"""Explicit semantic-review boundary; numeric checks never imply entailment."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from core.answer_synthesis_contracts import AnswerPlan, CausalStrength, SynthesisInput


class EntailmentVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class SemanticClaimReview:
    claim_id: str
    evidence_ids: tuple[str, ...]
    verdict: EntailmentVerdict
    causal_strength: CausalStrength
    rationale: str


@dataclass(frozen=True)
class SemanticReview:
    reviewer_version: str
    claims: tuple[SemanticClaimReview, ...]
    input_digest: str
    # Optional for human/offline reviewers; provider workflows must require
    # authoritative values before accounting or authorizing another inference.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


def semantic_input_digest(source: SynthesisInput, plan: AnswerPlan, draft: str = "") -> str:
    """Bind a review to exact evidence, claims, query, locale and buffered draft."""
    def encode(value):
        if is_dataclass(value):
            return {"type": type(value).__name__, "fields": {
                item.name: encode(getattr(value, item.name)) for item in fields(value)
            }}
        if isinstance(value, Mapping):
            return {str(key): encode(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [encode(item) for item in value]
        if isinstance(value, Decimal):
            return {"decimal": str(value)}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise ValueError("unsupported semantic review input")
    material = json.dumps(encode((source, plan, draft)), sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class EvidenceEntailmentReviewer(Protocol):
    """Adapters independently assess claims using the complete cited evidence.

    This interface does not authorize Provider calls. Model judgments are
    fallible and must be evaluated against human gold labels before rollout.
    """

    def review(self, source: SynthesisInput, plan: AnswerPlan, draft: str) -> SemanticReview: ...


def validate_semantic_review(
    source: SynthesisInput, plan: AnswerPlan, review: SemanticReview, draft: str = "",
) -> bool:
    """Fail closed on uncertain/missing/duplicate claims or citation/causal drift.

    A True result validates the review contract, not the reviewer's accuracy.
    Numeric, period, scope and final-render validation remain separate gates.
    """
    plan.validate_bindings(source)
    if not isinstance(review, SemanticReview) or not review.reviewer_version.strip():
        return False
    if review.input_digest != semantic_input_digest(source, plan, draft):
        return False
    claims = {claim.claim_id: claim for claim in plan.claims}
    if len(review.claims) != len(claims) or len({item.claim_id for item in review.claims}) != len(claims):
        return False
    for item in review.claims:
        claim = claims.get(item.claim_id)
        if (claim is None or item.verdict != EntailmentVerdict.SUPPORTED
                or not isinstance(item.verdict, EntailmentVerdict)
                or item.evidence_ids != claim.evidence_ids or not item.rationale.strip()):
            return False
        if item.causal_strength != claim.causal_strength:
            return False
    return True


def validate_grounded_answer_review(source, plan, review, draft) -> bool:
    """Require complete claim projection in addition to a fallible model review.

    The lower-level review contract deliberately remains independently usable
    for auditing. It is not sufficient authorization to publish arbitrary text.
    """
    if not isinstance(draft, str) or not draft.strip():
        return False
    try:
        from core.answer_synthesis_contracts import AnswerType
        from core.answer_synthesis_narrative import NARRATIVE_TYPES, assemble_narrative

        if source.answer_type in NARRATIVE_TYPES:
            candidate = {"claims": [{"text": claim.semantic_content,
                "evidence_ids": list(claim.evidence_ids),
                "causal_strength": claim.causal_strength.value, "caveat": claim.caveat}
                for claim in plan.claims]}
            rebuilt = assemble_narrative(source, candidate)
            complete = rebuilt.plan == plan and rebuilt.text == draft
        elif source.answer_type == AnswerType.FACT:
            from core.answer_synthesis_draft_verifier import ControlledFactDraftVerifier
            from core.answer_synthesis_renderer import RestrictedAnswerRenderer

            complete = RestrictedAnswerRenderer().render(source, plan).text == draft
            if not complete:
                result = ControlledFactDraftVerifier().verify(source, plan, draft)
                complete = result.passed and set(result.reviewed_claim_ids) == {
                    claim.claim_id for claim in plan.claims}
        elif source.answer_type in {AnswerType.COMPARISON, AnswerType.TREND}:
            from core.answer_synthesis_analysis import AnalyticalAnswerRenderer

            complete = AnalyticalAnswerRenderer().render(source, plan).text == draft
        else:
            # Unknown projection strategies cannot gain publication permission
            # merely because a model returns SUPPORTED.
            complete = False
        return complete and validate_semantic_review(source, plan, review, draft)
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
