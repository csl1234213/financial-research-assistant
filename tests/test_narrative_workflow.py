from dataclasses import replace
from unittest.mock import Mock

import pytest

from core.answer_synthesis_narrative import assemble_narrative
from core.answer_synthesis_narrative_ollama import GeneratedNarrative
from core.answer_synthesis_narrative_workflow import synthesize_narrative, verified_narrative_outcome_chunks
from core.answer_synthesis_semantic import (
    EntailmentVerdict,
    SemanticClaimReview,
    SemanticReview,
    semantic_input_digest,
)
from core.answer_synthesis_usage import AccountedCompletionFailure, FailedCompletionUsage, ProviderPreflightFailure
from tests.test_answer_synthesis_narrative import narrative_inputs


def fixture_ports():
    source, candidate = narrative_inputs()
    buffered = assemble_narrative(source, candidate)
    generation = GeneratedNarrative(buffered, "fixture-model", 100, 50, 150)
    reviews = tuple(SemanticClaimReview(claim.claim_id, claim.evidence_ids, EntailmentVerdict.SUPPORTED,
        claim.causal_strength, "fixture support") for claim in buffered.plan.claims)
    review = SemanticReview("fixture", reviews, semantic_input_digest(source, buffered.plan, buffered.text), 100, 20, 120)
    generator, reviewer = Mock(), Mock()
    generator.generate.return_value, reviewer.review.return_value = generation, review
    return source, generator, reviewer, review


@pytest.mark.parametrize("call_limit", [45, 120])
def test_long_workflow_budget_keeps_each_provider_call_bounded(call_limit):
    source, generator, reviewer, _ = fixture_ports()
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer,
                                 enabled=True, max_seconds=300, clock=lambda: 0,
                                 max_call_seconds=call_limit)
    assert result.reason == "REVIEWED_NARRATIVE"
    assert generator.generate.call_args.kwargs["max_seconds"] == call_limit
    assert reviewer.review.call_args.kwargs["max_seconds"] == call_limit


@pytest.mark.parametrize("seconds", [True, 0, -1, 601, float("inf"), float("nan")])
def test_invalid_workflow_deadline_never_calls_provider(seconds):
    source, generator, reviewer, _ = fixture_ports()
    with pytest.raises(ValueError, match="INVALID_NARRATIVE_WORKFLOW_BUDGET"):
        synthesize_narrative(source, generator=generator, reviewer=reviewer,
                             enabled=True, max_seconds=seconds)
    generator.generate.assert_not_called()
    reviewer.review.assert_not_called()


def test_generation_and_review_usage_are_added_before_release():
    source, generator, reviewer, _ = fixture_ports()
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True)
    assert result.text and result.total_tokens == 270 and result.usage_complete
    assert (result.generation_calls, result.reviewer_calls) == (1, 1)
    assert result.generated.buffered.plan.claims
    assert result.review is not None
    assert "".join(verified_narrative_outcome_chunks(source, result, chunk_size=7)) == result.text


def test_review_output_budget_is_independent_but_global_ceiling_is_preserved():
    source, generator, reviewer, _ = fixture_ports()
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True,
                                 max_output_tokens=512, max_review_output_tokens=2048,
                                 max_total_tokens=1000)
    assert result.reason == "REVIEWED_NARRATIVE"
    assert generator.generate.call_args.kwargs["max_tokens"] == 512
    assert reviewer.review.call_args.kwargs["max_tokens"] == 850


@pytest.mark.parametrize("limit", [True, 0, -1, 4097, 1.5])
def test_invalid_review_output_budget_never_calls_provider(limit):
    source, generator, reviewer, _ = fixture_ports()
    with pytest.raises(ValueError, match="INVALID_NARRATIVE_WORKFLOW_BUDGET"):
        synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True,
                             max_review_output_tokens=limit)
    generator.generate.assert_not_called()
    reviewer.review.assert_not_called()


@pytest.mark.parametrize("phase", ["generation", "review"])
@pytest.mark.parametrize("budget", [200, 8192])
def test_accounted_failure_retains_usage_without_retry_or_release(phase, budget):
    source, generator, reviewer, _ = fixture_ports()
    error = AccountedCompletionFailure("TRUNCATED", FailedCompletionUsage(100, 100, 200))
    if phase == "generation":
        generator.generate.side_effect = error
        expected = 200
    else:
        reviewer.review.side_effect = error
        expected = 350
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer,
                                 enabled=True, max_total_tokens=budget)
    assert result.total_tokens == expected and result.usage_complete
    assert result.text is None
    assert result.reason == ("TOKEN_BUDGET_EXHAUSTED" if expected > budget
                             else f"{phase.upper()}_FAILED_ACCOUNTED")
    assert generator.generate.call_count == 1
    assert reviewer.review.call_count == (phase == "review")
    with pytest.raises(ValueError):
        list(verified_narrative_outcome_chunks(source, result))


@pytest.mark.parametrize("values", [(True, 1, 2), (-1, 2, 1), (1, 1, 3), (0, 0, 0)])
def test_failed_usage_receipt_rejects_invalid_accounting(values):
    with pytest.raises(ValueError):
        FailedCompletionUsage(*values)


def test_phase_latency_is_separate_from_deadline_clock():
    source, generator, reviewer, _ = fixture_ports()
    ticks = iter([0, 1, 4, 5, 10, 12])
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer,
                                 enabled=True, clock=lambda: 0, timing_clock=lambda: next(ticks))
    assert result.reason == "REVIEWED_NARRATIVE"
    assert result.generation_seconds == 3
    assert result.review_seconds == 5
    assert result.workflow_seconds == 12


def test_failed_review_retains_latency_without_claiming_complete_usage():
    source, generator, reviewer, _ = fixture_ports()
    reviewer.review.side_effect = TimeoutError("private failure")
    ticks = iter([0, 1, 4, 5, 10, 12])
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer,
                                 enabled=True, clock=lambda: 0, timing_clock=lambda: next(ticks))
    assert result.reason == "REVIEW_FAILED"
    assert result.text is None and not result.usage_complete
    assert result.generation_seconds == 3
    assert result.review_seconds == 5
    assert result.workflow_seconds == 12


@pytest.mark.parametrize("retain", [False, True])
def test_preflight_failure_is_accounted_and_private_candidate_cannot_release(retain):
    source, generator, reviewer, _ = fixture_ports()
    reviewer.review.side_effect = ProviderPreflightFailure("SEMANTIC_INPUT_BUDGET_EXCEEDED", 17000)
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True,
                                 retain_diagnostic_candidate=retain)
    assert result.reason == "REVIEW_FAILED_PREFLIGHT"
    assert result.total_tokens == 150 and result.usage_complete
    assert result.text is None
    assert (result.generated is not None) is retain
    assert generator.generate.call_count == reviewer.review.call_count == 1
    with pytest.raises(ValueError):
        list(verified_narrative_outcome_chunks(source, result))


@pytest.mark.parametrize("mutation", ["text", "citations", "review", "missing_receipt", "calls"])
def test_mutated_narrative_outcome_releases_no_chunks(mutation):
    source, generator, reviewer, _ = fixture_ports()
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True)
    if mutation == "text":
        result = replace(result, text=result.text + " Additional unsupported assertion.")
    elif mutation == "citations":
        result = replace(result, generated=replace(result.generated, buffered=replace(
            result.generated.buffered, citation_evidence_ids=("wrong-source",))))
    elif mutation == "review":
        result = replace(result, review=replace(result.review, input_digest="0" * 64))
    elif mutation == "usage":
        result = replace(result, usage_complete=False)
    elif mutation == "tokens":
        result = replace(result, total_tokens=1)
    elif mutation == "calls":
        result = replace(result, reviewer_calls=0)
    else:
        result = replace(result, generated=None)
    received = []
    with pytest.raises(ValueError):
        for chunk in verified_narrative_outcome_chunks(source, result):
            received.append(chunk)
    assert received == []


def test_unsupported_review_can_trigger_only_one_budgeted_revision():
    source, generator, reviewer, review = fixture_ports()
    failed = replace(review, claims=tuple(replace(claim, verdict=EntailmentVerdict.UNSUPPORTED) for claim in review.claims))
    reviewer.review.side_effect = [failed, review]
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True)
    assert result.text and result.total_tokens == 540 and result.generation_calls == 2
    assert generator.generate.call_args.kwargs["feedback_codes"] == ("SEMANTIC_REVIEW_NOT_SUPPORTED",)


@pytest.mark.parametrize("failure", [TimeoutError(), ValueError()])
def test_unknown_usage_never_retries_or_exposes_draft(failure):
    source, generator, reviewer, _ = fixture_ports()
    reviewer.review.side_effect = failure
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True)
    assert result.text is None and not result.usage_complete
    assert generator.generate.call_count == reviewer.review.call_count == 1


def test_budget_exhaustion_and_default_disable_do_not_call_reviewer():
    source, generator, reviewer, _ = fixture_ports()
    assert synthesize_narrative(source, generator=generator, reviewer=reviewer).reason == "DISABLED"
    generator.generate.assert_not_called()
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True, max_total_tokens=150)
    assert result.text is None and result.total_tokens == 150
    reviewer.review.assert_not_called()


def test_revision_limit_rejects_every_failed_draft():
    source, generator, reviewer, review = fixture_ports()
    reviewer.review.return_value = replace(review, claims=tuple(
        replace(claim, verdict=EntailmentVerdict.UNSUPPORTED) for claim in review.claims))
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True)
    assert result.reason == "REVISION_LIMIT" and result.text is None
    assert result.total_tokens == 540
    assert generator.generate.call_count == reviewer.review.call_count == 2


def test_global_deadline_blocks_release_of_late_supported_answer():
    source, generator, reviewer, _ = fixture_ports()
    clock = Mock(side_effect=[0, 0, 1, 121])
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True, clock=clock)
    assert result.reason == "DEADLINE_EXHAUSTED" and result.text is None
    assert result.total_tokens == 270
