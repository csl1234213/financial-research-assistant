"""Real P1.3 rows -> SQLite fact repository -> P2.1 unified evidence."""

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from core.structured_financial_query import lookup_persisted_financial_fact
from retrieval.adaptive_adapters import FinancialFactEvidenceAdapter
from retrieval.adaptive_contract import RetrievalMode, RetrievalRequest, RetrievalStatus
from tests.test_structured_financial_query import moutai_rows, persisted_moutai  # noqa: F401


@pytest.mark.parametrize(
    "metric,period",
    [
        ("total_assets", "INSTANT"),
        ("cash_and_bank_balances", "INSTANT"),
        ("net_income", "DURATION"),
        ("attributable_net_income", "DURATION"),
        ("operating_cash_flow", "DURATION"),
    ],
)
def test_real_persisted_fact_adapter_preserves_financial_identity(persisted_moutai, metric, period):  # noqa: F811
    data = persisted_moutai
    request = RetrievalRequest(
        ScopedRequest(
            query="贵州茅台2025年财务指标", tenant_id=data["tenant_id"], document_ids=(str(data["document"].id),)
        ),
        metric=metric,
        fiscal_year="2025",
        period=period,
        scope="CONSOLIDATED",
        query_class="EXACT_FACT",
    )

    def lookup(req):
        return lookup_persisted_financial_fact(
            query=req.scoped.query,
            company="贵州茅台",
            canonical_metric=req.metric,
            fiscal_year=req.fiscal_year,
            period_semantics="point_in_time" if req.period == "INSTANT" else "duration",
            tenant_id=req.scoped.tenant_id,
            session_factory=data["session_factory"],
        )

    result = FinancialFactEvidenceAdapter(lookup).retrieve(request)
    assert result.status == RetrievalStatus.FOUND
    assert result.route == RetrievalMode.FACT and result.deterministic
    assert result.cost_metadata["llm_calls"] == 0
    ev = result.evidence[0]
    assert ev.metric == metric and ev.scope == "CONSOLIDATED"
    assert ev.period["fiscal_year"] == 2025 or str(ev.period["fiscal_year"]) == "2025"
    assert ev.provenance["fact_id"] == ev.evidence_id
    assert ev.provenance["row_verification_status"] == "VERIFIED"
    assert ev.provenance["source_locator"] and ev.page
