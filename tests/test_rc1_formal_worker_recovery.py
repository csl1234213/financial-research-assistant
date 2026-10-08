"""Release gate: the queue worker must preserve formal terminal failures.

Use migrated PostgreSQL and the real handler, runner, executor and ledger.
Only subprocess transport and the external broker are replaced in this test.
"""

import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

import services.rc1_delivery as delivery_module
import tasks.formal_ready_tasks as formal_handler_module
import tasks.worker as worker_module
from core.ingestion_contracts import STAGES
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task, TaskStatus, TaskType
from services.formal_ingestion_composition import FormalIngestionComposition
from storage.chroma_store import ChromaEmbeddingStore
from storage.ingestion_artifacts import IngestionArtifactStore
from tasks.formal_ingestion_ledger import FormalIngestionLedger
from tasks.formal_ready_tasks import process_formal_ready_task
from tasks.ingestion_stage_executor import IngestionStageExecutor
from tasks.ingestion_task_runner import IngestionTaskRunner
from tasks.models import TaskType as WorkerTaskType
from tasks.repository import TaskRepository
from tests.formal_contract_data import NOW
from tests.formal_ingestion_test_harness import SOURCE, formal  # noqa: F401


def _wire_worker(runtime, factory, monkeypatch):
    monkeypatch.setattr(delivery_module, "get_delivery", lambda: runtime)
    monkeypatch.setattr(worker_module, "get_task_repository", lambda: TaskRepository(factory()))
    broker = Mock()
    monkeypatch.setattr(worker_module, "get_broker", lambda: broker)
    monkeypatch.setattr(worker_module, "get_heartbeat", lambda *_args: Mock())
    worker = worker_module.TaskWorker(worker_id="formal-recovery-matrix")

    def invoke_actual_handler(task_type, public_id):
        assert task_type == WorkerTaskType.FORMAL_READY_DOCUMENT
        process_formal_ready_task(public_id)

    monkeypatch.setattr(worker, "_run_handler_with_timeout", invoke_actual_handler)
    return worker, broker, invoke_actual_handler


@pytest.fixture
def worker_runtime(formal, tmp_path, monkeypatch):  # noqa: F811
    _, _, factory = formal
    clock = SimpleNamespace(now=NOW)
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        runtime = FormalIngestionComposition(
            factory, storage_root=tmp_path / "uploads", artifact_root=tmp_path / "artifacts",
            vectors=vectors, embedder=lambda texts: [[1.0, len(text) / 10000] for text in texts],
            embedding_identity="formal-offline-fixture", clock=lambda: clock.now,
        )
        data = SOURCE.read_bytes()
        upload = runtime.upload.create(
            tenant_id=1, user_id=2, filename="report.pdf", size=len(data),
            sha256=hashlib.sha256(data).hexdigest(), mime_type="application/pdf",
        )
        runtime.upload.receive(upload.upload_id, 1, 2, data)
        task_id = runtime.upload.finalize(upload.upload_id, 1, 2).ingestion_job_id
        worker, broker, invoke = _wire_worker(runtime, factory, monkeypatch)
        yield SimpleNamespace(
            runtime=runtime, task_id=task_id, worker=worker, broker=broker,
            invoke=invoke, factory=factory, clock=clock,
        )


def _checkpoint_state(case):
    with case.factory() as session:
        task = session.scalar(select(Task).where(Task.public_id == case.task_id))
        rows = session.scalars(select(TaskStageCheckpoint).where(TaskStageCheckpoint.task_id == task.id)).all()
        return {row.stage: (row.status, row.attempt_count, row.artifact_sha256) for row in rows}


def _assert_not_ready(case):
    assert case.runtime.ledger.status(case.task_id, 1, 2)["status"] != "ready"
    with pytest.raises(ValueError, match="DOCUMENT_NOT_READY"):
        case.runtime.ledger.ready_index(case.task_id, 1, 2)


def _assert_task(case, status, retries):
    with case.factory() as session:
        task = session.scalar(select(Task).where(Task.public_id == case.task_id))
        assert task.status == status and task.retry_count == retries


def _assert_ready(case):
    assert case.runtime.ledger.status(case.task_id, 1, 2)["status"] == "ready"
    assert all(value[0] == "complete" for value in _checkpoint_state(case).values())
    case.runtime.ledger.ready_index(case.task_id, 1, 2)


def test_terminal_formal_failure_survives_queue_worker(
    formal, tmp_path, monkeypatch, record_property,  # noqa: F811
):
    _, repository, factory = formal
    task_id = repository.finalize("upload-1", 1, 2, NOW).ingestion_job_id
    ledger = FormalIngestionLedger(
        factory, artifact_store=IngestionArtifactStore(tmp_path / "artifacts"),
    )

    def invalid_source(_lease):
        raise ValueError("SOURCE_REJECTED")

    executor = IngestionStageExecutor(
        ledger, source_resolver=invalid_source, clock=lambda: NOW,
    )
    delivery = SimpleNamespace(repository=repository, runner=IngestionTaskRunner(executor))
    monkeypatch.setattr(delivery_module, "get_delivery", lambda: delivery)
    monkeypatch.setattr(worker_module, "get_task_repository", lambda: TaskRepository(factory()))
    broker = Mock()
    monkeypatch.setattr(worker_module, "get_broker", lambda: broker)
    monkeypatch.setattr(worker_module, "get_heartbeat", lambda *_args: Mock())
    worker = worker_module.TaskWorker(worker_id="formal-recovery-acceptance")

    def invoke_actual_handler(task_type, public_id):
        assert task_type == WorkerTaskType.FORMAL_READY_DOCUMENT
        process_formal_ready_task(public_id)

    monkeypatch.setattr(worker, "_run_handler_with_timeout", invoke_actual_handler)
    worker._execute_task(task_id, message_id="isolated-formal-terminal")

    state = ledger.status(task_id, 1, 2)
    with factory() as session:
        task = session.scalar(select(Task).where(Task.public_id == task_id))
        checkpoint = session.scalar(select(TaskStageCheckpoint).where(
            TaskStageCheckpoint.task_id == task.id, TaskStageCheckpoint.stage == "PARSING",
        ))
        document = session.get(Document, checkpoint.document_id)
        record_property("FORMAL_LEDGER_STATUS", state["status"])
        record_property("DOCUMENT_STATUS", document.status)
        record_property("CHECKPOINT_STATUS", checkpoint.status)
        record_property("QUEUE_TASK_STATUS", task.status)
        record_property("QUEUE_RETRY_COUNT", task.retry_count)
        record_property("BROKER_RETRY_CALLS", broker.retry_task.call_count)
        assert state["status"] == "failed" and not state["retryable"]
        assert document.status == "failed" and checkpoint.status == "failed"
        assert checkpoint.attempt_count == 1 and state["completed_stages"] == []
        assert task.status == TaskStatus.FAILED.value, (
            "Formal terminal failure was overwritten by queue retry: "
            f"task={task.status}, document={document.status}, "
            f"checkpoint={checkpoint.status}, retries={task.retry_count}"
        )
        assert task.retry_count == 0
    broker.retry_task.assert_not_called()
    broker.ack_task.assert_called_once_with(task_id, "isolated-formal-terminal")


@pytest.mark.parametrize("stage", STAGES)
def test_five_stage_terminal_failure_never_requeued(worker_runtime, monkeypatch, stage, record_property):
    case = worker_runtime
    operators = dict(zip(STAGES, (
        case.runtime.executor.parser, case.runtime.executor.quality, case.runtime.executor.facts,
        case.runtime.executor.tree, case.runtime.executor.index,
    )))
    monkeypatch.setattr(operators[stage], "execute", Mock(side_effect=ValueError("NON_RETRYABLE_STAGE")))
    case.worker._execute_task(case.task_id, message_id="terminal-stage")
    state = case.runtime.ledger.status(case.task_id, 1, 2)
    graph = _checkpoint_state(case)
    assert state["status"] == "failed" and not state["retryable"]
    assert state["completed_stages"] == list(STAGES[:STAGES.index(stage)])
    assert graph[stage][:2] == ("failed", 1)
    _assert_task(case, "failed", 0)
    _assert_not_ready(case)
    case.broker.retry_task.assert_not_called()
    case.broker.ack_task.assert_called_once_with(case.task_id, "terminal-stage")
    with case.factory() as session:
        assert session.scalar(select(Document.status)) == "failed"
    record_property("TERMINAL_STAGE", stage)
    record_property("BROKER_RETRY_CALLS", 0)
    record_property("PREMATURE_READY", 0)


def test_quality_quarantine_is_not_queue_retry(worker_runtime, monkeypatch):
    case = worker_runtime
    execute = case.runtime.executor.quality.execute

    def quarantine(*args, **kwargs):
        receipt = execute(*args, **kwargs)
        return dict(receipt, quality_status="FAIL")

    monkeypatch.setattr(case.runtime.executor.quality, "execute", quarantine)
    case.worker._execute_task(case.task_id)
    assert case.runtime.ledger.status(case.task_id, 1, 2)["status"] == "quarantined"
    assert _checkpoint_state(case)["QUALITY_CHECK"][0] == "quarantined"
    _assert_task(case, "failed", 0)
    _assert_not_ready(case)
    case.broker.retry_task.assert_not_called()


def test_formal_retryable_stage_failure_can_recover(worker_runtime, monkeypatch):
    case = worker_runtime
    execute = case.runtime.executor.parser.execute
    transient = Mock(side_effect=TimeoutError("TRANSIENT_STAGE"))
    monkeypatch.setattr(case.runtime.executor.parser, "execute", transient)
    monkeypatch.setattr(formal_handler_module.time, "sleep", Mock(
        side_effect=worker_module.TaskExecutionError("PROCESS_INTERRUPTED_DURING_BACKOFF"),
    ))
    case.worker._execute_task(case.task_id)
    state = case.runtime.ledger.status(case.task_id, 1, 2)
    assert state["status"] == "pending" and state["retryable"]
    assert _checkpoint_state(case)["PARSING"][:2] == ("pending", 1)
    _assert_task(case, "pending", 1)
    _assert_not_ready(case)
    case.broker.retry_task.assert_called_once_with(
        task_id=case.task_id, tenant_id=1, task_type="formal_ready_document",
    )
    case.clock.now += timedelta(seconds=3)
    monkeypatch.setattr(case.runtime.executor.parser, "execute", execute)
    case.worker._execute_task(case.task_id)
    _assert_ready(case)
    _assert_task(case, "success", 1)
    assert _checkpoint_state(case)["PARSING"][1] == 2
    assert case.broker.retry_task.call_count == 1


def test_retryable_stage_attempt_exhaustion_remains_terminal(worker_runtime, monkeypatch):
    case = worker_runtime
    monkeypatch.setattr(case.runtime.executor.parser, "execute", Mock(side_effect=ConnectionError))
    monkeypatch.setattr(formal_handler_module.time, "sleep", Mock(
        side_effect=worker_module.TaskExecutionError("PROCESS_INTERRUPTED_DURING_BACKOFF"),
    ))
    for attempt, delay in ((1, 3), (2, 5), (3, 0)):
        case.worker._execute_task(case.task_id)
        _assert_not_ready(case)
        if attempt < 3:
            _assert_task(case, "pending", attempt)
            assert case.runtime.ledger.status(case.task_id, 1, 2)["retryable"]
        case.clock.now += timedelta(seconds=delay)
    assert _checkpoint_state(case)["PARSING"][:2] == ("failed", 3)
    _assert_task(case, "failed", 2)
    assert case.broker.retry_task.call_count == 2


@pytest.mark.parametrize("leased", [False, True])
def test_worker_interruption_before_terminal_state_recovers(worker_runtime, monkeypatch, leased):
    case = worker_runtime
    first_lease = None

    def interrupted(_kind, task_id):
        nonlocal first_lease
        if leased:
            first_lease = case.runtime.ledger.claim(task_id, case.clock.now)
        raise worker_module.TaskExecutionError("PROCESS_INTERRUPTED")

    monkeypatch.setattr(case.worker, "_run_handler_with_timeout", interrupted)
    case.worker._execute_task(case.task_id)
    _assert_task(case, "pending", 1)
    _assert_not_ready(case)
    assert _checkpoint_state(case)["PARSING"][0] == ("leased" if leased else "pending")
    if leased:
        assert case.runtime.ledger.claim(case.task_id, case.clock.now) is None
        case.clock.now += timedelta(seconds=301)
    monkeypatch.setattr(case.worker, "_run_handler_with_timeout", case.invoke)
    case.worker._execute_task(case.task_id)
    _assert_ready(case)
    _assert_task(case, "success", 1)
    assert _checkpoint_state(case)["PARSING"][1] == (2 if leased else 1)
    if first_lease:
        assert not case.runtime.ledger.finish(first_lease, now=case.clock.now, error_code="STALE_WRITE")


def test_queue_retry_budget_remains_bounded(worker_runtime, monkeypatch):
    case = worker_runtime
    assert worker_module.should_retry(2) and not worker_module.should_retry(3)
    handler = Mock(side_effect=worker_module.TaskExecutionError("PROCESS_INTERRUPTED"))
    monkeypatch.setattr(case.worker, "_run_handler_with_timeout", handler)
    for attempt in range(4):
        case.worker._execute_task(case.task_id)
        _assert_not_ready(case)
        _assert_task(case, "pending" if attempt < 3 else "failed", min(attempt + 1, 3))
    assert case.broker.retry_task.call_count == 3
    assert handler.call_count == 4
    assert _checkpoint_state(case)["PARSING"][:2] == ("pending", 0)


def test_completed_checkpoint_crash_resume_and_duplicate_delivery(worker_runtime, monkeypatch, record_property):
    case = worker_runtime
    writes = Mock(wraps=case.runtime.artifacts.put)
    parser = Mock(wraps=case.runtime.executor.parser.execute)
    promotion = Mock(wraps=case.runtime.ready.promote)
    monkeypatch.setattr(case.runtime.artifacts, "put", writes)
    monkeypatch.setattr(case.runtime.executor.parser, "execute", parser)
    monkeypatch.setattr(case.runtime.ready, "promote", promotion)

    def crash_after_checkpoint(_kind, task_id):
        assert case.runtime.executor.run_one(task_id) == "completed"
        raise worker_module.TaskExecutionError("CRASH_AFTER_COMMITTED_CHECKPOINT")

    monkeypatch.setattr(case.worker, "_run_handler_with_timeout", crash_after_checkpoint)
    case.worker._execute_task(case.task_id)
    original_parse = _checkpoint_state(case)["PARSING"]
    assert original_parse[0] == "complete"
    _assert_not_ready(case)
    _assert_task(case, "pending", 1)
    monkeypatch.setattr(case.worker, "_run_handler_with_timeout", case.invoke)
    case.worker._execute_task(case.task_id)
    _assert_ready(case)
    assert _checkpoint_state(case)["PARSING"] == original_parse
    assert parser.call_count == 1 and promotion.call_count == 1
    receipt = case.runtime.ledger.ready_index(case.task_id, 1, 2)
    graph = _checkpoint_state(case)
    write_count = writes.call_count
    for _ in range(2):
        case.worker._execute_task(case.task_id)
        process_formal_ready_task(case.task_id)
    assert writes.call_count == write_count
    assert parser.call_count == 1 and promotion.call_count == 1
    assert _checkpoint_state(case) == graph
    assert case.runtime.ledger.ready_index(case.task_id, 1, 2) == receipt
    with case.factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 5
    record_property("PARSING_EXECUTIONS", parser.call_count)
    record_property("READY_PROMOTIONS", promotion.call_count)
    record_property("DUPLICATE_ARTIFACT_WRITES", writes.call_count - write_count)


def test_legacy_retry_never_reads_formal_authority(worker_runtime, monkeypatch):
    case = worker_runtime
    with case.factory() as session:
        legacy = TaskRepository(session).create_task(TaskType.PROCESS_DOCUMENT, {}, 1, 2)
        legacy_id = legacy.public_id
    monkeypatch.setattr(FormalIngestionLedger, "status", Mock(side_effect=AssertionError("LEGACY_LEDGER_ACCESS")))

    def legacy_failure(kind, _task_id):
        assert kind == WorkerTaskType.PROCESS_DOCUMENT
        raise ValueError("LEGACY_FAILURE")

    monkeypatch.setattr(case.worker, "_run_handler_with_timeout", legacy_failure)
    for attempt in range(4):
        case.worker._execute_task(legacy_id)
        with case.factory() as session:
            legacy = session.scalar(select(Task).where(Task.public_id == legacy_id))
            assert legacy.status == ("pending" if attempt < 3 else "failed")
            assert legacy.retry_count == min(attempt + 1, 3)
    assert case.broker.retry_task.call_count == 3
    case.broker.retry_task.assert_called_with(
        task_id=legacy_id, tenant_id=1, task_type="process_document",
    )


def test_formal_and_legacy_handler_references_are_distinct():
    assert worker_module._HANDLERS[WorkerTaskType.PROCESS_DOCUMENT] == (
        "tasks.knowledge_tasks:process_document_task"
    )
    assert worker_module._HANDLERS[WorkerTaskType.FORMAL_READY_DOCUMENT] == (
        "tasks.formal_ready_tasks:process_formal_ready_task"
    )
