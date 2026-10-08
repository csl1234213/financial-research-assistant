"""Defense in depth: storage filters are not proof of returned source identity."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.answer_synthesis_contracts import AnswerType, EvidenceSnapshot
from retrieval.adaptive_contract import Evidence, RetrievalMode
from retrieval.ingestion_ready_retriever import IngestionReadyRetriever
from services.ready_narrative_synthesis_source import ReadyNarrativeSynthesisSource


@pytest.mark.parametrize("question,accepted", [
    ("说明2025年报中的主要业务", True),
    ("说明2024年报中的主要业务", False),
    ("说明2025年的业务情况", False),
    ("说明2025年报中2025年的业务情况", False),
])
def test_report_identity_does_not_promote_observation_period(question, accepted):
    digest = "a" * 64
    manifest = {"document_id": 42, "source_sha256": digest}
    ledger = Mock()
    ledger.ready_index.return_value = manifest
    evidence = (EvidenceSnapshot.from_evidence(Evidence(
        "business", "NARRATIVE_TEXT", "42", "Source disclosure", RetrievalMode.HYBRID,
        "ready_indexed_text", "report.pdf",
        provenance={"tenant_id": 1, "content_sha256": digest, "report_period": "FY2025"}),
        tenant_id=1),)
    retriever = SimpleNamespace(ledger=ledger, search_evidence=lambda *args, **kwargs: evidence)
    resolver = ReadyNarrativeSynthesisSource(retriever, query_embedder=lambda _: [1.0])
    parameters = dict(question=question, locale="zh-CN", tenant_id=1, user_id=2,
                      ingestion_job_id="job", manifest=manifest)
    if accepted:
        assert resolver(**parameters).evidence == evidence
    else:
        with pytest.raises(ValueError, match="NARRATIVE_QUERY_PERIOD_NOT_BOUND"):
            resolver(**parameters)


@pytest.mark.parametrize("mutation", ["tenant", "boolean_tenant", "document", "version", "distance", "shape", "duplicate"])
def test_returned_records_are_independently_bound(mutation):
    manifest = {"embedding_identity": "test", "collection": "isolated", "verified_chunk_count": 2,
                "document_id": 42, "source_sha256": "a" * 64}
    metadata = {"embedding_identity": "test", "tenant_id": 1, "document_id": "42", "source_sha256": "a" * 64}
    result = {"ids": [["c1"]], "documents": [["actual source"]], "metadatas": [[metadata]], "distances": [[0.2]]}
    if mutation == "tenant":
        metadata["tenant_id"] = 2
    elif mutation == "boolean_tenant":
        metadata["tenant_id"] = True
    elif mutation == "document":
        metadata["document_id"] = "43"
    elif mutation == "version":
        metadata["source_sha256"] = "b" * 64
    elif mutation == "distance":
        result["distances"] = [[float("nan")]]
    elif mutation == "shape":
        result["documents"] = [[]]
    else:
        for columns in result.values():
            columns[0].append(columns[0][0])
    ledger = Mock()
    ledger.ready_index.return_value = manifest
    collection = SimpleNamespace(count=lambda: 2, query=lambda **_: result)
    vectors = SimpleNamespace(client=SimpleNamespace(get_collection=lambda _: collection))
    retriever = IngestionReadyRetriever(ledger, vectors, embedding_identity="test")
    with pytest.raises(ValueError, match="QUERY_INDEX_"):
        retriever.search("job", tenant_id=1, user_id=2, query_embedding=[1.0])


@pytest.mark.parametrize("section,accepted", [("Risk Factors", True), ("Management Discussion", False),
                                             (" ", False), (None, False)])
def test_cross_section_source_requires_bound_section_metadata(section, accepted):
    digest = "a" * 64
    manifest = {"document_id": 42, "source_sha256": digest}
    ledger = Mock()
    ledger.ready_index.return_value = manifest
    evidence = tuple(EvidenceSnapshot.from_evidence(Evidence(
        f"e{index}", "NARRATIVE_TEXT", "42", "Source disclosure", RetrievalMode.HYBRID,
        "ready_indexed_text", "report.pdf", section=label,
        provenance={"tenant_id": 1, "content_sha256": digest}), tenant_id=1)
        for index, label in enumerate(("Management Discussion", section)))
    retriever = SimpleNamespace(ledger=ledger, search_evidence=lambda *args, **kwargs: evidence)
    resolver = ReadyNarrativeSynthesisSource(retriever, query_embedder=lambda _: [1.0])
    parameters = dict(question="跨章节说明经营与风险", locale="zh-CN", tenant_id=1, user_id=2,
                      ingestion_job_id="job", manifest=manifest)
    if accepted:
        result = resolver(**parameters)
        assert result.answer_type == AnswerType.CROSS_SECTION
        assert result.coverage["complete"] is None
        assert result.evidence == evidence
    else:
        with pytest.raises(ValueError, match="CROSS_SECTION_EVIDENCE_REQUIRED"):
            resolver(**parameters)
