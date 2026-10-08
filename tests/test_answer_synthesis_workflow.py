from dataclasses import replace

import pytest

from core.answer_synthesis_contracts import RevisionPolicy
from core.answer_synthesis_planner import DeterministicAnswerPlanner
from core.answer_synthesis_renderer import RestrictedAnswerRenderer
from core.answer_synthesis_workflow import (
    BoundedSynthesisWorkflow,
    DraftCandidate,
    SynthesisBudget,
)
from tests.test_answer_synthesis_renderer import ready_input


class Generator:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response(request) if callable(response) else response


def inputs():
    source = ready_input()
    return source, DeterministicAnswerPlanner().plan(source)


def test_default_disabled_spends_no_tokens_or_calls():
    source, plan = inputs()
    generator = Generator([])
    result = BoundedSynthesisWorkflow().run(source, plan, generator=generator)
    assert result.mode == "TEMPLATE"
    assert result.generation_calls == result.total_tokens == 0
    assert not generator.requests


def test_valid_template_candidate_is_checked_before_release():
    source, plan = inputs()
    generator = Generator([lambda request: DraftCandidate(request.locked_rendering.text, 10)])
    result = BoundedSynthesisWorkflow().run(source, plan, enabled=True, generator=generator)
    assert result.mode == "VERIFIED_TEMPLATE" and result.generation_calls == 1
    assert result.answer.citation_evidence_ids == ("e1",)


def test_revision_gets_failure_codes_not_unsafe_draft_then_can_succeed():
    source, plan = inputs()
    generator = Generator(
        [
            DraftCandidate("profit fell because of expenses", 20),
            lambda request: DraftCandidate(request.locked_rendering.text, 10),
        ]
    )
    result = BoundedSynthesisWorkflow().run(source, plan, enabled=True, generator=generator)
    assert result.mode == "VERIFIED_TEMPLATE" and result.revisions_attempted == 1
    assert "UNSUPPORTED_CLAIM" in generator.requests[1].feedback_codes
    assert "OVERCLAIMED_CAUSALITY" in generator.requests[1].feedback_codes
    assert generator.requests[1].remaining_total_tokens == 4096 - 20
    assert "profit fell" not in repr(result)


@pytest.mark.parametrize("revisions", [0, 1, 2])
def test_repeated_failure_is_bounded_and_unsafe_text_never_exposed(revisions):
    source, plan = inputs()
    generator = Generator([DraftCandidate("unsafe 999 [999]", 10)] * 10)
    result = BoundedSynthesisWorkflow().run(
        source,
        plan,
        enabled=True,
        generator=generator,
        budget=SynthesisBudget(revision_policy=RevisionPolicy(revisions)),
    )
    assert result.mode == "SAFE_FALLBACK"
    assert len(generator.requests) == revisions + 1
    assert result.answer == RestrictedAnswerRenderer().render(source, plan)
    assert "unsafe" not in repr(result)


def test_token_budget_exhaustion_stops_revision():
    source, plan = inputs()
    generator = Generator([DraftCandidate("unsafe", 50)])
    result = BoundedSynthesisWorkflow().run(
        source,
        plan,
        enabled=True,
        generator=generator,
        budget=SynthesisBudget(max_total_tokens=50, max_output_tokens=25),
    )
    assert result.mode == "SAFE_FALLBACK" and len(generator.requests) == 1
    assert result.reason == "token_budget_exhausted"


def test_over_budget_candidate_is_not_released_even_when_text_matches():
    source, plan = inputs()
    generator = Generator([lambda request: DraftCandidate(request.locked_rendering.text, 101)])
    result = BoundedSynthesisWorkflow().run(
        source,
        plan,
        enabled=True,
        generator=generator,
        budget=SynthesisBudget(max_total_tokens=100, max_output_tokens=50),
    )
    assert result.mode == "SAFE_FALLBACK" and result.reason == "token_budget_exceeded"


def test_deadline_passed_to_adapter_and_late_result_discarded():
    source, plan = inputs()
    clock = [100.0]

    def late(request):
        assert request.deadline == 101.0
        clock[0] = 102.0
        return DraftCandidate(request.locked_rendering.text, 10)

    result = BoundedSynthesisWorkflow(clock=lambda: clock[0]).run(
        source, plan, enabled=True, generator=Generator([late]), budget=SynthesisBudget(max_seconds=1)
    )
    assert result.mode == "SAFE_FALLBACK" and result.reason == "deadline_exhausted"


def test_adapter_error_does_not_retry_with_unknown_cost_or_leak_exception():
    source, plan = inputs()
    generator = Generator([RuntimeError("API_KEY=private")])
    result = BoundedSynthesisWorkflow().run(source, plan, enabled=True, generator=generator)
    assert len(generator.requests) == 1 and result.reason == "generation_error"
    assert "private" not in repr(result)


@pytest.mark.parametrize("usage", [None, True, 1.5, -1])
def test_invalid_usage_does_not_grant_more_revision_budget(usage):
    source, plan = inputs()
    generator = Generator([DraftCandidate("unsafe", usage)])
    result = BoundedSynthesisWorkflow().run(source, plan, enabled=True, generator=generator)
    assert result.reason == "verification_failed_usage_unavailable_no_revision" and len(generator.requests) == 1


def test_no_generation_without_a_verified_fallback():
    source, plan = inputs()
    source = replace(source, required_dimensions={"metric": "total_debt"})
    generator = Generator([])
    with pytest.raises(ValueError):
        BoundedSynthesisWorkflow().run(source, plan, enabled=True, generator=generator)
    assert not generator.requests


@pytest.mark.parametrize(
    "parameters",
    [
        {"max_total_tokens": True},
        {"max_output_tokens": 0},
        {"max_seconds": float("nan")},
        {"max_seconds": float("inf")},
        {"max_seconds": 121},
        {"max_total_tokens": 10, "max_output_tokens": 11},
    ],
)
def test_invalid_budget_rejected(parameters):
    with pytest.raises(ValueError):
        SynthesisBudget(**parameters)
