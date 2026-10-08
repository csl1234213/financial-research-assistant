import logging
import time

from billing.calculator import calculate_cost
from billing.models import BillingRecord
from core.usage_events import ResourceType, UsageEvent
from models.task import TaskStatus
from services.agent_runtime.runtime import run_agent
from services.usage_service import record_usage
from storage.database import SessionLocal
from tasks.repository import get_task_repository

logger = logging.getLogger(__name__)


def agent_task_handler(task_public_id: str):
    """
    Handle AGENT_TASK: execute run_agent() and persist result.

    Flow:
        1. Load task from DB
        2. Update status → RUNNING
        3. Execute run_agent()
        4. Save result
        5. Update status → SUCCESS
        6. Record usage

    On failure → FAILED (retry handled by worker)
    """
    repo = get_task_repository()
    try:
        task = repo.get_task(task_public_id)
        if task is None:
            logger.warning(f"Agent task {task_public_id} not found")
            return

        tenant_id = task.tenant_id
        user_id = task.user_id
        payload = task.payload
        question = payload.get("question", "")
        thread_id = payload.get("thread_id", "default")

        if not question:
            repo.update_task(
                task_public_id,
                status=TaskStatus.FAILED,
                error_message="question is required for agent task",
            )
            return

        repo.update_task(task_public_id, progress=10)

        t0 = time.time()
        result = run_agent(
            question=question,
            thread_id=thread_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        duration = round(time.time() - t0, 3)

        repo.update_task(
            task_public_id,
            status=TaskStatus.SUCCESS,
            progress=100,
            result={
                "answer": result.get("answer", ""),
                "thread_id": result.get("thread_id", thread_id),
                "tools_used": result.get("tools_used", []),
                "sources": result.get("sources", []),
                "companies": result.get("companies", []),
                "quality_score": result.get("quality_score", 0.0),
                "duration": duration,
            },
        )

        db_usage = SessionLocal()
        try:
            record_usage(
                tenant_id=tenant_id,
                user_id=user_id,
                event_type=UsageEvent.CHAT_REQUEST,
                resource_type=ResourceType.CHAT,
                quantity=1,
                metadata={
                    "endpoint": "/api/v1/agent/tasks",
                    "thread_id": thread_id,
                    "tools_used": result.get("tools_used", []),
                    "quality_score": result.get("quality_score", 0.0),
                    "duration": duration,
                    "latency_ms": int(duration * 1000),
                    "retrieval_count": len(result.get("sources", [])),
                    "token_usage": result.get("token_usage", {}),
                    "agent_type": "langgraph_async",
                    "task_id": task_public_id,
                    "error": None,
                },
                db=db_usage,
            )
        finally:
            db_usage.close()

        db_billing = SessionLocal()
        try:
            token_usage = result.get("token_usage", {})
            tools_used = result.get("tools_used", [])
            cost = calculate_cost(
                token_usage=token_usage,
                duration_seconds=duration,
                tool_calls=len(tools_used),
            )
            billing = BillingRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                resource_type=ResourceType.CHAT,
                quantity=1,
                unit_price=cost["total_cost"],
                amount=cost["total_cost"],
                currency=cost["currency"],
            )
            db_billing.add(billing)
            db_billing.commit()
            logger.info(
                f"Billing record created for task {task_public_id}: "
                f"cost=${cost['total_cost']}, tokens={cost['total_tokens']}"
            )
        finally:
            db_billing.close()

        logger.info(
            f"Agent task {task_public_id} completed: "
            f"score={result.get('quality_score', 0)}, duration={duration}s"
        )

    except Exception as e:
        logger.exception(f"Agent task {task_public_id} failed: {e}")
        repo.update_task(
            task_public_id,
            status=TaskStatus.FAILED,
            error_message=str(e),
        )
