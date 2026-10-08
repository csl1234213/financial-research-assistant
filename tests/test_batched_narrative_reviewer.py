"""Execution fixtures test contracts and cost gates, not semantic accuracy."""

from dataclasses import replace

import pytest

from core.answer_synthesis_batched_reviewer import BatchedNarrativeReviewer
from core.answer_synthesis_semantic import (
    EntailmentVerdict,
    SemanticClaimReview,
    SemanticReview,
    semantic_input_digest,
    validate_grounded_answer_review,
)
from core.answer_synthesis_usage import AccountedCompletionFailure, FailedCompletionUsage
from tests.test_narrative_review_batches import prepared as prepare_stress


def prepared():
    return prepare_stress(8)


class Reviewer:
    def __init__(self, mutation=None):
        self.calls = 0
        self.mutation = mutation

    def review(self, source, plan, draft, **budgets):
        self.calls += 1
        assert 0 < budgets["max_seconds"] <= 120
        assert budgets["max_tokens"] > 0
        result = SemanticReview("fixture", tuple(SemanticClaimReview(claim.claim_id,
            claim.evidence_ids, EntailmentVerdict.SUPPORTED, claim.causal_strength, "fixture")
            for claim in plan.claims), semantic_input_digest(source, plan, draft), 100, 20, 120)
        if self.mutation and self.calls == 2:
            return self.mutation(result)
        return result


def test_complete_review_binds_full_draft_and_accounts_all_calls():
    source, buffered = prepared()
    underlying = Reviewer()
    reviewer = BatchedNarrativeReviewer(underlying, max_total_tokens=65536)
    review = reviewer.review(source, buffered.plan, buffered.text)
    assert underlying.calls > 1
    assert review.total_tokens == underlying.calls * 120
    assert validate_grounded_answer_review(source, buffered.plan, review, buffered.text)
    assert not validate_grounded_answer_review(source, buffered.plan, review, buffered.text + " extra")


def test_insufficient_total_reservation_makes_zero_calls():
    source, buffered = prepared()
    underlying = Reviewer()
    with pytest.raises(ValueError, match="RESERVATION_EXCEEDED"):
        BatchedNarrativeReviewer(underlying, max_total_tokens=100).review(source, buffered.plan, buffered.text)
    assert underlying.calls == 0


@pytest.mark.parametrize("mutation", [
    lambda review: replace(review, claims=()),
    lambda review: replace(review, input_digest="changed"),
    lambda review: replace(review, reviewer_version="different"),
    lambda review: replace(review, claims=(review.claims[0],) * len(review.claims)),
    lambda review: replace(review, claims=(None,) + review.claims[1:]),
    lambda review: replace(review, reviewer_version=None),
])
def test_changed_or_incomplete_batch_never_returns_partial_review(mutation):
    source, buffered = prepared()
    reviewer = BatchedNarrativeReviewer(Reviewer(mutation), max_total_tokens=65536)
    with pytest.raises(AccountedCompletionFailure) as error:
        reviewer.review(source, buffered.plan, buffered.text)
    assert error.value.usage.total_tokens == 240


def test_failed_second_completion_accounts_prior_success():
    source, buffered = prepared()

    def failure(_review):
        raise AccountedCompletionFailure("failed", FailedCompletionUsage(100, 10, 110))

    reviewer = BatchedNarrativeReviewer(Reviewer(failure), max_total_tokens=65536)
    with pytest.raises(AccountedCompletionFailure) as error:
        reviewer.review(source, buffered.plan, buffered.text)
    assert error.value.usage.total_tokens == 230


def test_unsupported_claim_is_retained_and_blocks_full_release():
    source, buffered = prepared()

    def unsupported(review):
        claims = list(review.claims)
        claims[0] = replace(claims[0], verdict=EntailmentVerdict.UNSUPPORTED)
        return replace(review, claims=tuple(claims))

    reviewer = BatchedNarrativeReviewer(Reviewer(unsupported), max_total_tokens=65536)
    review = reviewer.review(source, buffered.plan, buffered.text)
    assert not validate_grounded_answer_review(source, buffered.plan, review, buffered.text)


def test_workflow_cannot_bypass_remaining_total_budget():
    from core.answer_synthesis_narrative_workflow import synthesize_narrative
    from tests.test_narrative_workflow import fixture_ports

    source, generator, _, _ = fixture_ports()
    underlying = Reviewer()
    reviewer = BatchedNarrativeReviewer(underlying, max_total_tokens=65536)
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer,
        enabled=True, max_total_tokens=1000, max_revisions=0)
    assert underlying.calls == 0
    assert result.reason == "REVIEW_FAILED_PREFLIGHT"
    assert result.total_tokens == 150 and result.usage_complete
    assert result.text is None


def test_workflow_revalidates_complete_aggregate_before_streaming():
    from core.answer_synthesis_narrative_workflow import synthesize_narrative, verified_narrative_outcome_chunks
    from tests.test_narrative_workflow import fixture_ports

    source, generator, _, _ = fixture_ports()
    reviewer = BatchedNarrativeReviewer(Reviewer(), max_total_tokens=65536)
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer,
        enabled=True, max_total_tokens=65536, max_revisions=0)
    assert result.reason == "REVIEWED_NARRATIVE"
    assert result.total_tokens == 270
    assert "".join(verified_narrative_outcome_chunks(source, result)) == result.text


def test_deadline_includes_preflight_and_stops_before_first_call():
    source, buffered = prepared()
    times = iter([0, 61])
    underlying = Reviewer()
    reviewer = BatchedNarrativeReviewer(underlying, max_total_tokens=65536, clock=lambda: next(times))
    with pytest.raises(ValueError, match="DEADLINE_EXHAUSTED"):
        reviewer.review(source, buffered.plan, buffered.text, max_seconds=60)
    assert underlying.calls == 0


def test_second_call_unknown_failure_is_not_retried_or_reported_complete():
    source, buffered = prepared()

    def unknown(_review):
        raise TimeoutError("fixture timeout")

    underlying = Reviewer(unknown)
    reviewer = BatchedNarrativeReviewer(underlying, max_total_tokens=65536)
    with pytest.raises(TimeoutError):
        reviewer.review(source, buffered.plan, buffered.text)
    assert underlying.calls == 2
    assert reviewer.receipts[-1]["usage_complete"] is False
    assert reviewer.receipts[-1]["known_prompt_tokens"] == 100
    assert reviewer.receipts[-1]["known_completion_tokens"] == 20


def test_bad_full_draft_preflight_has_known_zero_provider_usage():
    from core.answer_synthesis_usage import ReviewBatchPreflightFailure

    source, buffered = prepared()
    underlying = Reviewer()
    reviewer = BatchedNarrativeReviewer(underlying, max_total_tokens=65536)
    with pytest.raises(ReviewBatchPreflightFailure, match="PROJECTION_CHANGED"):
        reviewer.review(source, buffered.plan, buffered.text + " extra")
    assert underlying.calls == 0
    assert reviewer.receipts[-1]["provider_attempts"] == 0
