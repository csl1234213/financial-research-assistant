import logging
import time
from typing import Optional

from api.schemas.response import ChatResponse
from llm.usage import collect_usage, summarize_usage
from services.agent_runtime.runtime import run_agent

logger = logging.getLogger(__name__)


class ChatService:
    """
    V5 Chat Service

    Single entry point for all clients (HTTP, CLI, Streamlit, etc.).

    Pipeline:
    Planning → Workflow → Execution → Routing → Provider
    """

    def chat(
        self,
        question: str,
        company: Optional[str] = None,
        *,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        thread_id: Optional[str] = None,
        answer_language: str | None = None,
        deadline: float | None = None,
    ) -> ChatResponse:
        t0 = time.monotonic()
        logger.info(
            "chat_request_start thread_id=%s question_chars=%s",
            thread_id or "default",
            len(question),
        )

        with collect_usage() as usage_calls:
            run_kwargs = {
                "question": question,
                "company": company,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "thread_id": thread_id or "default",
                "answer_language": answer_language,
            }
            if deadline is not None:
                run_kwargs["deadline"] = deadline
            result = run_agent(
                **run_kwargs,
            )
        intent_result = result.get("intent") or {}
        plan_dict = result.get("plan") or {}

        reasoning = {
            "intent": intent_result.get("intent", ""),
             "companies": intent_result.get("companies") or [],
            "research_mode": result.get("research_mode", "default"),
            "evidence_count": result.get("evidence_count", 0),
        }

        execution_time = round(time.monotonic() - t0, 3)
        logger.info(
            "chat_request_end thread_id=%s duration_ms=%.2f",
            thread_id or "default",
            execution_time * 1000,
        )

        return ChatResponse(
            report=result.get("answer", ""),
            citations=result.get("citations", []),
            reasoning=reasoning,
            plan=plan_dict,
            execution_time=execution_time,
            routing=result.get("routing"),
            planning=result.get("planning"),
            execution=result.get("execution"),
            workflow=result.get("workflow"),
            usage=summarize_usage(usage_calls),
        )
