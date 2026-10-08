"""Formal storage tests: no experimental ORM or repository composition."""
# ruff: noqa: F811 -- imported pytest fixture is resolved by name.

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from core.upload_session_contracts import UploadState
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task
from storage.upload_session_repository import UploadSessionRepository
from tasks.task_dispatcher import TaskDispatcher
from tests.formal_contract_data import NOW
from tests.formal_ingestion_test_harness import formal  # noqa: F401


def test_finalize_binding_and_restart(formal):
    engine, repo, factory = formal
    first = repo.finalize("upload-1", 1, 2, NOW)
    assert UploadSessionRepository(factory).finalize("upload-1", 1, 2, NOW + timedelta(hours=2)) == first
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 5
        task = session.scalar(select(Task))
        assert (task.status, task.dispatch_state) == ("pending", "pending")
    with pytest.raises(PermissionError):
        repo.finalize("upload-1", 1, 999, NOW)


def test_checkpoint_insert_failure_rolls_back_finalize(formal):
    engine, repo, _ = formal

    def fail(*args):
        raise RuntimeError("injected checkpoint persistence failure")

    event.listen(TaskStageCheckpoint, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            repo.finalize("upload-1", 1, 2, NOW)
    finally:
        event.remove(TaskStageCheckpoint, "before_insert", fail)
    assert repo.get("upload-1", 1, 2).state == UploadState.VERIFIED
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Task)) == 0
        assert session.scalar(select(func.count()).select_from(Document)) == 0
    repo.finalize("upload-1", 1, 2, NOW)


def test_dispatch_restart_and_stale_token(formal):
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    dispatcher = TaskDispatcher(factory, lease_seconds=1)
    old = dispatcher.claim(NOW)
    assert old.task_id == result.ingestion_job_id
    assert dispatcher.claim(NOW) is None
    recovered = TaskDispatcher(factory, lease_seconds=1).claim(NOW + timedelta(seconds=2))
    assert recovered.task_id == old.task_id and recovered.token != old.token
    assert not dispatcher.finish(old, delivered=True, now=NOW + timedelta(seconds=2))
    assert dispatcher.finish(recovered, delivered=True, now=NOW + timedelta(seconds=2))
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert (task.status, task.dispatch_state) == ("pending", "delivered")


def test_transport_failure_keeps_durable_same_task(formal):
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)

    def unavailable(*args):
        raise ConnectionError("transport unavailable")

    assert TaskDispatcher(factory).dispatch_one(unavailable, NOW) == "not_delivered"
    delivered = []
    assert (
        TaskDispatcher(factory).dispatch_one(
            lambda task_id, *_: delivered.append(task_id) or True, NOW + timedelta(seconds=3)
        )
        == "delivered"
    )
    assert delivered == [result.ingestion_job_id]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Task)) == 1


def test_two_dispatchers_only_one_active_lease(formal):
    _, repo, factory = formal
    repo.finalize("upload-1", 1, 2, NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: TaskDispatcher(factory).claim(NOW), range(2)))
    assert sum(lease is not None for lease in leases) == 1


def test_publish_success_ack_failure_replays_same_identity(formal):
    engine, repo, factory = formal
    result = repo.finalize("upload-1", 1, 2, NOW)
    dispatcher = TaskDispatcher(factory, lease_seconds=1)
    first = dispatcher.claim(NOW)
    published = [first.task_id]  # Transport accepted; fail before the acknowledgement commits.

    def fail_ack(mapper, connection, target):
        if target.dispatch_state == "delivered":
            raise RuntimeError("injected acknowledgement failure")

    event.listen(Task, "before_update", fail_ack)
    try:
        with pytest.raises(RuntimeError, match="acknowledgement"):
            dispatcher.finish(first, delivered=True, now=NOW)
    finally:
        event.remove(Task, "before_update", fail_ack)
    recovered = TaskDispatcher(factory, lease_seconds=1)
    assert (
        recovered.dispatch_one(lambda task_id, *_: published.append(task_id) or True, NOW + timedelta(seconds=2))
        == "delivered"
    )
    assert published == [result.ingestion_job_id, result.ingestion_job_id]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(func.count()).select_from(Document)) == 1


def test_historical_task_has_no_dispatch_obligation(formal):
    engine, _, factory = formal
    with Session(engine) as session, session.begin():
        session.add(
            Task(public_id="historical-task", tenant_id=1, user_id=2, task_type="process_document", status="pending")
        )
    assert TaskDispatcher(factory).claim(NOW) is None
    with Session(engine) as session:
        task = session.scalar(select(Task))
        assert task.dispatch_state == "none" and task.status == "pending"
