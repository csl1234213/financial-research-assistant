"""Explicit formal task handler; legacy PROCESS_DOCUMENT never enters here."""

import time

from sqlalchemy import select

from models.task import Task, TaskType


def process_formal_ready_task(task_id):
    from services.rc1_delivery import get_delivery

    delivery = get_delivery()
    with delivery.repository.session_factory() as session:
        task = session.scalar(select(Task).where(Task.public_id == task_id))
        if task is None or task.task_type != TaskType.FORMAL_READY_DOCUMENT.value:
            raise ValueError("FORMAL_TASK_KIND_REQUIRED")
        tenant_id, user_id = task.tenant_id, task.user_id
    # Existing worker subprocess owns the total task deadline. Never consume a
    # retry/lease-busy delivery as successful or bypass the durable stage ledger.
    while True:
        result = delivery.runner.run(task_id, tenant_id=tenant_id, user_id=user_id)
        if result == "ready":
            return
        if result in {"failed", "quarantined"}:
            raise ValueError("FORMAL_INGESTION_TERMINAL_FAILURE")
        if result not in {"retry_pending", "lease_busy"}:
            raise ValueError("FORMAL_INGESTION_INVALID_RESULT")
        time.sleep(1)
