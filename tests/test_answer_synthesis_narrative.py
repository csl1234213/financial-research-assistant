from dataclasses import replace

import pytest

from core.answer_synthesis_contracts import AnswerType
from core.answer_synthesis_narrative import assemble_narrative, release_reviewed_narrative
from core.answer_synthesis_semantic import (
    EntailmentVerdict,
    SemanticClaimReview,
    SemanticReview,
    semantic_input_digest,
)
from tests.test_answer_synthesis_workflow import inputs


def narrative_inputs(kind=AnswerType.EXPLANATION):
    source, _ = inputs()
    evidence = replace(source.evidence[0], payload={**source.evidence[0].payload,
        "text": "Demand weakened. Revenue fell 10%."})
    source = replace(source, answer_type=kind, evidence=(evidence,))
    candidate = {"claims": [{"text": "Revenue fell 10%.", "evidence_ids": [evidence.evidence_id],
        "causal_strength": "UNSUPPORTED", "caveat": None}]}
    return source, candidate


def test_review_binds_all_rendered_claims_and_rejects_changed_draft():
    source, candidate = narrative_inputs()
    result = assemble_narrative(source, candidate)
    review = SemanticReview("fixture-reviewer", tuple(SemanticClaimReview(claim.claim_id,
        claim.evidence_ids, EntailmentVerdict.SUPPORTED, claim.causal_strength, "fixture support")
        for claim in result.plan.claims), semantic_input_digest(source, result.plan, result.text))
    assert release_reviewed_narrative(source, candidate, review) == result
    candidate["claims"][0]["text"] = "Revenue increased 10%."
    with pytest.raises(ValueError, match="SEMANTIC_REVIEW_REQUIRED"):
        release_reviewed_narrative(source, candidate, review)


@pytest.mark.parametrize("change", [
    {"text": "Revenue fell 11%."}, {"text": "Revenue fell 10%. [99]"},
    {"evidence_ids": ["missing"]}, {"causal_strength": "DIRECTLY_STATED"},
    {"caveat": "Revenue fell 99%."},
])
def test_unlocked_numbers_citations_and_causality_are_rejected(change):
    source, candidate = narrative_inputs()
    candidate["claims"][0].update(change)
    with pytest.raises(ValueError):
        assemble_narrative(source, candidate)


def test_cross_document_and_exhaustive_constraints():
    source, candidate = narrative_inputs(AnswerType.CROSS_DOCUMENT)
    with pytest.raises(ValueError, match="CROSS_DOCUMENT_EVIDENCE_REQUIRED"):
        assemble_narrative(source, candidate)
    source = replace(source, answer_type=AnswerType.EXHAUSTIVE_LIST, coverage={"complete": False})
    assert "INCOMPLETE_COVERAGE" in assemble_narrative(source, candidate).plan.caveats


@pytest.mark.parametrize("dimension", ["company", "metric", "scope", "currency", "unit", "statement", "period"])
def test_explicit_query_dimensions_cannot_be_dropped(dimension):
    source, candidate = narrative_inputs()
    with pytest.raises(ValueError, match="QUERY_DIMENSION_MISMATCH"):
        assemble_narrative(replace(source, required_dimensions={dimension: "unmatched"}), candidate)


@pytest.mark.parametrize("second_section,second_document,accepted", [
    ("Risk Factors", None, True),
    (" Management Discussion ", None, False),
    (" ", None, False),
    (None, None, False),
    (42, None, False),
    ("Risk Factors", "another-report", False),
])
def test_cross_section_requires_two_named_sections_in_same_report(second_section, second_document, accepted):
    source, candidate = narrative_inputs(AnswerType.CROSS_SECTION)
    first = replace(source.evidence[0], payload={**source.evidence[0].payload, "section": "Management Discussion"})
    second = replace(first, evidence_id="section-2", document_id=second_document or first.document_id,
                     payload={**first.payload, "section": second_section})
    source = replace(source, evidence=(first, second))
    candidate["claims"][0]["evidence_ids"].append(second.evidence_id)
    if accepted:
        answer = assemble_narrative(source, candidate)
        assert answer.citation_evidence_ids == (first.evidence_id, second.evidence_id)
    else:
        with pytest.raises(ValueError, match="CROSS_SECTION_EVIDENCE_REQUIRED"):
            assemble_narrative(source, candidate)
