"""Opt-in narrative claim assembly; candidates remain unverified until review.

Every rendered assertion comes from an explicit claim, not an untracked prose
field. This module does not call a provider or certify semantic correctness.
"""

import re
from dataclasses import dataclass

from core.answer_synthesis_contracts import (
    AnswerPlan,
    AnswerType,
    CausalStrength,
    ClaimType,
    GroundedClaim,
    SynthesisInput,
)
from core.answer_synthesis_semantic import SemanticReview, validate_grounded_answer_review
from core.evidence_subject_guard import bind_claim_subject
from core.narrative_subject_binding import subject_binding

NARRATIVE_TYPES = frozenset({AnswerType.EXPLANATION, AnswerType.RISK_ANALYSIS,
    AnswerType.CROSS_SECTION, AnswerType.CROSS_DOCUMENT, AnswerType.EXHAUSTIVE_LIST,
    AnswerType.CAUSAL_ANALYSIS})
_NUMBERS = re.compile(r"[-+]?\d+(?:[,，]\d{3})*(?:\.\d+)?%?")


@dataclass(frozen=True)
class BufferedNarrative:
    plan: AnswerPlan
    text: str
    citation_evidence_ids: tuple[str, ...]


def assemble_narrative(source: SynthesisInput, candidate: dict) -> BufferedNarrative:
    if source.answer_type not in NARRATIVE_TYPES or source.retrieval_status not in {"FOUND", "PARTIAL"}:
        raise ValueError("NARRATIVE_SYNTHESIS_NOT_AVAILABLE")
    if not isinstance(candidate, dict) or set(candidate) != {"claims"}:
        raise ValueError("INVALID_NARRATIVE_SCHEMA")
    rows = candidate["claims"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("NARRATIVE_CLAIM_BUDGET")
    evidence = {item.evidence_id: item for item in source.evidence}
    claims = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"text", "evidence_ids", "causal_strength", "caveat"}:
            raise ValueError("INVALID_NARRATIVE_CLAIM_SCHEMA")
        text, ids = row["text"], row["evidence_ids"]
        if (not isinstance(text, str) or not text.strip() or len(text) > 2000
                or any(mark in text for mark in ("\n", "\r", "[", "]", "<", ">"))
                or not isinstance(ids, list) or not ids or any(not isinstance(eid, str) for eid in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= evidence.keys()):
            raise ValueError("INVALID_NARRATIVE_CLAIM")
        strength = CausalStrength(row["causal_strength"])
        for eid in ids:
            # Explicit query dimensions cannot be silently dropped by narrative
            # generation. Missing source dimensions are not inferred from prose.
            payload = evidence[eid].payload
            binding = subject_binding(payload)
            if binding is not None and not binding.allows(text):
                raise ValueError("NARRATIVE_SUBJECT_ATTRIBUTION_REQUIRED")
            for key, required in source.required_dimensions.items():
                actual = payload.get(key)
                if key in {"currency", "unit"}:
                    actual = payload.get("provenance", {}).get(key)
                if actual != required:
                    raise ValueError("NARRATIVE_QUERY_DIMENSION_MISMATCH")
        caveat = row["caveat"]
        if caveat is not None and (not isinstance(caveat, str) or not caveat.strip() or len(caveat) > 500
                                  or any(mark in caveat for mark in ("\n", "\r", "[", "]", "<", ">"))):
            raise ValueError("INVALID_CAUSAL_CAVEAT")
        claim_subject = bind_claim_subject(source, text, ids, caveat=caveat)
        if source.answer_type != AnswerType.CAUSAL_ANALYSIS and strength != CausalStrength.UNSUPPORTED:
            raise ValueError("CAUSAL_STRENGTH_NOT_APPLICABLE")
        # Lexical numeric locking is necessary, not sufficient: a number found
        # in evidence can still be assigned to the wrong company/period/metric.
        # Independent entailment review must reject those semantic mutations.
        originals = " ".join(str(evidence[eid].payload.get("text", "")) for eid in ids)
        allowed_numbers = set(_NUMBERS.findall(originals))
        if any(number not in allowed_numbers for number in _NUMBERS.findall(text + (caveat or ""))):
            raise ValueError("NARRATIVE_NUMERIC_MUTATION")
        claim_type = (ClaimType.CONTRIBUTING_FACTOR if strength != CausalStrength.UNSUPPORTED
                      else ClaimType.INTERPRETATION)
        claims.append(GroundedClaim(f"narrative:{index}", claim_type, text.strip(), tuple(ids),
            causal_strength=strength, caveat=caveat, claim_subject=claim_subject))
    if source.answer_type == AnswerType.CROSS_DOCUMENT:
        documents = {evidence[eid].document_id for claim in claims for eid in claim.evidence_ids}
        if len(documents) < 2:
            raise ValueError("CROSS_DOCUMENT_EVIDENCE_REQUIRED")
    if source.answer_type == AnswerType.CROSS_SECTION:
        used = [evidence[eid] for claim in claims for eid in claim.evidence_ids]
        labels = [item.payload.get("section") for item in used]
        if (any(not isinstance(label, str) or not label.strip() for label in labels)
                or len({label.strip() for label in labels}) < 2
                or len({item.document_id for item in used}) != 1):
            raise ValueError("CROSS_SECTION_EVIDENCE_REQUIRED")
    caveats = ()
    if source.answer_type == AnswerType.EXHAUSTIVE_LIST and source.coverage.get("complete") is not True:
        caveats = ("INCOMPLETE_COVERAGE",)
    plan = AnswerPlan(source.answer_type, tuple(claims), caveats=caveats)
    plan.validate_bindings(source)
    citation_ids = tuple(dict.fromkeys(eid for claim in claims for eid in claim.evidence_ids))
    numbering = {eid: index + 1 for index, eid in enumerate(citation_ids)}
    lines = []
    if caveats:
        lines.append({"zh-CN": "以下仅列出当前证据支持的项目，并非完整清单。",
                      "zh-TW": "以下僅列出目前證據支持的項目，並非完整清單。",
                      "en": "Only evidence-supported items are listed; coverage is incomplete."}[source.locale])
    for claim in claims:
        # Caveats are part of reviewed semantic content, never hidden metadata.
        content = claim.semantic_content + (f" ({claim.caveat})" if claim.caveat else "")
        lines.append("- " + content + " " + " ".join(f"[{numbering[eid]}]" for eid in claim.evidence_ids))
    return BufferedNarrative(plan, "\n".join(lines), citation_ids)


def release_reviewed_narrative(source, candidate, review: SemanticReview):
    rebuilt = assemble_narrative(source, candidate)
    if not validate_grounded_answer_review(source, rebuilt.plan, review, rebuilt.text):
        raise ValueError("NARRATIVE_SEMANTIC_REVIEW_REQUIRED")
    return rebuilt
