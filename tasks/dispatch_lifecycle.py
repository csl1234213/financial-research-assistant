"""Dispatch lifecycle rules; execution and transport outcomes remain distinct.

Existing ``none`` means no outstanding dispatch is required, including an active
obligation withdrawn by terminal execution. It never asserts transport delivery.
Already delivered/failed outcomes and attempt counters remain historical evidence.
Callers own the Task-first row lock and commit closure with the terminal transition.
"""

from sqlalchemy import and_, exists, or_, select

from models.document import Document
from models.ingestion_persistence import UploadSession
from models.task import Task, TaskStatus, TaskType

ACTIVE_DISPATCH_STATES = ("pending", "leased")
TERMINAL_DOCUMENT_STATES = ("ready", "failed", "quarantined")
TERMINAL_CLOSURE_CODE = "TASK_TERMINAL"


def dispatchable_task_predicate():
    """Fail closed for unknown task states and missing/terminal formal authority."""
    formal_source_active = exists(
        select(UploadSession.upload_id)
        .join(Document, Document.id == UploadSession.document_id)
        .where(
            UploadSession.task_id == Task.id,
            UploadSession.status == "FINALIZED",
            Document.status.not_in(TERMINAL_DOCUMENT_STATES),
        )
    )
    return and_(
        Task.status.in_((TaskStatus.PENDING.value, TaskStatus.RUNNING.value)),
        or_(Task.task_type != TaskType.FORMAL_READY_DOCUMENT.value, formal_source_active),
    )


def close_terminal_obligation(task):
    """Idempotently withdraw active dispatch without inventing a delivery."""
    if task.dispatch_state in ACTIVE_DISPATCH_STATES:
        task.dispatch_state = "none"
        task.dispatch_error_code = TERMINAL_CLOSURE_CODE
    # All terminal outcomes must have no outstanding lease/retry reservation.
    task.dispatch_lease_token = task.dispatch_lease_expires_at = None
    task.dispatch_next_attempt_at = None


def reopen_retry_obligation(task, *, previous_status):
    """Reopen only an obligation withdrawn on the worker's transient FAILED path.

No new obligation for historical none, no resetting attempts, no reopening an
exhausted transport outcome or a delivered message. Formal authority must already
have been checked by the caller; stage-level retry never closes its obligation.
"""
    if (
        previous_status == TaskStatus.FAILED.value
        and task.status == TaskStatus.PENDING.value
        and task.dispatch_state == "none"
        and task.dispatch_error_code == TERMINAL_CLOSURE_CODE
    ):
        task.dispatch_state = "pending"
        task.dispatch_error_code = None
