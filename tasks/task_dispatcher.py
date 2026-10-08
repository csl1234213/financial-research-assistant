"""Task-backed at-least-once delivery. Execution state is never changed."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select

from models.task import Task, TaskType
from storage.ingestion_transactions import require_aware, serialize_sqlite, utc
from tasks.dispatch_lifecycle import dispatchable_task_predicate


@dataclass(frozen=True)
class TaskDispatchLease:
    task_id: str
    token: str
    tenant_id: int
    task_type: str


class TaskDispatcher:
    def __init__(self, session_factory, *, max_attempts=3, lease_seconds=30):
        if not 1 <= max_attempts <= 10 or not 1 <= lease_seconds <= 300:
            raise ValueError("INVALID_DISPATCH_POLICY")
        self.session_factory = session_factory
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds

    def claim(self, now):
        require_aware(now)
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            task = session.scalar(
                select(Task)
                .where(
                    dispatchable_task_predicate(),
                    Task.task_type.in_([
                        TaskType.PROCESS_DOCUMENT.value, TaskType.FORMAL_READY_DOCUMENT.value,
                    ]),
                    or_(
                        and_(
                            Task.dispatch_state == "pending",
                            or_(Task.dispatch_next_attempt_at.is_(None), Task.dispatch_next_attempt_at <= now),
                        ),
                        and_(Task.dispatch_state == "leased", Task.dispatch_lease_expires_at <= now),
                    ),
                )
                .order_by(Task.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if task is None:
                return None
            if task.dispatch_attempt_count >= self.max_attempts:
                task.dispatch_state = "failed"
                task.dispatch_error_code = "DISPATCH_RETRY_EXHAUSTED"
                task.dispatch_lease_token = task.dispatch_lease_expires_at = None
                return None
            task.dispatch_attempt_count += 1
            task.dispatch_state = "leased"
            task.dispatch_lease_token = uuid4().hex
            task.dispatch_lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            task.dispatch_next_attempt_at = None
            return TaskDispatchLease(task.public_id, task.dispatch_lease_token, task.tenant_id, task.task_type)

    def finish(self, lease, *, delivered, now, retryable=True):
        require_aware(now)
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            task = session.scalar(
                select(Task).where(Task.public_id == lease.task_id, dispatchable_task_predicate()).with_for_update()
            )
            return self._finish_locked(task, lease, delivered=delivered, now=now, retryable=retryable)

    def _finish_locked(self, task, lease, *, delivered, now, retryable):
        if not self._current(task, lease, now):
            return False
        if delivered:
            task.dispatch_state, task.dispatch_error_code = "delivered", None
        elif retryable and task.dispatch_attempt_count < self.max_attempts:
            task.dispatch_state = "pending"
            task.dispatch_next_attempt_at = now + timedelta(seconds=min(60, 2**task.dispatch_attempt_count))
            task.dispatch_error_code = "DISPATCH_TRANSPORT_FAILURE"
        else:
            task.dispatch_state, task.dispatch_error_code = "failed", "DISPATCH_DELIVERY_FAILED"
        task.dispatch_lease_token = task.dispatch_lease_expires_at = None
        return True

    @staticmethod
    def _current(task, lease, now):
        return (
            task is not None
            and task.dispatch_state == "leased"
            and task.dispatch_lease_token == lease.token
            and task.dispatch_lease_expires_at is not None
            and utc(task.dispatch_lease_expires_at) > now
        )

    def dispatch_one(self, publisher, now):
        lease = self.claim(now)
        if lease is None:
            return "idle"
        # Claim alone does not authorize a later publication. A terminal transition
        # may have committed meanwhile. Recheck under the same Task lock used by
        # terminal authorities and hold it through publication/ack persistence.
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            task = session.scalar(
                select(Task).where(Task.public_id == lease.task_id, dispatchable_task_predicate()).with_for_update()
            )
            if not self._current(task, lease, now):
                return "lease_lost"
            try:
                delivered = bool(publisher(lease.task_id, lease.tenant_id, lease.task_type))
                retryable = True
            except (TimeoutError, ConnectionError):
                delivered, retryable = False, True
            except Exception:
                delivered, retryable = False, False
            self._finish_locked(task, lease, delivered=delivered, retryable=retryable, now=now)
            return "delivered" if delivered else "not_delivered"
