"""Formal read-port boundary tests; real persisted E2E is a separate gate."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tasks.formal_ingestion_ledger import FormalIngestionLedger


@pytest.fixture
def read_port(monkeypatch):
    manifest = {"document_id": 7, "source_sha256": "a" * 64}
    task = SimpleNamespace(tenant_id=1, user_id=2)
    document = SimpleNamespace(id=7, content_sha256="a" * 64)
    graph = {stage: SimpleNamespace(status="complete", artifact_sha256=digest)
        for stage, digest in [("PARSING", "b" * 64), ("QUALITY_CHECK", "c" * 64),
                              ("BUILDING_FACTS", "d" * 64)]}
    payload = {"schema": "financial-ingestion-facts.v1", "tenant_id": 1, "document_id": 7,
        "source_sha256": "a" * 64, "parse_artifact_sha256": "b" * 64,
        "quality_artifact_sha256": "c" * 64, "facts": []}
    store = Mock()
    store.read.side_effect = lambda *args: json.dumps(payload).encode()
    ledger = FormalIngestionLedger(lambda: nullcontext(Mock()), artifact_store=store)
    monkeypatch.setattr(ledger, "ready_index", Mock(return_value=manifest))
    monkeypatch.setattr(ledger, "_load", lambda *args: (task, document, graph))
    return ledger, task, document, graph, payload


def test_exact_complete_status_is_accepted(read_port):
    ledger, *_, payload = read_port
    assert ledger.ready_facts("job", 1, 2) == payload
    ledger.artifact_store.read.assert_called_once_with(1, "a" * 64, "d" * 64)


@pytest.mark.parametrize("status", ["completed", "pending", "leased", "failed"])
def test_noncontract_checkpoint_status_rejected(read_port, status):
    ledger, _, _, graph, _ = read_port
    graph["BUILDING_FACTS"].status = status
    with pytest.raises(ValueError, match="READY_FACT_CHECKPOINT_REQUIRED"):
        ledger.ready_facts("job", 1, 2)


@pytest.mark.parametrize("stage", ["PARSING", "QUALITY_CHECK", "BUILDING_FACTS"])
def test_missing_prerequisite_artifact_rejected(read_port, stage):
    ledger, _, _, graph, _ = read_port
    graph[stage].artifact_sha256 = None
    with pytest.raises(ValueError, match="READY_FACT_CHECKPOINT_REQUIRED"):
        ledger.ready_facts("job", 1, 2)


@pytest.mark.parametrize("tenant,user", [(9, 2), (1, 9)])
def test_wrong_owner_rejected(read_port, tenant, user):
    ledger = read_port[0]
    with pytest.raises(PermissionError, match="INGESTION_NOT_FOUND"):
        ledger.ready_facts("job", tenant, user)


@pytest.mark.parametrize("field,value", [("id", 8), ("content_sha256", "e" * 64)])
def test_document_or_source_version_mismatch_rejected(read_port, field, value):
    ledger, _, document, *_ = read_port
    setattr(document, field, value)
    with pytest.raises(ValueError, match="FACT_RECEIPT_SOURCE_CHANGED"):
        ledger.ready_facts("job", 1, 2)


@pytest.mark.parametrize("field,value", [("document_id", 9), ("source_sha256", "e" * 64),
    ("parse_artifact_sha256", "e" * 64), ("quality_artifact_sha256", "e" * 64),
    ("tenant_id", 9), ("schema", "untrusted.v1"), ("facts", {})])
def test_tampered_artifact_binding_rejected(read_port, field, value):
    ledger, *_, payload = read_port
    payload[field] = value
    with pytest.raises(ValueError, match="READY_FACT_ARTIFACT_BINDING_INVALID"):
        ledger.ready_facts("job", 1, 2)


def test_nonready_document_rejected_before_io(read_port):
    ledger = read_port[0]
    ledger.ready_index.side_effect = ValueError("DOCUMENT_NOT_READY")
    with pytest.raises(ValueError, match="DOCUMENT_NOT_READY"):
        ledger.ready_facts("job", 1, 2)
    ledger.artifact_store.read.assert_not_called()


def test_post_io_receipt_change_rejected(read_port):
    ledger, _, _, graph, payload = read_port

    def read(*args):
        graph["BUILDING_FACTS"].artifact_sha256 = "e" * 64
        return json.dumps(payload).encode()

    ledger.artifact_store.read.side_effect = read
    with pytest.raises(ValueError, match="READY_FACT_RECEIPT_GRAPH_CHANGED"):
        ledger.ready_facts("job", 1, 2)
