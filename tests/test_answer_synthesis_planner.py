from dataclasses import replace
from decimal import Decimal

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from core.answer_synthesis_contracts import AnswerType, VerificationFailure, adapt_retrieval_result
from core.answer_synthesis_planner import DeterministicAnswerPlanner, DeterministicAnswerVerifier
from core.structured_financial_query import lookup_persisted_financial_fact
from retrieval.adaptive_adapters import FinancialFactEvidenceAdapter
from retrieval.adaptive_contract import Evidence, RetrievalMode, RetrievalRequest, RetrievalResult, RetrievalStatus
from tests.test_structured_financial_query import moutai_rows, persisted_moutai  # noqa: F401


def evidence(identity="e1", end="2025-12-31", value="123.45", **changes):
    base = Evidence(
        identity,
        "STRUCTURED_FINANCIAL_FACT",
        "d1",
        "source row",
        RetrievalMode.FACT,
        "verified_financial_fact",
        "report.pdf",
        "贵州茅台",
        page=52,
        source_locator={"page": 52, "row": 3},
        structured_value=value,
        metric="total_assets",
        scope="CONSOLIDATED",
        statement="BALANCE_SHEET",
        period={"period_type": "INSTANT", "period_end": end, "fiscal_year": end[:4]},
        provenance={
            "tenant_id": 7,
            "structured_financial_fact": True,
            "row_verification_status": "VERIFIED",
            "mapping_status": "EXACT",
            "document_version": "a" * 64,
            "currency": "CNY",
            "unit": "CNY_YUAN",
        },
    )
    return replace(base, **changes)


def source(*items, answer_type=AnswerType.FACT, status=RetrievalStatus.FOUND):
    return adapt_retrieval_result(
        RetrievalResult(status, RetrievalMode.FACT, tuple(items)),
        query="总资产",
        tenant_id=7,
        answer_type=answer_type,
        locale="zh-CN",
    )


def test_exact_observation_is_locked_but_not_semantically_certified():
    incoming = source(evidence())
    plan = DeterministicAnswerPlanner().plan(incoming)
    assert plan.claims[0].observation["value"] == Decimal("123.45")
    result = DeterministicAnswerVerifier().verify(incoming, plan)
    assert result.failures == ()
    assert not result.passed and not result.semantic_review_complete
    assert not DeterministicAnswerVerifier().verify(incoming, plan, "new unsupported claim").passed


@pytest.mark.parametrize(
    "key,value,failure",
    [
        ("value", Decimal("999"), "NUMERIC_MUTATION"),
        ("currency", "USD", "NUMERIC_MUTATION"),
        ("unit", "CNY_BILLION", "NUMERIC_MUTATION"),
        ("period", {"period_end": "2024-12-31"}, "PERIOD_MISMATCH"),
        ("scope", "PARENT_COMPANY", "SCOPE_MISMATCH"),
        ("metric", "total_debt", "METRIC_MISMATCH"),
        ("company", "Tesla", "CITATION_WRONG_SOURCE"),
        ("document_version", "b" * 64, "CITATION_WRONG_SOURCE"),
        ("source_locator", {"page": 999}, "CITATION_WRONG_SOURCE"),
    ],
)
def test_mutation_is_detected(key, value, failure):
    incoming = source(evidence())
    plan = DeterministicAnswerPlanner().plan(incoming)
    original = plan.claims[0]
    mutated = replace(original, observation={**original.observation, key: value})
    result = DeterministicAnswerVerifier().verify(incoming, replace(plan, claims=(mutated,)))
    assert VerificationFailure(failure) in result.failures


@pytest.mark.parametrize(
    "field,value",
    [
        ("row_verification_status", "PARTIAL"),
        ("mapping_status", "AMBIGUOUS"),
        ("structured_financial_fact", False),
        ("document_version", None),
        ("currency", "UNKNOWN"),
    ],
)
def test_confidence_or_row_verification_alone_does_not_admit_fact(field, value):
    original = evidence()
    incoming = source(replace(original, confidence=1, provenance={**original.provenance, field: value}))
    plan = DeterministicAnswerPlanner().plan(incoming)
    assert plan.claims[0].claim_type == "UNCERTAINTY"


@pytest.mark.parametrize("value", [float("nan"), 123.45, True, "NaN", "Infinity", "bad"])
def test_unsafe_numeric_input_is_not_accepted(value):
    plan = DeterministicAnswerPlanner().plan(source(evidence(value=value)))
    assert plan.claims[0].claim_type == "UNCERTAINTY"


def test_trend_order_and_values_preserved_without_inferred_growth():
    incoming = source(evidence(), evidence("e2", "2024-12-31", "100"), answer_type=AnswerType.TREND)
    plan = DeterministicAnswerPlanner().plan(incoming)
    assert [c.observation["value"] for c in plan.claims] == [Decimal("100"), Decimal("123.45")]
    assert all(c.claim_type == "FACT" for c in plan.claims)
    assert not plan.relationships


def test_comparison_scope_mismatch_is_disclosed_not_computed():
    incoming = source(evidence(), evidence("e2", scope="PARENT_COMPANY"), answer_type=AnswerType.COMPARISON)
    plan = DeterministicAnswerPlanner().plan(incoming)
    assert "INCOMPARABLE_FINANCIAL_DIMENSIONS" in plan.caveats


@pytest.mark.parametrize(
    "dimension,value",
    [
        ("company", "Tesla"),
        ("metric", "total_debt"),
        ("scope", "PARENT_COMPANY"),
        ("period", {"period_type": "INSTANT", "period_end": "2024-12-31"}),
    ],
)
def test_query_dimensions_are_not_silently_substituted(dimension, value):
    incoming = replace(source(evidence()), required_dimensions={dimension: value})
    plan = DeterministicAnswerPlanner().plan(incoming)
    assert plan.claims[0].claim_type == "UNCERTAINTY"
    assert any("QUERY_DIMENSION_MISMATCH" in caveat for caveat in plan.caveats)


@pytest.mark.parametrize("status", [RetrievalStatus.CONFLICT, RetrievalStatus.ERROR, RetrievalStatus.AMBIGUOUS])
def test_retrieval_failure_does_not_become_fact_success(status):
    plan = DeterministicAnswerPlanner().plan(source(evidence(), status=status))
    assert plan.claims[0].claim_type == "UNCERTAINTY"


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
def test_real_p13_rows_through_sql_and_planner(persisted_moutai, metric, period):  # noqa: F811
    data = persisted_moutai
    request = RetrievalRequest(
        ScopedRequest(
            query="贵州茅台2025年财务指标", tenant_id=data["tenant_id"], document_ids=(str(data["document"].id),)
        ),
        metric=metric,
        fiscal_year="2025",
        period=period,
        scope="CONSOLIDATED",
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
    incoming = adapt_retrieval_result(
        result, query=request.scoped.query, tenant_id=data["tenant_id"], answer_type=AnswerType.FACT, locale="zh-CN"
    )
    plan = DeterministicAnswerPlanner().plan(incoming)
    assert plan.claims[0].observation is not None, plan.caveats
    assert plan.claims[0].observation["metric"] == metric
    checked = DeterministicAnswerVerifier().verify(incoming, plan)
    assert checked.failures == () and not checked.passed
    # 真实重建行继续经过受限展示链路；两种语言的原值/证据身份必须一致。
    from core.answer_synthesis_renderer import RestrictedAnswerRenderer, RestrictedOutputVerifier

    outputs = []
    for locale in ("zh-CN", "en"):
        scoped = replace(incoming, locale=locale, required_dimensions={"metric": metric, "scope": "CONSOLIDATED"})
        scoped_plan = DeterministicAnswerPlanner().plan(scoped)
        rendered = RestrictedAnswerRenderer().render(scoped, scoped_plan)
        assert RestrictedOutputVerifier().verify(scoped, scoped_plan, rendered).passed
        from core.answer_synthesis_workflow import BoundedSynthesisWorkflow

        outcome = BoundedSynthesisWorkflow().run(scoped, scoped_plan)
        assert outcome.mode == "TEMPLATE" and outcome.generation_calls == 0
        assert outcome.answer == rendered
        from core.answer_synthesis_draft_verifier import ControlledFactDraftVerifier, factual_sentence_variants

        paraphrase = factual_sentence_variants(scoped, scoped_plan)[0][1]
        assert ControlledFactDraftVerifier().verify(scoped, scoped_plan, paraphrase).passed
        outputs.append(rendered)
    assert outputs[0].citation_evidence_ids == outputs[1].citation_evidence_ids
    assert outputs[0].presentations[0].original_value == outputs[1].presentations[0].original_value
    from core.answer_synthesis_shadow import evaluate_structured_shadow

    shadow = evaluate_structured_shadow(
        query=request.scoped.query,
        tenant_id=data["tenant_id"],
        locale="zh-CN",
        intent={
            "intent": "FINANCIAL_FACT_QUERY",
            "companies": ["贵州茅台"],
            "canonical_metric": metric,
            "fiscal_year": "2025",
            "period_semantics": "point_in_time" if period == "INSTANT" else "duration",
            "structured_fact_lookup": result.trace,
        },
        evidence=[item.to_agent() for item in result.evidence],
        enabled=True,
    )
    assert shadow.status == "PASS", shadow
