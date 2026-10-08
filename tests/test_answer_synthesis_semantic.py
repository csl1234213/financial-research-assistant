from dataclasses import replace

import pytest

from core.answer_synthesis_contracts import CausalStrength
from core.answer_synthesis_semantic import (
    EntailmentVerdict,
    SemanticClaimReview,
    SemanticReview,
    semantic_input_digest,
    validate_semantic_review,
)
from tests.test_answer_synthesis_workflow import inputs


def prepared():
    source, plan = inputs()
    claim = plan.claims[0]
    item = SemanticClaimReview(claim.claim_id, claim.evidence_ids, EntailmentVerdict.SUPPORTED,
                               claim.causal_strength, "Explicit source statement")
    return source, plan, SemanticReview("fixture-reviewer-not-semantic-certification", (item,),
                                       semantic_input_digest(source, plan))


def test_complete_review_has_a_separate_semantic_contract():
    source, plan, review = prepared()
    assert validate_semantic_review(source, plan, review)


@pytest.mark.parametrize("mutation", ["uncertain", "unsupported", "missing", "duplicate", "citation", "causal", "version"])
def test_incomplete_or_drifting_semantic_review_cannot_pass(mutation):
    source, plan, review = prepared()
    item = review.claims[0]
    if mutation in {"uncertain", "unsupported"}:
        review = replace(review, claims=(replace(item, verdict=EntailmentVerdict(mutation.upper())),))
    elif mutation == "missing":
        review = replace(review, claims=())
    elif mutation == "duplicate":
        review = replace(review, claims=(item, item))
    elif mutation == "citation":
        review = replace(review, claims=(replace(item, evidence_ids=("wrong",)),))
    elif mutation == "causal":
        review = replace(review, claims=(replace(item, causal_strength=CausalStrength.DIRECTLY_STATED),))
    else:
        review = replace(review, reviewer_version="")
    assert not validate_semantic_review(source, plan, review)


@pytest.mark.parametrize("mutation", ["claim", "query", "locale", "draft", "evidence"])
def test_previous_review_cannot_be_replayed_after_input_change(mutation):
    source, plan, review = prepared()
    draft = ""
    if mutation == "claim":
        plan = replace(plan, claims=(replace(plan.claims[0], semantic_content="different conclusion"),))
    elif mutation == "query":
        source = replace(source, query="different question")
    elif mutation == "locale":
        source = replace(source, locale="en")
    elif mutation == "draft":
        draft = "unreviewed additional conclusion"
    else:
        item = source.evidence[0]
        source = replace(source, evidence=(replace(item, payload={**item.payload, "text": "changed source"}),))
    assert not validate_semantic_review(source, plan, review, draft)
