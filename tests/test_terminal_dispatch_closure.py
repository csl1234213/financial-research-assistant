"""Terminal dispatch regressions against real repositories, never the Q2 canary."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from models.document import Document
from models.task import Task, TaskStatus
from tasks.formal_ingestion_ledger import FormalIngestionLedger
from tasks.repository import TaskRepository
from tasks.task_dispatcher import TaskDispatcher
from tasks.worker import TaskWorker
from tests.formal_contract_data import NOW
from tests.formal_ingestion_test_harness import formal  # noqa: F401


@pytest.mark.parametrize("status", ["success", "failed"])
def test_stale_terminal_pending_obligation_is_not_claimed(formal, status):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    with Session(engine) as session, session.begin():
        task = session.scalar(select(Task).where(Task.public_id == result.ingestion_job_id))
        task.status = status
    assert TaskDispatcher(factory).claim(NOW) is None
    with Session(engine) as session:
        task = session.scalar(select(Task).where(Task.public_id == result.ingestion_job_id))
        assert task.dispatch_state == "pending" and task.dispatch_attempt_count == 0


@pytest.mark.parametrize("status", [TaskStatus.SUCCESS, TaskStatus.FAILED])
def test_repository_terminal_commit_closes_obligation(formal, status):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    with Session(engine) as session:
        TaskRepository(session).update_task(result.ingestion_job_id, status=status)
    with Session(engine) as session:
        task = session.scalar(select(Task).where(Task.public_id == result.ingestion_job_id))
        assert task.status == status.value
        assert task.dispatch_state == "none"
        assert task.dispatch_next_attempt_at is None
    assert TaskDispatcher(factory).claim(NOW) is None


@pytest.mark.parametrize("document_status", ["ready", "failed", "quarantined"])
def test_terminal_document_excludes_inconsistent_nonterminal_task(formal, document_status):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    with Session(engine) as session, session.begin():
        session.get(Document, int(result.document_id)).status = document_status
    assert TaskDispatcher(factory).claim(NOW) is None


def test_terminal_commit_between_claim_and_publish_prevents_transport(formal, monkeypatch):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    dispatcher = TaskDispatcher(factory)
    original_claim = dispatcher.claim

    def claimed_then_completed(now):
        lease = original_claim(now)
        with Session(engine) as session:
            TaskRepository(session).update_task(result.ingestion_job_id, status=TaskStatus.SUCCESS)
        return lease

    monkeypatch.setattr(dispatcher, "claim", claimed_then_completed)
    published = []
    assert dispatcher.dispatch_one(lambda *args: published.append(args) or True, NOW) == "lease_lost"
    assert published == []


def test_nonterminal_retry_and_expired_lease_remain_dispatchable(formal):  # noqa: F811
    _, repo, factory = formal
    repo.finalize("upload-1", 1, 2, NOW)
    dispatcher = TaskDispatcher(factory, lease_seconds=1)
    first = dispatcher.claim(NOW)
    assert first is not None and dispatcher.claim(NOW) is None
    recovered = TaskDispatcher(factory, lease_seconds=1).claim(NOW + timedelta(seconds=2))
    assert recovered is not None and recovered.token != first.token
    assert dispatcher.finish(recovered, delivered=False, now=NOW + timedelta(seconds=2))
    assert dispatcher.claim(NOW + timedelta(seconds=3)) is None
    assert dispatcher.claim(NOW + timedelta(seconds=7)) is not None


@pytest.mark.parametrize("initial", ["pending", "leased", "none", "delivered", "failed"])
@pytest.mark.parametrize("autoflush", [True, False])
def test_actual_worker_execution_retry_restores_only_withdrawn_obligation(formal, monkeypatch, initial, autoflush):  # noqa: F811
    import tasks.worker as worker_module

    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    with Session(engine) as session, session.begin():
        task = session.scalar(select(Task))
        task.dispatch_state = initial
        task.dispatch_attempt_count = 1
        if initial == "leased":
            task.dispatch_lease_token = "f" * 32
            task.dispatch_lease_expires_at = NOW + timedelta(seconds=30)
    broker = MagicMock()
    worker = TaskWorker(worker_id="p1-execution-retry-test")
    db = Session(engine, autoflush=autoflush)
    monkeypatch.setattr(worker_module, "get_task_repository", lambda: TaskRepository(db))
    monkeypatch.setattr(worker_module, "get_broker", lambda: broker)

    def transient_failure(*args):
        raise ConnectionError("isolated transient handler failure")

    monkeypatch.setattr(worker, "_run_handler_with_timeout", transient_failure)
    worker._execute_task(result.ingestion_job_id)
    broker.retry_task.assert_called_once()
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert task.status == "pending" and task.retry_count == 1
        expected = "pending" if initial in {"pending", "leased"} else initial
        assert task.dispatch_state == expected and task.dispatch_attempt_count == 1
    assert (TaskDispatcher(factory).claim(NOW) is not None) == (initial in {"pending", "leased"})


@pytest.mark.parametrize("quality_failure", [False, True])
def test_formal_permanent_failure_or_quarantine_closes_atomically(formal, quality_failure):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    ledger = FormalIngestionLedger(factory, artifact_store=None, max_attempts=1)
    lease = ledger.claim(result.ingestion_job_id, NOW)
    if quality_failure:
        # Real checkpoint authority; advance parsing with a stored artifact.
        class Artifacts:
            def read(self, *args):
                return b"{}"

        ledger.artifact_store = Artifacts()
        assert ledger.finish(lease, now=NOW, artifact_id="a" * 64, artifact_sha256="a" * 64)
        lease = ledger.claim(result.ingestion_job_id, NOW)
        assert lease.stage == "QUALITY_CHECK"
        assert ledger.finish(lease, now=NOW, quality_status="FAIL")
    else:
        assert ledger.finish(lease, now=NOW, error_code="PERMANENT_TEST_FAILURE", retryable=False)
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert task.status == "failed" and task.dispatch_state == "none"
        assert session.get(Document, int(result.document_id)).status == ("quarantined" if quality_failure else "failed")
    assert TaskDispatcher(factory).claim(NOW) is None


def test_stage_retry_preserves_active_obligation(formal):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    ledger = FormalIngestionLedger(factory, artifact_store=None)
    lease = ledger.claim(result.ingestion_job_id, NOW)
    assert ledger.finish(lease, now=NOW, error_code="TRANSIENT_STAGE_FAILURE", retryable=True)
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert task.status == "pending" and task.dispatch_state == "pending"
    assert TaskDispatcher(factory).claim(NOW) is not None


def test_exhausted_stage_claim_closes_obligation(formal):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    ledger = FormalIngestionLedger(factory, artifact_store=None, max_attempts=1, lease_seconds=1)
    assert ledger.claim(result.ingestion_job_id, NOW) is not None
    assert ledger.claim(result.ingestion_job_id, NOW + timedelta(seconds=2)) is None
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert task.status == "failed" and task.dispatch_state == "none"


def test_crash_before_terminal_commit_rolls_back_both_and_retry_commits_both(formal):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    writes = []

    def interrupted(mapper, connection, task):
        writes.append((task.status, task.dispatch_state))
        raise RuntimeError("crash before final task commit")

    event.listen(Task, "before_update", interrupted)
    try:
        with Session(engine) as session, pytest.raises(RuntimeError, match="crash"):
            TaskRepository(session).update_task(result.ingestion_job_id, status=TaskStatus.SUCCESS)
    finally:
        event.remove(Task, "before_update", interrupted)
    assert writes == [("success", "none")]
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert (task.status, task.dispatch_state) == ("pending", "pending")
        TaskRepository(session).update_task(result.ingestion_job_id, status=TaskStatus.SUCCESS)
    # New dispatcher/repository instances simulate restart after atomic commit.
    assert TaskDispatcher(factory).claim(NOW + timedelta(hours=1)) is None
    with Session(engine) as session:
        task = TaskRepository(session).update_task(result.ingestion_job_id, status=TaskStatus.SUCCESS)
        assert (task.status, task.dispatch_state) == ("success", "none")


def test_stale_orm_session_cannot_overwrite_committed_success(formal):  # noqa: F811
    engine, repo, _ = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    with Session(engine, expire_on_commit=False) as stale:
        old = TaskRepository(stale).get_task(result.ingestion_job_id)
        stale.commit()
        assert old.status == "pending"
        with Session(engine) as fresh:
            TaskRepository(fresh).update_task(result.ingestion_job_id, status=TaskStatus.SUCCESS)
        observed = TaskRepository(stale).update_task(result.ingestion_job_id, status=TaskStatus.FAILED)
        assert observed.status == "success" and observed.dispatch_state == "none"


def test_late_dispatch_finish_cannot_reopen_closed_lease(formal):  # noqa: F811
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    dispatcher = TaskDispatcher(factory)
    lease = dispatcher.claim(NOW)
    with Session(engine) as session:
        TaskRepository(session).update_task(result.ingestion_job_id, status=TaskStatus.SUCCESS)
    assert not dispatcher.finish(lease, delivered=False, now=NOW)
    assert TaskDispatcher(factory).claim(NOW + timedelta(hours=1)) is None


@pytest.mark.FORMAL_ACCEPTANCE
def test_postgres_publication_lock_serializes_terminal_commit(formal):  # noqa: F811
    engine, repo, factory = formal
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock acceptance only")
    result = repo.finalize("upload-1", 1, 2, NOW)
    entered, release, attempted, committed = Event(), Event(), Event(), Event()

    def publisher(*args):
        entered.set()
        assert release.wait(10)
        assert not committed.is_set()
        return True

    def terminal():
        attempted.set()
        with Session(engine) as session:
            TaskRepository(session).update_task(result.ingestion_job_id, status=TaskStatus.SUCCESS)
        committed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        publishing = pool.submit(TaskDispatcher(factory).dispatch_one, publisher, NOW)
        assert entered.wait(10)
        completing = pool.submit(terminal)
        assert attempted.wait(10)
        try:
            assert not committed.wait(0.3), "terminal commit escaped publication Task lock"
        finally:
            release.set()
        assert publishing.result(timeout=10) == "delivered"
        completing.result(timeout=10)
    assert TaskDispatcher(factory).claim(NOW + timedelta(hours=1)) is None
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert (task.status, task.dispatch_state) == ("success", "delivered")
