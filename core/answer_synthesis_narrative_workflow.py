"""Bounded generation/review/release orchestration with no failed draft output."""

import time
from dataclasses import dataclass

from core.answer_synthesis_batched_reviewer import BatchedNarrativeReviewer
from core.answer_synthesis_budget import NarrativeTimeBudget
from core.answer_synthesis_narrative_ollama import GeneratedNarrative, reviewed_narrative_chunks
from core.answer_synthesis_semantic import SemanticReview, validate_grounded_answer_review
from core.answer_synthesis_usage import (
    AccountedCompletionFailure,
    ProviderPreflightFailure,
    ReviewBatchPreflightFailure,
)
from llm.providers.provider_exceptions import ProviderTimeoutError, StructuredOutputError


@dataclass(frozen=True)
class NarrativeOutcome:
    text: str | None
    reason: str
    generation_calls: int
    reviewer_calls: int
    total_tokens: int | None
    usage_complete: bool
    generated: GeneratedNarrative | None = None
    review: SemanticReview | None = None
    generation_seconds: float = 0
    review_seconds: float = 0
    workflow_seconds: float = 0
    generation_status: str = "SUCCESS"
    usage_status: str = "KNOWN"
    failure_class: str | None = None


def verified_narrative_outcome_chunks(source, outcome, *, chunk_size=128):
    """Revalidate retained claim/citation/review bindings before releasing text.

    A successful workflow label or a text string is not an authorization token.
    This port makes no provider call and never releases a failed candidate.
    """
    if (not isinstance(outcome, NarrativeOutcome) or outcome.reason != "REVIEWED_NARRATIVE"
            or outcome.generated is None or outcome.review is None
            or type(outcome.generation_calls) is not int
            or outcome.generation_calls not in (1, 2)
            or type(outcome.reviewer_calls) is not int
            or outcome.reviewer_calls != outcome.generation_calls):
        raise ValueError("REVIEWED_NARRATIVE_OUTCOME_REQUIRED")
    text = "".join(reviewed_narrative_chunks(source, outcome.generated, outcome.review,
                                            chunk_size=chunk_size))
    if text != outcome.text:
        raise ValueError("NARRATIVE_OUTCOME_TEXT_CHANGED")
    for offset in range(0, len(text), chunk_size):
        yield text[offset:offset + chunk_size]


def _usage(result):
    values = (result.prompt_tokens, result.completion_tokens, result.total_tokens)
    if any(type(value) is not int or value < 0 for value in values) or values[0] + values[1] != values[2]:
        return None
    return values[2]


def synthesize_narrative(source, *, generator, reviewer, enabled=False, max_total_tokens=8192,
                         max_output_tokens=1024, max_seconds=120, max_revisions=1, clock=time.monotonic,
                         max_call_seconds=None, timing_clock=time.perf_counter,
                         max_review_output_tokens=None, retain_diagnostic_candidate=False):
    if enabled is not True:
        return NarrativeOutcome(None, "DISABLED", 0, 0, 0, True)
    if (type(max_total_tokens) is not int or not 1 <= max_total_tokens <= 65536
            or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 4096
            or (max_review_output_tokens is not None
                and (type(max_review_output_tokens) is not int or not 1 <= max_review_output_tokens <= 4096))
            or type(retain_diagnostic_candidate) is not bool
            or type(max_revisions) is not int or not 0 <= max_revisions <= 1):
        raise ValueError("INVALID_NARRATIVE_WORKFLOW_BUDGET")
    try:
        time_budget = NarrativeTimeBudget(total_seconds=max_seconds, per_call_seconds=max_call_seconds)
    except ValueError as exc:
        raise ValueError("INVALID_NARRATIVE_WORKFLOW_BUDGET") from exc
    deadline = clock() + max_seconds
    timing_started = timing_clock()
    generation_seconds = review_seconds = 0.0
    generation_calls = reviewer_calls = total = 0
    feedback = ()
    diagnostic_candidate = None
    generation_status = "NOT_STARTED"
    failure_class = None

    def add_usage(value):
        nonlocal total
        total = total + value if total is not None and value is not None else None

    def available_tokens():
        return max_total_tokens - total if total is not None else max_total_tokens

    def stopped(reason, known=True):
        return NarrativeOutcome(None, reason, generation_calls, reviewer_calls, total, known and total is not None,
            generated=diagnostic_candidate if retain_diagnostic_candidate else None,
            generation_seconds=generation_seconds, review_seconds=review_seconds,
            workflow_seconds=max(0.0, timing_clock() - timing_started),
            generation_status=generation_status,
            usage_status="KNOWN" if known and total is not None else "UNAVAILABLE",
            failure_class=failure_class)

    for _ in range(max_revisions + 1):
        remaining_seconds = time_budget.allowance(deadline=deadline, now=clock())
        if remaining_seconds <= 0:
            return stopped("DEADLINE_EXHAUSTED")
        if total is not None and total >= max_total_tokens:
            return stopped("TOKEN_BUDGET_EXHAUSTED")
        generation_calls += 1
        phase_started = timing_clock()
        try:
            generated = generator.generate(source, max_seconds=remaining_seconds,
                max_tokens=min(max_output_tokens, available_tokens()), feedback_codes=feedback)
            generation_status = "SUCCESS"
            add_usage(_usage(generated))
            diagnostic_candidate = generated
        except ProviderTimeoutError:
            generation_seconds += max(0.0, timing_clock() - phase_started)
            generation_status = failure_class = "TIMEOUT"
            return stopped("GENERATION_TIMEOUT", False)
        except StructuredOutputError:
            generation_seconds += max(0.0, timing_clock() - phase_started)
            generation_status = failure_class = "STRUCTURED_OUTPUT_ERROR"
            return stopped("STRUCTURED_OUTPUT_ERROR", False)
        except AccountedCompletionFailure as exc:
            generation_seconds += max(0.0, timing_clock() - phase_started)
            add_usage(exc.usage.total_tokens)
            failure_class = exc.failure_class
            generation_status = failure_class
            if failure_class == "STRUCTURED_OUTPUT_ERROR":
                return stopped("STRUCTURED_OUTPUT_ERROR")
            return stopped("TOKEN_BUDGET_EXHAUSTED" if total is not None and total > max_total_tokens
                           else "GENERATION_FAILED_ACCOUNTED")
        except Exception:
            generation_seconds += max(0.0, timing_clock() - phase_started)
            # Failed calls may have spent tokens. Never silently record zero
            # usage as complete or retry when actual usage is unavailable.
            generation_status = failure_class = "PROVIDER_ERROR"
            return stopped("GENERATION_FAILED", False)
        generation_seconds += max(0.0, timing_clock() - phase_started)
        if total is not None and total >= max_total_tokens:
            return stopped("TOKEN_BUDGET_EXHAUSTED")
        remaining_seconds = time_budget.allowance(deadline=deadline, now=clock())
        if remaining_seconds <= 0:
            return stopped("DEADLINE_EXHAUSTED")
        reviewer_calls += 1
        phase_started = timing_clock()
        try:
            buffered = generated.buffered
            review_budget = ({"max_total_tokens": available_tokens()}
                             if isinstance(reviewer, BatchedNarrativeReviewer) else {})
            review = reviewer.review(source, buffered.plan, buffered.text, max_seconds=remaining_seconds,
                max_tokens=min(max_output_tokens if max_review_output_tokens is None
                               else max_review_output_tokens, available_tokens()), **review_budget)
            add_usage(_usage(review))
        except ProviderTimeoutError:
            review_seconds += max(0.0, timing_clock() - phase_started)
            failure_class = "TIMEOUT"
            return stopped("REVIEW_TIMEOUT", False)
        except StructuredOutputError:
            review_seconds += max(0.0, timing_clock() - phase_started)
            failure_class = "STRUCTURED_OUTPUT_ERROR"
            return stopped("STRUCTURED_OUTPUT_ERROR", False)
        except (ProviderPreflightFailure, ReviewBatchPreflightFailure):
            review_seconds += max(0.0, timing_clock() - phase_started)
            return stopped("REVIEW_FAILED_PREFLIGHT")
        except AccountedCompletionFailure as exc:
            review_seconds += max(0.0, timing_clock() - phase_started)
            add_usage(exc.usage.total_tokens)
            failure_class = exc.failure_class
            if failure_class == "STRUCTURED_OUTPUT_ERROR":
                return stopped("STRUCTURED_OUTPUT_ERROR")
            return stopped("TOKEN_BUDGET_EXHAUSTED" if total is not None and total > max_total_tokens
                           else "REVIEW_FAILED_ACCOUNTED")
        except Exception:
            review_seconds += max(0.0, timing_clock() - phase_started)
            failure_class = "PROVIDER_ERROR"
            return stopped("REVIEW_FAILED", False)
        review_seconds += max(0.0, timing_clock() - phase_started)
        if total is not None and total > max_total_tokens:
            return stopped("TOKEN_BUDGET_EXHAUSTED")
        if clock() >= deadline:
            return stopped("DEADLINE_EXHAUSTED")
        try:
            supported = validate_grounded_answer_review(source, buffered.plan, review, buffered.text)
        except Exception:
            return stopped("INVALID_REVIEW_CONTRACT")
        if supported:
            try:
                text = "".join(reviewed_narrative_chunks(source, generated, review))
            except Exception:
                return stopped("FINAL_VERIFICATION_FAILED")
            if clock() >= deadline:
                return stopped("DEADLINE_EXHAUSTED")
            return NarrativeOutcome(text, "REVIEWED_NARRATIVE", generation_calls, reviewer_calls,
                                    total, total is not None, generated, review, generation_seconds,
                                    review_seconds, max(0.0, timing_clock() - timing_started),
                                    "SUCCESS", "KNOWN" if total is not None else "UNKNOWN")
        if total is None:
            return stopped("SEMANTIC_REVIEW_NOT_SUPPORTED", False)
        feedback = ("SEMANTIC_REVIEW_NOT_SUPPORTED",)
    return stopped("REVISION_LIMIT")
