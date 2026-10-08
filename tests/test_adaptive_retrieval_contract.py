from types import SimpleNamespace

import pytest

from agent.reasoning_models import Evidence as AgentEvidence
from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from retrieval.adaptive_adapters import FinancialFactEvidenceAdapter, HybridEvidenceAdapter, evidence_from_source
from retrieval.adaptive_contract import RetrievalMode, RetrievalRequest, RetrievalStatus
from storage.vector_models import SearchResult


def request(**kwargs):
    return RetrievalRequest(ScopedRequest(query="总资产", tenant_id=7, document_ids=("doc",), **kwargs))


def metadata():
    return {
        "tenant_id": 7,
        "document_id": "doc",
        "fact_id": "fact",
        "source": "report.pdf",
        "page": 12,
        "bbox": [1, 2, 3, 4],
        "source_block_ids": ["block"],
        "value": "123.00",
        "canonical_metric": "total_assets",
        "fiscal_year": "2025",
        "scope": "CONSOLIDATED",
        "statement_type": "BALANCE_SHEET",
        "currency": "CNY",
        "unit": "CNY_YUAN",
        "source_locator": {"page": 12},
        "custom_provenance": {"nested": [1]},
    }


def test_fact_adapter_preserves_identity_financial_fields_and_nested_provenance():
    data = metadata()
    original = AgentEvidence("source row", "report.pdf", "Moutai", 1.0, data)
    adapter = FinancialFactEvidenceAdapter(
        lambda req: SimpleNamespace(status="FOUND", evidence=(original,), trace={"scope": "CONSOLIDATED"})
    )
    result = adapter.retrieve(request())
    ev = result.evidence[0]
    assert ev.evidence_id == "fact"
    assert (ev.metric, ev.structured_value, ev.period["fiscal_year"], ev.scope) == (
        "total_assets",
        "123.00",
        "2025",
        "CONSOLIDATED",
    )
    assert ev.source_block_ids == ("block",)
    assert ev.provenance["currency"] == "CNY"
    ev.to_agent().metadata["custom_provenance"]["nested"].append(2)
    assert data["custom_provenance"]["nested"] == [1]


@pytest.mark.parametrize("tenant", [None, True, 8, "7", 7.0])
def test_rejects_missing_or_foreign_tenant(tenant):
    with pytest.raises(ValueError, match="tenant"):
        evidence_from_source(
            request=request(),
            metadata={**metadata(), "tenant_id": tenant},
            text="text",
            source="report.pdf",
            document_id="doc",
            evidence_id="id",
            route=RetrievalMode.HYBRID,
            confidence=0.8,
        )


def test_rejects_document_outside_scope():
    with pytest.raises(ValueError, match="document"):
        evidence_from_source(
            request=request(),
            metadata=metadata(),
            text="text",
            source="report.pdf",
            document_id="other",
            evidence_id="id",
            route=RetrievalMode.HYBRID,
            confidence=1,
        )


def test_hybrid_adapter_does_not_change_query_ranking_or_metadata():
    row = SearchResult("doc", "chunk", 0.8, "actual source text", metadata())

    class Retriever:
        def retrieve(self, context, store):
            assert context.question == "总资产" and context.tenant_id == 7 and context.top_k == 5
            return [row]

        def _evidence_confidence(self, result):
            return 0.8

    result = HybridEvidenceAdapter(Retriever(), object()).retrieve(request())
    assert result.status == RetrievalStatus.FOUND
    assert result.evidence[0].bbox == [1, 2, 3, 4]
    assert result.evidence[0].text == row.content
    assert result.evidence[0].provenance["custom_provenance"] == row.metadata["custom_provenance"]


@pytest.mark.parametrize("status", ["NOT_FOUND", "AMBIGUOUS", "CONFLICT", "UNSUPPORTED_METRIC"])
def test_fact_status_is_not_promoted_to_found(status):
    result = FinancialFactEvidenceAdapter(lambda req: SimpleNamespace(status=status, evidence=(), trace={})).retrieve(
        request()
    )
    assert result.status != RetrievalStatus.FOUND


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("metric", "total_liabilities", "metric"),
        ("fiscal_year", "2024", "fiscal year"),
        ("scope", "PARENT_COMPANY", "financial scope"),
        ("period", "DURATION", "period type"),
    ],
)
def test_fact_adapter_refuses_wrong_financial_dimension(field, value, reason):
    from dataclasses import replace

    scoped_request = replace(request(), **{field: value})
    with pytest.raises(ValueError, match=reason):
        evidence_from_source(
            request=scoped_request,
            metadata={**metadata(), "period_type": "INSTANT"},
            text="source row",
            source="report.pdf",
            document_id="doc",
            evidence_id="fact",
            route=RetrievalMode.FACT,
            confidence=1,
        )
