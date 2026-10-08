"""Opt-in bounded review execution; never releases partial or unreviewed text."""

import time
from dataclasses import replace

from core.answer_synthesis_budget import NarrativeTimeBudget
from core.answer_synthesis_review_batches import plan_narrative_review_batches
from core.answer_synthesis_semantic import (
    EntailmentVerdict,
    SemanticClaimReview,
    SemanticReview,
    semantic_input_digest,
)
from core.answer_synthesis_usage import (
    AccountedCompletionFailure,
    FailedCompletionUsage,
    ReviewBatchPreflightFailure,
)
from llm.providers.provider_exceptions import StructuredOutputError


class BatchedNarrativeReviewer:
    """Caller supplies a separately authorized reviewer and total-token ceiling.

    Request bytes plus a 2,048-token envelope are conservative admission reserves,
    not measured token usage. Actual successful/failed completions are accounted
    separately. This adapter cannot enable a Provider or raise workflow budgets.
    """

    def __init__(self, reviewer, *, max_total_tokens, clock=time.monotonic):
        if type(max_total_tokens) is not int or not 1 <= max_total_tokens <= 65536:
            raise ValueError("INVALID_BATCH_REVIEW_TOKEN_LIMIT")
        self.reviewer = reviewer
        self.max_total_tokens = max_total_tokens
        self.clock = clock
        self.receipts = []

    def review(self, source, plan, draft, *, max_seconds=60, max_tokens=1024, max_total_tokens=None):
        policy = NarrativeTimeBudget(total_seconds=max_seconds)
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ValueError("INVALID_BATCH_REVIEW_OUTPUT_LIMIT")
        if max_total_tokens is not None and (type(max_total_tokens) is not int or max_total_tokens <= 0):
            raise ValueError("INVALID_BATCH_REVIEW_TOKEN_LIMIT")
        token_ceiling = min(self.max_total_tokens, max_total_tokens or self.max_total_tokens)
        deadline = self.clock() + max_seconds
        try:
            batches = plan_narrative_review_batches(source, plan, draft)
        except ValueError as error:
            if str(error) in {"REVIEW_SINGLE_CLAIM_EXCEEDS_INPUT_BUDGET", "REVIEW_BATCH_LIMIT_EXCEEDED",
                              "REVIEW_DRAFT_PROJECTION_CHANGED"}:
                self.receipts.append({"phase": "admission", "provider_attempts": 0, "code": str(error)})
                raise ReviewBatchPreflightFailure(str(error)) from error
            raise
        # Reserve all calls before the first invocation; no surprise paid calls.
        reserve = sum(batch.wire_bytes + 2048 for batch in batches) + max_tokens
        self.receipts.append({"phase": "admission", "batch_count": len(batches),
                              "reserved_tokens_upper_bound": reserve, "provider_attempts": 0})
        if reserve > token_ceiling or max_tokens < len(batches):
            raise ReviewBatchPreflightFailure("BATCH_REVIEW_RESERVATION_EXCEEDED")
        prompt_total = completion_total = 0
        usage_known = True
        reviews = []
        version = None

        def failed(code):
            if prompt_total + completion_total:
                raise AccountedCompletionFailure(code, FailedCompletionUsage(
                    prompt_total, completion_total, prompt_total + completion_total))
            raise ReviewBatchPreflightFailure(code)

        for index, batch in enumerate(batches):
            remaining_seconds = policy.allowance(deadline=deadline, now=self.clock())
            if remaining_seconds <= 0:
                failed("BATCH_REVIEW_DEADLINE_EXHAUSTED")
            remaining_outputs = max_tokens - completion_total
            output_limit = remaining_outputs // (len(batches) - index)
            remaining_reserve = sum(item.wire_bytes + 2048 for item in batches[index:]) + remaining_outputs
            if prompt_total + completion_total + remaining_reserve > token_ceiling:
                failed("BATCH_REVIEW_RESERVATION_EXCEEDED")
            try:
                review = self.reviewer.review(source, batch.plan, batch.draft,
                    max_seconds=remaining_seconds, max_tokens=output_limit)
            except AccountedCompletionFailure as error:
                prompt_total += error.usage.prompt_tokens
                completion_total += error.usage.completion_tokens
                failed("BATCH_REVIEW_FAILED_ACCOUNTED")
            except Exception:
                self.receipts.append({"batch_index": index, "usage_complete": False,
                    "known_prompt_tokens": prompt_total, "known_completion_tokens": completion_total})
                raise
            if not isinstance(review, SemanticReview):
                raise StructuredOutputError("BATCH_REVIEW_INVALID_STRUCTURED_OUTPUT")
            usage = (review.prompt_tokens, review.completion_tokens, review.total_tokens)
            valid_usage = (all(type(value) is int and value >= 0 for value in usage)
                           and usage[0] + usage[1] == usage[2])
            usage_known = usage_known and valid_usage
            if valid_usage:
                prompt_total += usage[0]
                completion_total += usage[1]
            self.receipts.append({"batch_index": index, "usage_complete": valid_usage,
                "prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": usage[2]})
            if ((valid_usage and usage[1] > output_limit) or prompt_total + completion_total > token_ceiling
                    or self.clock() >= deadline):
                failed("BATCH_REVIEW_BUDGET_EXHAUSTED")
            expected = batch.plan.claims
            if (not isinstance(review, SemanticReview)
                    or review.input_digest != semantic_input_digest(source, batch.plan, batch.draft)
                    or not isinstance(review.reviewer_version, str) or not review.reviewer_version.strip()
                    or (version is not None and review.reviewer_version != version)
                    or not isinstance(review.claims, tuple)
                    or len(review.claims) != len(expected)):
                failed("BATCH_REVIEW_CONTRACT_CHANGED")
            for claim, result in zip(expected, review.claims, strict=True):
                if (not isinstance(result, SemanticClaimReview)
                        or result.claim_id != claim.claim_id or result.evidence_ids != claim.evidence_ids
                        or not isinstance(result.verdict, EntailmentVerdict)
                        or result.causal_strength != claim.causal_strength
                        or not isinstance(result.rationale, str) or not result.rationale.strip()):
                    failed("BATCH_REVIEW_CLAIM_CHANGED")
            version = review.reviewer_version
            reviews.extend(review.claims)
        # Digest covers the original FULL draft/source, not just the last batch.
        return replace(SemanticReview(version, tuple(reviews), semantic_input_digest(source, plan, draft)),
                       prompt_tokens=prompt_total if usage_known else None,
                       completion_tokens=completion_total if usage_known else None,
                       total_tokens=prompt_total + completion_total if usage_known else None)
