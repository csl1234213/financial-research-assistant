import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from models.task import Task as TaskModel
from models.task import TaskStatus, TaskType
from storage.database import SessionLocal
from tasks.dispatch_lifecycle import close_terminal_obligation, dispatchable_task_predicate, reopen_retry_obligation

STALE_TASK_TIMEOUT_MINUTES = 30


class TaskRepository:
    def __init__(self, db: Session):
        self._db = db

    def create_task(
        self,
        task_type: TaskType,
        payload: Dict[str, Any],
        tenant_id: int,
        user_id: int,
    ) -> TaskModel:
        if tenant_id is None:
            raise ValueError("tenant_id is required to create a task")

        public_id = uuid.uuid4().hex[:16]
        task = TaskModel(
            public_id=public_id,
            task_type=task_type.value,
            status=TaskStatus.PENDING.value,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        task.payload = payload
        self._db.add(task)
        self._db.commit()
        self._db.refresh(task)
        return task

    def get_task(self, task_id: str) -> Optional[TaskModel]:
        return self._db.query(TaskModel).filter(TaskModel.public_id == task_id).first()

    def list_tasks(
        self,
        tenant_id: Optional[int] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        query = self._db.query(TaskModel)

        if tenant_id is not None:
            query = query.filter(TaskModel.tenant_id == tenant_id)
        if status is not None:
            query = query.filter(TaskModel.status == status)

        total = query.count()
        items = (
            query.order_by(TaskModel.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    def claim_task(self, task_id: Optional[str] = None) -> Optional[TaskModel]:
        """Atomically claim the next pending task, or one known task by public ID."""
        query = self._db.query(TaskModel).filter(TaskModel.status == TaskStatus.PENDING.value)
        if task_id is not None:
            query = query.filter(TaskModel.public_id == task_id)

        task = (
            query.with_for_update(skip_locked=True)
            .order_by(TaskModel.created_at.asc())
            .first()
        )

        if task is None:
            return None

        task.status = TaskStatus.RUNNING.value
        task.started_at = datetime.now(timezone.utc)
        task.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(task)
        return task

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        error_message: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[TaskModel]:
        task = (
            self._db.query(TaskModel).filter(TaskModel.public_id == task_id)
            .populate_existing().with_for_update().first()
        )
        if task is None:
            return None

        if status is not None:
            previous_status = task.status
            # A stale handler failure/retry must not undo committed success.
            if previous_status == TaskStatus.SUCCESS.value and status != TaskStatus.SUCCESS:
                return task
            task.status = status.value
            if status == TaskStatus.SUCCESS or status == TaskStatus.FAILED:
                task.completed_at = datetime.now(timezone.utc)
                close_terminal_obligation(task)
            elif status == TaskStatus.PENDING and previous_status == TaskStatus.FAILED.value:
                # FAILED can be transient in the worker. Reopen only the prior
                # withdrawn obligation, and never when formal source is terminal.
                # Runtime SessionLocal disables autoflush: predicate must see the
                # tentative PENDING state inside this same locked transaction.
                self._db.flush()
                if self._db.query(TaskModel.id).filter(
                    TaskModel.id == task.id, dispatchable_task_predicate()
                ).first() is not None:
                    reopen_retry_obligation(task, previous_status=previous_status)
                elif task.task_type == TaskType.FORMAL_READY_DOCUMENT.value:
                    task.status = previous_status
        if progress is not None:
            task.progress = progress
        if error_message is not None:
            task.error_message = error_message
        if result is not None:
            task.result = result

        task.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(task)
        return task

    def recover_stale_tasks(
        self,
        *,
        stale_after_seconds: int | float | None = None,
    ) -> int:
        if stale_after_seconds is None:
            stale_after_seconds = STALE_TASK_TIMEOUT_MINUTES * 60
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be greater than zero")

        stale_threshold = datetime.now(timezone.utc) - timedelta(
            seconds=stale_after_seconds
        )
        stale_tasks = (
            self._db.query(TaskModel)
            .filter(
                and_(
                    TaskModel.status == TaskStatus.RUNNING.value,
                    TaskModel.started_at < stale_threshold,
                )
            )
            .all()
        )

        count = 0
        for task in stale_tasks:
            task.status = TaskStatus.PENDING.value
            task.started_at = None
            task.updated_at = datetime.now(timezone.utc)
            count += 1

        if count > 0:
            self._db.commit()

        return count

    def delete_task(self, task_id: str) -> bool:
        task = self._db.query(TaskModel).filter(TaskModel.public_id == task_id).first()
        if task is None:
            return False
        self._db.delete(task)
        self._db.commit()
        return True


def get_task_repository() -> TaskRepository:

    db = SessionLocal()
    return TaskRepository(db)
