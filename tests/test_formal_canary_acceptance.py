"""Harness fixes are tested separately from dispatch product repair."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task
from scripts.formal_canary_acceptance import verify_formal_canary, verify_hybrid_retrieval
from tests.formal_contract_data import HASH, NOW
from tests.formal_ingestion_test_harness import formal  # noqa: F401


def completed(formal_data, dispatch_state):
    engine, repo, _ = formal_data
    result = repo.finalize("upload-1", 1, 2, NOW)
    with Session(engine) as session, session.begin():
        task = session.scalar(select(Task))
        task.status, task.dispatch_state = "success", dispatch_state
        session.get(Document, int(result.document_id)).status = "ready"
        for row in session.scalars(select(TaskStageCheckpoint)):
            row.status, row.artifact_id, row.artifact_sha256, row.completed_at = "complete", HASH, HASH, NOW
    return engine, result


@pytest.mark.parametrize("state", ["none", "delivered", "failed"])
def test_harness_accepts_owner_and_transport_independent_terminal_contract(formal, state):  # noqa: F811
    engine, result = completed(formal, state)
    with Session(engine) as session:
        receipt = verify_formal_canary(session, task_id=result.ingestion_job_id,
                                      tenant_id=1, user_id=2, source_sha256=HASH, now=NOW)
    assert receipt["status"] == "PASS"
    assert not receipt["fixed_redis_delivery_count_required"]


def test_harness_still_rejects_stale_active_obligation(formal):  # noqa: F811
    engine, result = completed(formal, "pending")
    with Session(engine) as session, pytest.raises(ValueError, match="CANARY_DISPATCH_NOT_CLOSED"):
        verify_formal_canary(session, task_id=result.ingestion_job_id,
                             tenant_id=1, user_id=2, source_sha256=HASH, now=NOW)


@pytest.mark.parametrize("tenant,user", [(1, 999), (999, 2)])
def test_harness_foreign_ownership_remains_rejected(formal, tenant, user):  # noqa: F811
    engine, result = completed(formal, "none")
    with Session(engine) as session, pytest.raises(PermissionError):
        verify_formal_canary(session, task_id=result.ingestion_job_id,
                             tenant_id=tenant, user_id=user, source_sha256=HASH, now=NOW)


def hybrid_evidence():
    return SimpleNamespace(document_id="1", payload={
        "retriever": "HYBRID", "page": 57, "company": "",
        "provenance": {"tenant_id": 1, "content_sha256": HASH,
                       "document_version": HASH, "retrieval_component": "hybrid_bm25_vector_rrf"},
    })


def test_hybrid_harness_does_not_claim_narrative_acceptance():
    receipt = verify_hybrid_retrieval([hybrid_evidence()], tenant_id=1, document_id=1,
                                    source_sha256=HASH, page_count=71)
    assert receipt["status"] == "PASS"
    assert receipt["scope"] == "RETRIEVAL_SOURCE_BINDING_ONLY"
    assert receipt["narrative_answer_accepted"] is False


@pytest.mark.parametrize("field,value", [
    ("tenant_id", 999), ("content_sha256", "b" * 64),
    ("document_version", "b" * 64), ("retrieval_component", "vector_only"),
])
def test_hybrid_harness_rejects_invalid_provenance(field, value):
    evidence = hybrid_evidence()
    evidence.payload["provenance"][field] = value
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        verify_hybrid_retrieval([evidence], tenant_id=1, document_id=1,
                               source_sha256=HASH, page_count=71)


@pytest.mark.parametrize("page", [0, 72, True])
def test_hybrid_harness_rejects_invalid_source_page(page):
    evidence = hybrid_evidence()
    evidence.payload["page"] = page
    with pytest.raises(ValueError, match="SOURCE_BINDING_INVALID"):
        verify_hybrid_retrieval([evidence], tenant_id=1, document_id=1,
                               source_sha256=HASH, page_count=71)
