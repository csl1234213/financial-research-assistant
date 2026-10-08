"""Bounded generation/revision runner with closed factual grammar and safe fallback."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Protocol

from core.answer_synthesis_analysis import AnalyticalAnswer, AnalyticalAnswerRenderer
from core.answer_synthesis_contracts import AnswerPlan, AnswerType, RevisionPolicy, SynthesisInput
from core.answer_synthesis_draft_verifier import ControlledFactDraftVerifier
from core.answer_synthesis_renderer import RenderedAnswer, RestrictedAnswerRenderer, RestrictedOutputVerifier
from llm.providers.provider_exceptions import ProviderTimeoutError, StructuredOutputError


@dataclass(frozen=True)
class SynthesisBudget:
    revision_policy: RevisionPolicy = field(default_factory=RevisionPolicy)
    max_total_tokens: int = 4096
    max_output_tokens: int = 512
    max_seconds: float = 30.0

    def __post_init__(self):
        if not isinstance(self.revision_policy, RevisionPolicy):
            raise ValueError("explicit revision policy required")
        for value in (self.max_total_tokens, self.max_output_tokens):
            if type(value) is not int or not 1 <= value <= 16384:
                raise ValueError("bounded positive integer token budget required")
        if self.max_output_tokens > self.max_total_tokens:
            raise ValueError("output token limit exceeds total budget")
        if isinstance(self.max_seconds, bool) or not math.isfinite(self.max_seconds) or not 0 < self.max_seconds <= 120:
            raise ValueError("deadline must be finite and at most 120 seconds")


@dataclass(frozen=True)
class DraftRequest:
    source: SynthesisInput
    plan: AnswerPlan
    locked_rendering: RenderedAnswer
    revision: int
    feedback_codes: tuple[str, ...]
    remaining_total_tokens: int
    max_output_tokens: int
    deadline: float


@dataclass(frozen=True)
class DraftCandidate:
    text: str
    total_tokens: int | None


class DraftGenerator(Protocol):
    """Adapter must enforce deadline/limits and report actual input + output tokens.

    This port does not grant provider authorization. A future adapter must check
    the existing provider policy and include hidden retries in accounting.
    """

    def generate(self, request: DraftRequest) -> DraftCandidate: ...


@dataclass(frozen=True)
class SynthesisOutcome:
    answer: RenderedAnswer | AnalyticalAnswer
    mode: str
    reason: str
    generation_calls: int
    revisions_attempted: int
    total_tokens: int | None
    last_failure_codes: tuple[str, ...] = ()


class BoundedSynthesisWorkflow:
    """Never exposes failed drafts; only source-locked templates/factual grammar can pass."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock

    def run(
        self,
        source: SynthesisInput,
        plan: AnswerPlan,
        *,
        generator: DraftGenerator | None = None,
        enabled: bool = False,
        budget: SynthesisBudget | None = None,
        analysis_enabled: bool = False,
    ) -> SynthesisOutcome:
        policy = budget or SynthesisBudget()
        if analysis_enabled is True and source.answer_type in {AnswerType.COMPARISON, AnswerType.TREND}:
            renderer = AnalyticalAnswerRenderer()
            analytical = renderer.render(source, plan)
            if not AnalyticalAnswerRenderer().verify(source, plan, analytical):
                raise ValueError("verified analytical answer unavailable")
            # Formula-derived statements do not go through the single-fact draft
            # grammar. No unverified model paraphrase is released in this mode.
            return SynthesisOutcome(analytical, "VERIFIED_ANALYSIS", "deterministic_analysis_only", 0, 0, 0)
        # Before spending any tokens, establish a verified fallback. Invalid
        # plans are rejected; no guessed empty or optimistic answer is created.
        fallback = RestrictedAnswerRenderer().render(source, plan)
        verifier = RestrictedOutputVerifier()
        if not verifier.verify(source, plan, fallback).passed:
            raise ValueError("verified fallback unavailable")
        if source.answer_type == AnswerType.AMBIGUOUS:
            # Clarification is not a factual generation request. Do not spend
            # model tokens or paraphrase it into an unrequested financial answer.
            return SynthesisOutcome(fallback, "CLARIFICATION", "query_interpretation_required", 0, 0, 0)
        if enabled is not True or generator is None:
            return SynthesisOutcome(fallback, "TEMPLATE", "generation_disabled", 0, 0, 0)
        deadline = self._clock() + policy.max_seconds
        calls, total, feedback = 0, 0, ()
        reason = "revision_limit"
        for revision in range(policy.revision_policy.max_revisions + 1):
            remaining = policy.max_total_tokens - total if total is not None else policy.max_total_tokens
            if self._clock() >= deadline:
                reason = "deadline_exhausted"
                break
            if remaining <= 0:
                reason = "token_budget_exhausted"
                break
            request = DraftRequest(
                source,
                plan,
                fallback,
                revision,
                feedback,
                remaining,
                min(policy.max_output_tokens, remaining),
                deadline,
            )
            calls += 1
            try:
                candidate = generator.generate(request)
            except ProviderTimeoutError:
                reason = "generation_timeout"
                break
            except StructuredOutputError:
                reason = "structured_output_error"
                break
            except Exception:
                # Adapter errors may represent a billed failed call. Do not
                # retry with unknown usage or leak exception strings/drafts.
                reason = "generation_error"
                break
            if (
                not isinstance(candidate, DraftCandidate)
                or not isinstance(candidate.text, str)
            ):
                reason = "invalid_usage_or_response"
                break
            known = type(candidate.total_tokens) is int and candidate.total_tokens >= 0
            total = total + candidate.total_tokens if known and total is not None else None
            if total is not None and total > policy.max_total_tokens:
                reason = "token_budget_exceeded"
                break
            if self._clock() >= deadline:
                reason = "deadline_exhausted"
                break
            if not candidate.text.strip() or len(candidate.text) > 65536:
                feedback = ("UNSUPPORTED_CLAIM",)
                continue
            rendered = replace(
                fallback,
                text=candidate.text,
                template_version=fallback.template_version
                if candidate.text == fallback.text
                else "p2.2.fact-grammar.v1",
            )
            checked = ControlledFactDraftVerifier().verify(source, plan, candidate.text)
            feedback = tuple(failure.value for failure in checked.failures)
            if checked.passed and set(checked.reviewed_claim_ids) == {claim.claim_id for claim in plan.claims}:
                exact = candidate.text == fallback.text
                return SynthesisOutcome(
                    rendered,
                    "VERIFIED_TEMPLATE" if exact else "VERIFIED_FACT_DRAFT",
                    "restricted_template_only" if exact else "closed_fact_grammar_only",
                    calls,
                    max(0, calls - 1),
                    total,
                )
            if total is None:
                reason = "verification_failed_usage_unavailable_no_revision"
                break
        return SynthesisOutcome(fallback, "SAFE_FALLBACK", reason, calls, max(0, calls - 1), total, feedback)
