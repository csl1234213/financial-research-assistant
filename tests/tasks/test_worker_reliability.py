import json
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import tasks
import tasks.worker as worker_module
import workers.agent_worker as agent_worker_module
from models.task import TaskStatus, TaskType
from tasks.heartbeat import WorkerHeartbeat, read_worker_health
from tasks.models import TaskType as WorkerTaskType
from tasks.worker import TaskExecutionError, TaskWorker


def _sleeping_handler(_task_public_id: str) -> None:
    time.sleep(30)


def _successful_handler(_task_public_id: str) -> None:
    return None


def _failing_handler(_task_public_id: str) -> None:
    raise ValueError("isolated handler failure")


def _task(status: str = TaskStatus.PENDING.value):
    return SimpleNamespace(
        public_id="task-reliability-001",
        status=status,
        task_type=TaskType.PROCESS_DOCUMENT.value,
        tenant_id=7,
        worker_id=None,
        locked_at=None,
        retry_count=0,
        error_message=None,
    )


def test_task_package_preserves_public_worker_export_lazily():
    assert tasks.TaskWorker is TaskWorker


def test_agent_entrypoint_uses_task_worker_default_identity(monkeypatch):
    worker = MagicMock()
    worker_factory = MagicMock(return_value=worker)
    registered_handlers = {}

    def register_handler(signum, handler):
        registered_handlers[signum] = handler

    def stop_after_first_tick(_seconds):
        registered_handlers[signal.SIGTERM](signal.SIGTERM, None)

    monkeypatch.setattr(agent_worker_module, "TaskWorker", worker_factory)
    monkeypatch.setattr(agent_worker_module.signal, "signal", register_handler)
    monkeypatch.setattr(agent_worker_module.time, "sleep", stop_after_first_tick)
    monkeypatch.setattr(agent_worker_module.sys, "argv", ["agent_worker"])

    assert agent_worker_module.main() == 0
    worker_factory.assert_called_once_with()
    worker.start.assert_called_once_with()
    worker.stop.assert_called_once_with()


def test_pending_stream_delivery_is_reclaimed_before_reading_new_work(monkeypatch):
    worker = TaskWorker(worker_id="reclaim-test")
    broker = MagicMock()
    broker.enabled = True
    broker.claim_pending_tasks.return_value = [
        {
            "task_id": "reclaimed-task",
            "_message_id": "stream-pending-001",
        }
    ]
    execute = MagicMock()

    monkeypatch.setattr(worker_module, "get_broker", lambda: broker)
    monkeypatch.setattr(worker, "_execute_task", execute)

    worker._process_next_task()

    broker.claim_pending_tasks.assert_called_once_with(
        min_idle_ms=worker_module.PENDING_RECLAIM_MIN_IDLE_MS,
        count=max(10, worker_module.WORKER_CONCURRENCY * 2),
    )
    broker.consume_task.assert_not_called()
    execute.assert_called_once_with(
        "reclaimed-task",
        message_id="stream-pending-001",
    )


def test_reclaimed_batch_is_drained_without_claiming_messages_twice():
    worker = TaskWorker(worker_id="reclaim-batch-test")
    broker = MagicMock()
    broker.claim_pending_tasks.return_value = [
        {"task_id": "task-1", "_message_id": "message-1"},
        {"task_id": "task-2", "_message_id": "message-2"},
    ]

    first = worker._claim_pending_message(broker)
    second = worker._claim_pending_message(broker)

    assert first["task_id"] == "task-1"
    assert second["task_id"] == "task-2"
    broker.claim_pending_tasks.assert_called_once()


def test_stale_recovery_waits_until_after_the_runtime_limit(monkeypatch):
    worker = TaskWorker(worker_id="stale-recovery-test")
    worker._last_recovery = datetime.now(timezone.utc) - timedelta(minutes=2)
    repo = MagicMock()
    repo.recover_stale_tasks.return_value = 0

    monkeypatch.setattr(worker_module, "get_task_repository", lambda: repo)
    monkeypatch.setattr(worker_module, "MAX_TASK_RUNTIME", 120)

    worker._recover_stale_if_needed()

    repo.recover_stale_tasks.assert_called_once_with(
        stale_after_seconds=(
            120 + worker_module.STALE_RECOVERY_GRACE_SECONDS
        )
    )
    repo._db.close.assert_called_once_with()


def test_handler_process_is_terminated_when_runtime_limit_expires(monkeypatch):
    worker = TaskWorker(worker_id="timeout-test")
    worker._running = True

    reader = MagicMock()
    writer = MagicMock()
    process = MagicMock()
    process.is_alive.side_effect = [True, False, False]
    context = MagicMock()
    context.Pipe.return_value = (reader, writer)
    context.Process.return_value = process

    monkeypatch.setattr(worker_module, "MAX_TASK_RUNTIME", 1)
    monkeypatch.setattr(
        worker_module.multiprocessing,
        "get_context",
        lambda method: context,
    )
    monotonic_values = iter([0.0, 2.0])
    monkeypatch.setattr(
        worker_module.time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(
        TaskExecutionError,
        match=r"exceeded MAX_TASK_RUNTIME \(1s\)",
    ):
        worker._run_handler_with_timeout(
            WorkerTaskType.PROCESS_DOCUMENT,
            "timeout-task",
        )

    process.start.assert_called_once_with()
    process.terminate.assert_called_once_with()
    process.kill.assert_not_called()
    writer.close.assert_called_once_with()
    reader.close.assert_called_once_with()
    process.close.assert_called_once_with()


def test_runtime_limit_terminates_a_real_isolated_handler(monkeypatch):
    worker = TaskWorker(worker_id="real-timeout-test")
    worker._running = True
    monkeypatch.setattr(worker_module, "MAX_TASK_RUNTIME", 1)
    monkeypatch.setitem(
        worker_module._HANDLERS,
        WorkerTaskType.PROCESS_DOCUMENT,
        "tests.tasks.test_worker_reliability:_sleeping_handler",
    )

    started_at = time.monotonic()
    with pytest.raises(
        TaskExecutionError,
        match=r"exceeded MAX_TASK_RUNTIME \(1s\)",
    ):
        worker._run_handler_with_timeout(
            WorkerTaskType.PROCESS_DOCUMENT,
            "real-timeout-task",
        )

    assert time.monotonic() - started_at < 10


@pytest.mark.parametrize(
    ("handler_name", "expected_error"),
    [
        ("_successful_handler", None),
        ("_failing_handler", "ValueError: isolated handler failure"),
    ],
)
def test_isolated_handler_reports_success_and_failure(
    monkeypatch,
    handler_name,
    expected_error,
):
    worker = TaskWorker(worker_id="isolated-result-test")
    worker._running = True
    monkeypatch.setattr(worker_module, "MAX_TASK_RUNTIME", 10)
    monkeypatch.setitem(
        worker_module._HANDLERS,
        WorkerTaskType.PROCESS_DOCUMENT,
        f"tests.tasks.test_worker_reliability:{handler_name}",
    )

    if expected_error is None:
        worker._run_handler_with_timeout(
            WorkerTaskType.PROCESS_DOCUMENT,
            "isolated-success-task",
        )
    else:
        with pytest.raises(TaskExecutionError, match=expected_error):
            worker._run_handler_with_timeout(
                WorkerTaskType.PROCESS_DOCUMENT,
                "isolated-failure-task",
            )


def test_timeout_is_persisted_as_failure_and_stream_message_is_acked(monkeypatch):
    worker = TaskWorker(worker_id="timeout-status-test")
    task = _task()
    repo = MagicMock()
    repo.get_task.return_value = task

    def claim_task(_task_id):
        task.status = TaskStatus.RUNNING.value
        return task

    def update_task(_task_id, *, status=None, error_message=None, **_kwargs):
        if status is not None:
            task.status = status.value
        if error_message is not None:
            task.error_message = error_message
        return task

    repo.claim_task.side_effect = claim_task
    repo.update_task.side_effect = update_task
    broker = MagicMock()

    monkeypatch.setattr(worker_module, "get_task_repository", lambda: repo)
    monkeypatch.setattr(worker_module, "get_broker", lambda: broker)
    monkeypatch.setattr(worker_module, "should_retry", lambda _count: False)
    monkeypatch.setattr(
        worker,
        "_run_handler_with_timeout",
        MagicMock(
            side_effect=TaskExecutionError(
                "Task exceeded MAX_TASK_RUNTIME (1s)"
            )
        ),
    )

    worker._execute_task(
        task.public_id,
        message_id="stream-timeout-001",
    )

    assert task.status == TaskStatus.FAILED.value
    assert task.error_message == "Task exceeded MAX_TASK_RUNTIME (1s)"
    broker.ack_task.assert_called_once_with(
        task.public_id,
        "stream-timeout-001",
    )


def test_successful_database_heartbeat_writes_a_live_health_signal(
    monkeypatch,
    tmp_path,
):
    health_file = tmp_path / "worker-health.json"
    heartbeat = WorkerHeartbeat(
        worker_id="health-test",
        hostname="test-host",
        health_file=health_file,
    )
    heartbeat._db = MagicMock()
    monkeypatch.setattr(heartbeat, "_send_with_db", lambda _db: True)

    assert heartbeat.send() is True

    payload = json.loads(health_file.read_text(encoding="utf-8"))
    assert payload["worker_id"] == "health-test"
    assert payload["pid"] == os.getpid()
    assert read_worker_health(
        max_age_seconds=5,
        health_file=health_file,
    ) == (True, "worker health-test is healthy")

    heartbeat.clear_health_signal()
    assert not health_file.exists()


def test_agent_worker_healthcheck_reads_the_runtime_signal(
    monkeypatch,
    tmp_path,
):
    health_file = tmp_path / "worker-health.json"
    heartbeat = WorkerHeartbeat(
        worker_id="cli-health-test",
        hostname="test-host",
        health_file=health_file,
    )
    heartbeat._db = MagicMock()
    monkeypatch.setattr(heartbeat, "_send_with_db", lambda _db: True)
    assert heartbeat.send() is True

    monkeypatch.setenv("WORKER_HEALTH_FILE", str(health_file))
    monkeypatch.setattr(
        agent_worker_module.sys,
        "argv",
        ["agent_worker", "--healthcheck"],
    )

    assert agent_worker_module.main() == 0


def test_stale_worker_health_signal_is_rejected(tmp_path):
    health_file = tmp_path / "worker-health.json"
    health_file.write_text(
        json.dumps(
            {
                "worker_id": "stale-worker",
                "hostname": "test-host",
                "pid": os.getpid(),
                "timestamp": 0,
            }
        ),
        encoding="utf-8",
    )

    healthy, message = read_worker_health(
        max_age_seconds=5,
        health_file=health_file,
    )

    assert healthy is False
    assert "stale" in message


def test_health_signal_for_missing_process_is_rejected(tmp_path):
    health_file = tmp_path / "worker-health.json"
    health_file.write_text(
        json.dumps(
            {
                "worker_id": "missing-worker",
                "hostname": "test-host",
                "pid": 2_147_483_647,
                "timestamp": datetime.now(timezone.utc).timestamp(),
            }
        ),
        encoding="utf-8",
    )

    healthy, message = read_worker_health(
        max_age_seconds=5,
        health_file=health_file,
    )

    assert healthy is False
    assert "not running" in message
