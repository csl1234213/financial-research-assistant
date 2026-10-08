import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tasks.models import Task, TaskStatus, TaskType


class TaskQueue:
    _instance: Optional["TaskQueue"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._queue: List[str] = []
        self._condition = threading.Condition()

    @classmethod
    def get_instance(cls) -> "TaskQueue":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def create_task(
        self,
        task_type: TaskType,
        payload: Dict[str, Any],
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Task:
        if tenant_id is None:
            raise ValueError("tenant_id is required to create a task")

        task_id = uuid.uuid4().hex[:16]
        task = Task(
            id=task_id,
            type=task_type,
            status=TaskStatus.PENDING,
            tenant_id=tenant_id,
            user_id=user_id,
            payload=payload,
        )
        self._tasks[task_id] = task
        return task

    def enqueue(self, task: Task) -> None:
        with self._condition:
            self._queue.append(task.id)
            self._condition.notify()

    def dequeue(self, timeout: float = 5.0) -> Optional[Task]:
        with self._condition:
            while not self._queue:
                if not self._condition.wait(timeout):
                    return None
            task_id = self._queue.pop(0)
            return self._tasks.get(task_id)

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        error_message: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if status is not None:
            task.status = status
        if progress is not None:
            task.progress = progress
        if error_message is not None:
            task.error_message = error_message
        if result is not None:
            task.result = result
        task.updated_at = datetime.now(timezone.utc).isoformat()
        return task

    def list_tasks(self, tenant_id: Optional[int] = None) -> List[Task]:
        tasks = list(self._tasks.values())
        if tenant_id is not None:
            tasks = [t for t in tasks if t.tenant_id == tenant_id]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)


_task_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue
