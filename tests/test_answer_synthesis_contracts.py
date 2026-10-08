from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from agent.reasoning_models import Evidence as AgentEvidence
from core.answer_synthesis_contracts import (
    AnswerPlan,
    AnswerType,
    CausalStrength,
    ClaimEdge,
    ClaimType,
    GroundedClaim,
    RelationType,
    RevisionPolicy,
    VerificationFailure,
    VerificationResult,
    adapt_legacy_evidence,
    adapt_retrieval_result,
    legacy_evidence_id,
)
from retrieval.adaptive_contract import CoverageReport, Evidence, RetrievalMode, RetrievalResult, RetrievalStatus


def evidence():
    return Evidence(
        "fact-1",
        "financial_fact",
        "doc-7",
        "货币资金",
        RetrievalMode.FACT,
        "financial_statement",
        "report.pdf",
        "Moutai",
        page=52,
        bbox=[1, 2, 3, 4],
        source_locator={"page": 52, "row": 3},
        source_block_ids=("block-3",),
        structured_value=Decimal("51690610946.50"),
        metric="cash_and_bank_balances",
        period={"end": "2025-12-31"},
        scope="CONSOLIDATED",
        statement="BALANCE_SHEET",
        confidence=1.0,
        provenance={"tenant_id": 7, "content_sha256": "a" * 64, "custom": ["x"]},
        citation={"page": 52},
    )


def source(ev=None, **kwargs):
    result = RetrievalResult(RetrievalStatus.FOUND, RetrievalMode.FACT, (ev or evidence(),), **kwargs)
    return adapt_retrieval_result(
        result, query="货币资金是多少？", tenant_id=7, answer_type=AnswerType.FACT, locale="zh-CN"
    )


def claim(**kwargs):
    return GroundedClaim("c1", ClaimType.FACT, "cash balance observation", ("fact-1",), **kwargs)


def test_preserves_all_evidence_fields_without_mutating_source():
    ev = evidence()
    adapted = source(ev)
    snapshot = adapted.evidence[0].payload
    assert set(snapshot) == set(ev.__dataclass_fields__)
    assert snapshot["structured_value"] == Decimal("51690610946.50")
    assert snapshot["metric"] == "cash_and_bank_balances"
    assert snapshot["source_locator"]["row"] == 3
    assert snapshot["scope"] == "CONSOLIDATED"
    assert snapshot["period"]["end"] == "2025-12-31"
    assert snapshot["source_block_ids"] == ("block-3",)
    ev.period["end"] = "2024-12-31"
    ev.provenance["custom"].append("y")
    assert snapshot["period"]["end"] == "2025-12-31"
    assert snapshot["provenance"]["custom"] == ("x",)
    with pytest.raises(TypeError):
        snapshot["period"]["end"] = "2023-12-31"
    with pytest.raises(FrozenInstanceError):
        adapted.locale = "en"


@pytest.mark.parametrize("owner", [None, True, "7", 7.0, 8])
def test_owner_is_explicit_and_not_coerced(owner):
    ev = replace(evidence(), provenance={"tenant_id": owner})
    with pytest.raises(ValueError, match="tenant"):
        source(ev)


@pytest.mark.parametrize("status", list(RetrievalStatus))
def test_retrieval_status_and_unknown_coverage_are_preserved(status):
    result = RetrievalResult(status, RetrievalMode.HYBRID)
    adapted = adapt_retrieval_result(
        result, query="风险？", tenant_id=7, answer_type=AnswerType.RISK_ANALYSIS, locale="en"
    )
    assert adapted.retrieval_status == status.value
    assert adapted.coverage["complete"] is None
    assert adapted.coverage["coverage_ratio"] is None


@pytest.mark.parametrize("answer_type", list(AnswerType))
def test_answer_type_is_independent_of_retrieval_route(answer_type):
    result = RetrievalResult(RetrievalStatus.FOUND, RetrievalMode.HYBRID, (evidence(),))
    adapted = adapt_retrieval_result(result, query="question", tenant_id=7, answer_type=answer_type, locale="en")
    assert adapted.answer_type == answer_type
    assert adapted.retrieval_route == "HYBRID"


def test_unverified_evidence_not_promoted_to_verified_claim():
    assert claim().fact_status == "UNVERIFIED"
    assert not VerificationResult().passed
    assert VerificationResult(semantic_review_complete=True).passed
    assert not VerificationResult((VerificationFailure.UNSUPPORTED_CLAIM,), semantic_review_complete=True).passed


def test_factual_claim_requires_evidence_but_uncertainty_may_have_none():
    with pytest.raises(ValueError, match="require evidence"):
        GroundedClaim("c", ClaimType.FACT, "assertion")
    GroundedClaim("u", ClaimType.UNCERTAINTY, "not enough evidence")


def test_binding_rejects_unknown_citation_duplicate_claim_and_dangling_edge():
    base = AnswerPlan(AnswerType.FACT, (claim(),))
    base.validate_bindings(source())
    for bad in (
        replace(base, claims=(replace(claim(), evidence_ids=("unknown",)),)),
        replace(base, claims=(claim(), claim())),
        replace(base, relationships=(ClaimEdge("c1", "missing", RelationType.SUPPORTS),)),
    ):
        with pytest.raises(ValueError):
            bad.validate_bindings(source())


def test_exhaustive_unknown_coverage_does_not_imply_complete():
    adapted = replace(source(), answer_type=AnswerType.EXHAUSTIVE_LIST)
    plan = AnswerPlan(AnswerType.EXHAUSTIVE_LIST, (claim(),))
    with pytest.raises(ValueError, match="coverage"):
        plan.validate_bindings(adapted)
    replace(plan, caveats=("Coverage unknown",)).validate_bindings(adapted)
    complete = source(coverage=CoverageReport(complete=True))
    plan.validate_bindings(replace(complete, answer_type=AnswerType.EXHAUSTIVE_LIST))


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        claim(confidence=confidence)


def test_contributing_factor_not_inferred_from_cooccurrence():
    for strength, caveat in [(CausalStrength.UNSUPPORTED, "unsupported"), (CausalStrength.PLAUSIBLE_ASSOCIATION, None)]:
        with pytest.raises(ValueError):
            GroundedClaim(
                "c", ClaimType.CONTRIBUTING_FACTOR, "factor", ("fact-1",), causal_strength=strength, caveat=caveat
            )


@pytest.mark.parametrize("limit", [-1, 3, True, 1.0])
def test_revision_limit_is_bounded(limit):
    with pytest.raises(ValueError):
        RevisionPolicy(limit)


def test_versioned_identity_is_deterministic_and_scope_sensitive():
    args = dict(tenant_id=7, document_id="doc", content_sha256="a" * 64, locator={"page": 5, "block": "b"})
    first = legacy_evidence_id(**args)
    assert first == legacy_evidence_id(**{**args, "locator": {"block": "b", "page": 5}})
    for key, value in [("tenant_id", 8), ("content_sha256", "b" * 64), ("document_id", "doc2")]:
        assert first != legacy_evidence_id(**{**args, key: value})
    with pytest.raises(ValueError):
        legacy_evidence_id(**{**args, "content_sha256": "missing"})


def test_legacy_bridge_preserves_original_provenance_and_does_not_use_rank():
    metadata = {
        "tenant_id": 7,
        "document_id": "doc",
        "content_sha256": "a" * 64,
        "source_locator": {"page": 52, "block": "b"},
        "page": 52,
        "value": Decimal("123.45"),
        "canonical_metric": "total_assets",
        "period_context": {"end": "2025-12-31"},
        "scope": "PARENT_COMPANY",
        "statement_type": "BALANCE_SHEET",
        "rank": 1,
        "custom": ["preserved"],
    }
    legacy = AgentEvidence("row", "report.pdf", "Moutai", 1, metadata)
    first = adapt_legacy_evidence(legacy, tenant_id=7, route=RetrievalMode.HYBRID)
    metadata["rank"] = 9
    second = adapt_legacy_evidence(legacy, tenant_id=7, route=RetrievalMode.HYBRID)
    assert first.evidence_id == second.evidence_id
    assert first.payload["structured_value"] == Decimal("123.45")
    assert first.payload["period"]["end"] == "2025-12-31"
    assert first.payload["provenance"]["custom"] == ("preserved",)
    assert first.payload["scope"] == "PARENT_COMPANY"
    assert first.payload["provenance"]["rank"] == 1


def test_legacy_bridge_rejects_unversioned_source():
    with pytest.raises(ValueError, match="version"):
        adapt_legacy_evidence(AgentEvidence("text", "report.pdf"), tenant_id=7, route=RetrievalMode.HYBRID)
