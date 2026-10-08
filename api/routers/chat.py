import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.schemas.request import ChatRequest
from api.schemas.response import ChatResponse
from api.services.chat_service import ChatService
from auth.dependencies import get_optional_user
from config import LLM_TOTAL_DEADLINE
from core.usage_events import ResourceType, UsageEvent
from llm.providers.provider_exceptions import ProviderTimeoutError
from models.user import User
from services.plan_service import can_chat
from services.usage_service import record_usage
from storage.database import get_db

router = APIRouter(tags=["Chat"])

chat_service = ChatService()
logger = logging.getLogger(__name__)


def _sse_event(event: str, payload: dict) -> str:
    """Serialize one Server-Sent Event without leaking raw model output."""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def _stream_verified_response(response: ChatResponse):
    """Stream only the final report after the normal grounding pipeline ends."""
    report = response.report
    # Chunk by Python Unicode code points; JSON/SSE handles UTF-8 encoding.
    for offset in range(0, len(report), 48):
        yield _sse_event("delta", {"text": report[offset : offset + 48]})
    yield _sse_event("complete", response.model_dump(mode="json"))


def _stream_chat_events(
    *,
    request: ChatRequest,
    current_user: Optional[User],
    db: Session,
):
    """Run the ordinary chat/grounding path, then stream its verified result."""
    yield _sse_event("status", {"state": "processing"})
    try:
        response = chat_service.chat(
            question=request.question,
            company=request.company,
            answer_language=request.answer_language,
            tenant_id=current_user.tenant_id if current_user is not None else None,
            user_id=current_user.id if current_user is not None else None,
            thread_id=request.thread_id,
            deadline=time.monotonic() + LLM_TOTAL_DEADLINE,
        )
    except ProviderTimeoutError:
        yield _sse_event(
            "error",
            {"status": 504, "detail": "The AI provider exceeded the request deadline. Please retry later."},
        )
        return
    except Exception:
        # Keep internal exception details and upstream response bodies private.
        logger.exception("chat_stream_generation_failed")
        yield _sse_event("error", {"status": 500, "detail": "Chat request failed."})
        return

    if current_user is not None:
        try:
            record_usage(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                event_type=UsageEvent.CHAT_REQUEST,
                resource_type=ResourceType.CHAT,
                quantity=1,
                metadata={"endpoint": "/api/v1/chat", "stream": True},
                db=db,
            )
        except Exception:
            logger.exception("chat_stream_usage_recording_failed")
            yield _sse_event("error", {"status": 500, "detail": "Chat request failed."})
            return

    yield from _stream_verified_response(response)


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user is not None and not can_chat(db, current_user.tenant_id):
        raise HTTPException(status_code=429, detail="Chat limit exceeded. Upgrade your plan.")

    if request.stream:
        return StreamingResponse(
            _stream_chat_events(request=request, current_user=current_user, db=db),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    try:
        response = chat_service.chat(
            question=request.question,
            company=request.company,
            answer_language=request.answer_language,
            tenant_id=current_user.tenant_id if current_user is not None else None,
            user_id=current_user.id if current_user is not None else None,
            thread_id=request.thread_id,
            deadline=time.monotonic() + LLM_TOTAL_DEADLINE,
        )
    except ProviderTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="The AI provider exceeded the request deadline. Please retry later.",
        ) from exc

    if current_user is not None:
        record_usage(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            event_type=UsageEvent.CHAT_REQUEST,
            resource_type=ResourceType.CHAT,
            quantity=1,
            metadata={"endpoint": "/api/v1/chat"},
            db=db,
        )

    return response
