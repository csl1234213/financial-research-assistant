"""Authenticated, principal-scoped Agent session lifecycle endpoints."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from api.schemas.agent_sessions import (
    AgentSessionDeleteResponse,
    AgentSessionDetailResponse,
    AgentSessionExportResponse,
    AgentSessionListResponse,
    AgentSessionMessageResponse,
    AgentSessionSummaryResponse,
)
from api.schemas.thread import MAX_THREAD_ID_LENGTH, validate_thread_id
from auth.dependencies import get_current_user
from cache.session import session_cache
from models.user import User
from services.agent_runtime.checkpointing import delete_scoped_checkpoint_thread
from storage.agent.models import AgentMessage, AgentSession
from storage.agent.repository import AgentRepository
from storage.database import get_db

router = APIRouter(prefix="/agent/sessions", tags=["Agent Sessions"])

ThreadId = Annotated[
    str,
    Path(min_length=1, max_length=MAX_THREAD_ID_LENGTH),
]


def _validate_thread_id(thread_id: str) -> str:
    try:
        validate_thread_id(thread_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return thread_id


def _message_response(message: AgentMessage) -> AgentSessionMessageResponse:
    return AgentSessionMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        metadata=message.metadata_dict,
        created_at=message.created_at,
    )


def _summary_response(
    session: AgentSession,
    message_count: int,
) -> AgentSessionSummaryResponse:
    return AgentSessionSummaryResponse(
        thread_id=session.thread_id,
        message_count=message_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("", response_model=AgentSessionListResponse)
def list_agent_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentSessionListResponse:
    repo = AgentRepository(db)
    rows, total = repo.list_sessions(
        current_user.tenant_id,
        current_user.id,
        limit=limit,
        offset=offset,
    )
    return AgentSessionListResponse(
        items=[
            _summary_response(row.session, row.message_count)
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{thread_id}", response_model=AgentSessionDetailResponse)
def get_agent_session(
    thread_id: ThreadId,
    message_limit: int = Query(default=100, ge=1, le=500),
    message_offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentSessionDetailResponse:
    thread_id = _validate_thread_id(thread_id)
    repo = AgentRepository(db)
    session = repo.get_session(
        current_user.tenant_id,
        current_user.id,
        thread_id,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent session not found",
        )

    messages, total = repo.list_messages(
        session.id,
        limit=message_limit,
        offset=message_offset,
    )
    return AgentSessionDetailResponse(
        session=_summary_response(session, total),
        messages=[_message_response(message) for message in messages],
        total_messages=total,
        limit=message_limit,
        offset=message_offset,
    )


@router.get("/{thread_id}/export", response_model=AgentSessionExportResponse)
def export_agent_session(
    thread_id: ThreadId,
    limit: int = Query(default=1000, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentSessionExportResponse:
    thread_id = _validate_thread_id(thread_id)
    repo = AgentRepository(db)
    session = repo.get_session(
        current_user.tenant_id,
        current_user.id,
        thread_id,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent session not found",
        )

    messages, total = repo.list_messages(
        session.id,
        limit=limit,
        offset=offset,
    )
    return AgentSessionExportResponse(
        exported_at=datetime.now(timezone.utc),
        session=_summary_response(session, total),
        messages=[_message_response(message) for message in messages],
        total_messages=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{thread_id}", response_model=AgentSessionDeleteResponse)
def delete_agent_session(
    thread_id: ThreadId,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentSessionDeleteResponse:
    thread_id = _validate_thread_id(thread_id)
    repo = AgentRepository(db)
    session = repo.get_session(
        current_user.tenant_id,
        current_user.id,
        thread_id,
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent session not found",
        )

    runtime_deleted = delete_scoped_checkpoint_thread(
        current_user.tenant_id,
        current_user.id,
        thread_id,
    )
    if not runtime_deleted:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to delete Agent runtime checkpoint",
        )

    cache_deletion = session_cache.delete_thread(
        thread_id,
        current_user.tenant_id,
        user_id=current_user.id,
    )
    if not cache_deletion.successful:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to delete Agent session cache",
        )

    deletion = repo.delete_session(
        current_user.tenant_id,
        current_user.id,
        thread_id,
    )
    if deletion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent session not found",
        )

    return AgentSessionDeleteResponse(
        thread_id=thread_id,
        messages_deleted=deletion.messages_deleted,
        checkpoints_archived=deletion.checkpoints_archived,
        runtime_checkpoints_deleted=runtime_deleted,
        cache_keys_deleted=cache_deletion.keys_deleted,
    )
