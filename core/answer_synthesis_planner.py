"""Offline structured planning and deterministic checks, not semantic certification."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from core.answer_synthesis_contracts import (
    AnswerPlan,
    AnswerType,
    ClaimType,
    EvidenceSnapshot,
    GroundedClaim,
    SynthesisInput,
    VerificationResult,
)
from core.answer_synthesis_contracts import (
    VerificationFailure as Failure,
)


def locked_observation(evidence: EvidenceSnapshot) -> dict[str, Any]:
    """Only explicit P1.5/P1.7 structured observations qualify, not confidence scores."""
    data = evidence.payload
    provenance = data["provenance"]
    if provenance.get("structured_financial_fact") is not True:
        raise ValueError("not a structured financial fact")
    if provenance.get("row_verification_status") != "VERIFIED":
        raise ValueError("row not verified")
    if provenance.get("mapping_status") not in {"EXACT", "SUPPORTED"}:
        raise ValueError("metric not verified")
    if not data.get("source_locator") or not data.get("page"):
        raise ValueError("source locator missing")
    digest = provenance.get("document_version") or provenance.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("document version missing")
    raw = data.get("structured_value")
    if isinstance(raw, (float, bool)) or not isinstance(raw, (str, int, Decimal)):
        raise ValueError("exact decimal value required")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("invalid value") from exc
    if not value.is_finite():
        raise ValueError("non-finite value")
    period = data["period"]
    end = period.get("period_end")
    start = period.get("period_start")
    kind = period.get("period_type")
    if kind not in {"INSTANT", "DURATION"} or not end:
        raise ValueError("explicit period required")
    end_date = date.fromisoformat(end)
    if kind == "DURATION" and (not start or date.fromisoformat(start) > end_date):
        raise ValueError("duration start required")
    dimensions = {
        "company": data.get("company"),
        "metric": data.get("metric"),
        "scope": data.get("scope"),
        "currency": provenance.get("currency"),
        "unit": provenance.get("unit"),
        "statement": data.get("statement"),
    }
    if any(not item or str(item).upper() == "UNKNOWN" for item in dimensions.values()):
        raise ValueError("financial dimensions incomplete")
    return {
        **dimensions,
        "value": value,
        "period": period,
        "document_id": evidence.document_id,
        "document_version": digest,
        "source_locator": data["source_locator"],
    }


class DeterministicAnswerPlanner:
    """Plan explicit structured facts only; never classify raw narrative with an LLM."""

    def plan(self, source: SynthesisInput) -> AnswerPlan:
        if source.answer_type == AnswerType.AMBIGUOUS:
            # Answer routing, not retrieval confidence, declares ambiguity.
            # Retrieved numbers cannot silently choose a financial interpretation.
            plan = AnswerPlan(
                AnswerType.AMBIGUOUS,
                (GroundedClaim("query-ambiguity", ClaimType.UNCERTAINTY,
                               "QUERY_INTERPRETATION_REQUIRED"),),
                caveats=("QUERY_INTERPRETATION_REQUIRED",),
                output_structure=("clarification",),
                direct_answer_required=False,
            )
            plan.validate_bindings(source)
            return plan
        claims: list[GroundedClaim] = []
        caveats: list[str] = []
        supported = {AnswerType.FACT, AnswerType.COMPARISON, AnswerType.TREND}
        if source.answer_type not in supported or source.retrieval_status not in {"FOUND", "PARTIAL"}:
            caveats.append("STRUCTURED_SYNTHESIS_NOT_AVAILABLE")
        else:
            for evidence in source.evidence:
                try:
                    observation = locked_observation(evidence)
                except (ValueError, TypeError):
                    caveats.append("EVIDENCE_NOT_ELIGIBLE:" + evidence.evidence_id)
                    continue
                if any(observation.get(key) != value for key, value in source.required_dimensions.items()):
                    caveats.append("QUERY_DIMENSION_MISMATCH:" + evidence.evidence_id)
                    continue
                claims.append(
                    GroundedClaim(
                        claim_id="observation:" + evidence.evidence_id,
                        claim_type=ClaimType.FACT,
                        semantic_content=observation["metric"],
                        evidence_ids=(evidence.evidence_id,),
                        fact_status="SOURCE_VERIFIED",
                        observation=observation,
                    )
                )
        if source.retrieval_status == "PARTIAL":
            caveats.append("RETRIEVAL_PARTIAL")
        if not source.required_dimensions:
            caveats.append("QUERY_SEMANTICS_NOT_BOUND")
        if source.answer_type == AnswerType.TREND:
            claims.sort(key=lambda claim: claim.observation["period"]["period_end"])
        if source.answer_type in {AnswerType.COMPARISON, AnswerType.TREND}:
            if len(claims) < 2:
                caveats.append("INSUFFICIENT_COMPARABLE_OBSERVATIONS")
            keys = ("metric", "scope", "currency", "unit", "statement")
            signatures = {tuple(claim.observation[key] for key in keys) for claim in claims}
            if len(signatures) > 1:
                caveats.append("INCOMPARABLE_FINANCIAL_DIMENSIONS")
            # 不根据年份差或金额变化自动添加增长、原因、同比结论。
            if source.answer_type == AnswerType.TREND and len({c.observation["company"] for c in claims}) > 1:
                caveats.append("TREND_COMPANY_MISMATCH")
        if not claims:
            claims.append(GroundedClaim("uncertainty", ClaimType.UNCERTAINTY, "NO_ELIGIBLE_STRUCTURED_FACTS"))
        plan = AnswerPlan(source.answer_type, tuple(claims), caveats=tuple(dict.fromkeys(caveats)))
        plan.validate_bindings(source)
        return plan


class DeterministicAnswerVerifier:
    """Check observation locks; free text entailment remains explicitly unreviewed."""

    def verify(self, source: SynthesisInput, plan: AnswerPlan, draft: str = "") -> VerificationResult:
        failures: list[Failure] = []
        by_id = {evidence.evidence_id: evidence for evidence in source.evidence}
        try:
            plan.validate_bindings(source)
        except ValueError:
            failures.append(Failure.CITATION_WRONG_SOURCE)
        reviewed = []
        for claim in plan.claims:
            reviewed.append(claim.claim_id)
            if claim.claim_type == ClaimType.UNCERTAINTY:
                continue
            if not claim.evidence_ids:
                failures.append(Failure.CITATION_MISSING)
                continue
            if claim.claim_type != ClaimType.FACT or claim.observation is None:
                failures.append(Failure.UNSUPPORTED_CLAIM)
                continue
            if len(claim.evidence_ids) != 1 or claim.evidence_ids[0] not in by_id:
                failures.append(Failure.CITATION_WRONG_SOURCE)
                continue
            try:
                expected = locked_observation(by_id[claim.evidence_ids[0]])
            except (ValueError, TypeError):
                failures.append(Failure.UNSUPPORTED_CLAIM)
                continue
            actual: Mapping = claim.observation
            checks = {
                "value": Failure.NUMERIC_MUTATION,
                "currency": Failure.NUMERIC_MUTATION,
                "unit": Failure.NUMERIC_MUTATION,
                "period": Failure.PERIOD_MISMATCH,
                "scope": Failure.SCOPE_MISMATCH,
                "metric": Failure.METRIC_MISMATCH,
                "company": Failure.CITATION_WRONG_SOURCE,
                "document_id": Failure.CITATION_WRONG_SOURCE,
                "document_version": Failure.CITATION_WRONG_SOURCE,
                "source_locator": Failure.CITATION_WRONG_SOURCE,
                "statement": Failure.METRIC_MISMATCH,
            }
            for key, failure in checks.items():
                if actual.get(key) != expected[key]:
                    failures.append(failure)
            for key, value in source.required_dimensions.items():
                if actual.get(key) != value:
                    failures.append(checks[key])
            if claim.semantic_content != expected["metric"]:
                failures.append(Failure.UNSUPPORTED_CLAIM)
        # draft 当前没有经过 claim extraction/蕴含审核，不能因 observation 一致就放行自然语言。
        return VerificationResult(tuple(dict.fromkeys(failures)), tuple(reviewed), semantic_review_complete=False)
