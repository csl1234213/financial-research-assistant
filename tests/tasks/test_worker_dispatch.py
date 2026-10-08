from types import SimpleNamespace
from unittest.mock import MagicMock

import tasks.worker as worker_module
from models.task import TaskStatus, TaskType
from tasks.models import TaskType as WorkerTaskType
from tasks.worker import TaskWorker


def _task(status: str = TaskStatus.PENDING.value):
    return SimpleNamespace(
        public_id="task-001",
        status=status,
        task_type=TaskType.PROCESS_DOCUMENT.value,
        tenant_id=7,
        worker_id=None,
        locked_at=None,
        retry_count=0,
    )


def test_database_poller_executes_a_task_it_already_claimed(monkeypatch):
    worker = TaskWorker(worker_id="dispatch-test")
    task = _task()
    repo = MagicMock()
    repo.claim_task.return_value = task
    broker = MagicMock()
    broker.enabled = False
    execute = MagicMock()

    monkeypatch.setattr("tasks.worker.get_broker", lambda: broker)
    monkeypatch.setattr("tasks.worker.get_task_repository", lambda: repo)
    monkeypatch.setattr(worker, "_execute_task", execute)

    worker._process_next_task()

    execute.assert_called_once_with("task-001", already_claimed=True)


def test_broker_message_claims_its_exact_task_and_is_acknowledged(monkeypatch):
    worker = TaskWorker(worker_id="dispatch-test")
    task = _task()
    repo = MagicMock()
    repo.get_task.return_value = task
    repo.claim_task.return_value = task
    broker = MagicMock()

    def _handler(task_id: str):
        assert task_id == task.public_id
        task.status = TaskStatus.SUCCESS.value

    monkeypatch.setattr("tasks.worker.get_broker", lambda: broker)
    monkeypatch.setattr("tasks.worker.get_task_repository", lambda: repo)
    monkeypatch.setitem(
        worker_module._HANDLERS,
        WorkerTaskType.PROCESS_DOCUMENT,
        _handler,
    )
    monkeypatch.setattr(
        worker,
        "_run_handler_with_timeout",
        lambda task_type, task_id: _handler(task_id),
    )

    worker._execute_task(task.public_id, message_id="stream-001")

    repo.claim_task.assert_called_once_with(task.public_id)
    assert task.worker_id == "dispatch-test"
    broker.ack_task.assert_called_once_with(task.public_id, "stream-001")


def test_already_claimed_database_task_is_not_claimed_twice(monkeypatch):
    worker = TaskWorker(worker_id="dispatch-test")
    task = _task(status=TaskStatus.RUNNING.value)
    repo = MagicMock()
    repo.get_task.return_value = task
    broker = MagicMock()

    def _handler(task_id: str):
        assert task_id == task.public_id
        task.status = TaskStatus.SUCCESS.value

    monkeypatch.setattr("tasks.worker.get_broker", lambda: broker)
    monkeypatch.setattr("tasks.worker.get_task_repository", lambda: repo)
    monkeypatch.setitem(
        worker_module._HANDLERS,
        WorkerTaskType.PROCESS_DOCUMENT,
        _handler,
    )
    monkeypatch.setattr(
        worker,
        "_run_handler_with_timeout",
        lambda task_type, task_id: _handler(task_id),
    )

    worker._execute_task(task.public_id, already_claimed=True)

    repo.claim_task.assert_not_called()
    assert task.worker_id == "dispatch-test"
