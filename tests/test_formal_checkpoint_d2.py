"""Real SQLite/PostgreSQL checkpoint fencing and restart checks."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.ingestion_persistence import TaskStageCheckpoint
from storage.ingestion_artifacts import IngestionArtifactStore
from tasks.formal_ingestion_ledger import FormalIngestionLedger
from tests.formal_contract_data import NOW
from tests.formal_ingestion_test_harness import formal  # noqa: F401, F811


def test_checkpoint_expiry_stale_writes_and_restart(formal, tmp_path):  # noqa: F811
    engine, repo, factory = formal
    task_id = repo.finalize("upload-1", 1, 2, NOW).ingestion_job_id
    store = IngestionArtifactStore(tmp_path / "artifacts")
    ledger = FormalIngestionLedger(factory, artifact_store=store, lease_seconds=1)
    first = ledger.claim(task_id, NOW)
    assert ledger.claim(task_id, NOW) is None
    restarted = FormalIngestionLedger(factory, artifact_store=store, lease_seconds=1)
    recovered = restarted.claim(task_id, NOW + timedelta(seconds=2))
    assert recovered.stage == first.stage and recovered.token != first.token
    digest = store.put(first.tenant_id, first.source_sha256, b"source-backed checkpoint")
    assert not ledger.finish(first, now=NOW + timedelta(seconds=2), artifact_id=digest, artifact_sha256=digest)
    assert not ledger.finish(first, now=NOW + timedelta(seconds=2), error_code="OLD_WORKER_FAILURE")
    assert restarted.finish(recovered, now=NOW + timedelta(seconds=2), artifact_id=digest, artifact_sha256=digest)
    assert not restarted.finish(recovered, now=NOW + timedelta(seconds=2), artifact_id=digest, artifact_sha256=digest)
    state = restarted.status(task_id, 1, 2)
    assert state["completed_stages"] == ["PARSING"] and state["status"] != "ready"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 5
        row = session.scalar(select(TaskStageCheckpoint).where(TaskStageCheckpoint.stage == "PARSING"))
        assert row.attempt_count == 2 and row.artifact_sha256 == digest


def test_retry_updates_same_checkpoint(formal, tmp_path):  # noqa: F811
    engine, repo, factory = formal
    task_id = repo.finalize("upload-1", 1, 2, NOW).ingestion_job_id
    ledger = FormalIngestionLedger(factory, artifact_store=IngestionArtifactStore(tmp_path / "artifacts"))
    lease = ledger.claim(task_id, NOW)
    assert ledger.finish(lease, now=NOW, error_code="STAGE_TRANSIENT_FAILURE", retryable=True)
    assert ledger.claim(task_id, NOW + timedelta(seconds=1)) is None
    recovered = ledger.claim(task_id, NOW + timedelta(seconds=3))
    assert recovered.stage == lease.stage and recovered.token != lease.token
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 5
