from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from core.answer_synthesis_analysis import AnalyticalAnswerRenderer, audited_difference
from core.answer_synthesis_contracts import AnswerType
from core.answer_synthesis_planner import DeterministicAnswerPlanner
from core.answer_synthesis_workflow import BoundedSynthesisWorkflow
from tests.test_answer_synthesis_planner import evidence
from tests.test_answer_synthesis_renderer import ready_input


def incoming(first="100", second="120", end="2025-12-31"):
    source = ready_input(evidence("old", end="2024-12-31", value=first),
                         evidence("new", end=end, value=second), answer_type=AnswerType.TREND)
    return source, DeterministicAnswerPlanner().plan(source)


def test_decimal_change_and_bilingual_audit_are_identical():
    source, plan = incoming("123.45", "130")
    with localcontext() as context:
        context.prec = 3
        answer = AnalyticalAnswerRenderer().render(source, plan)
    assert answer.audit.difference == Decimal("6.55")
    assert answer.audit.percentage_display == Decimal("5.31")
    assert answer.audit.percentage_rounded
    english = AnalyticalAnswerRenderer().render(replace(source, locale="en"), plan)
    assert english.audit == answer.audit
    assert "5.31%" in english.text and "[1] [2]" in answer.text
    assert not AnalyticalAnswerRenderer().verify(source, plan, replace(answer, text=answer.text + " unsupported"))


@pytest.mark.parametrize("baseline", ["0", "-100"])
def test_nonpositive_baseline_never_produces_growth_percentage(baseline):
    source, plan = incoming(baseline, "20")
    audit = audited_difference(source, plan)
    assert audit.percentage_display is None
    assert audit.percentage_unavailable_reason == "NON_POSITIVE_BASELINE"


@pytest.mark.parametrize("end", ["2026-12-31", "2025-09-30"])
def test_incompatible_years_or_season_end_rejected(end):
    source, plan = incoming(end=end)
    with pytest.raises(ValueError, match="NOT_COMPARABLE"):
        audited_difference(source, plan)


def test_cross_company_comparison_requires_explicit_accounting_basis():
    first = evidence("a", value="100")
    second = evidence("b", value="120", company="Hypothetical peer")
    source = ready_input(first, second, answer_type=AnswerType.COMPARISON)
    plan = DeterministicAnswerPlanner().plan(source)
    with pytest.raises(ValueError, match="ACCOUNTING_STANDARD_NOT_ALIGNED"):
        audited_difference(source, plan)
    items = [replace(item, provenance={**item.provenance, "accounting_standard": "CAS",
                                       "accounting_standard_source": "explicit fixture source"})
             for item in (first, second)]
    source = ready_input(*items, answer_type=AnswerType.COMPARISON)
    plan = DeterministicAnswerPlanner().plan(source)
    answer = AnalyticalAnswerRenderer().render(source, plan)
    assert answer.audit.difference == Decimal("20")
    assert "差额占第一项的比例" in answer.text


def test_difference_preserves_widely_separated_decimal_positions():
    source, plan = incoming("1E100", "1E-100")
    with localcontext() as context:
        context.prec = 250
        expected = Decimal("1E-100") - Decimal("1E100")
    assert audited_difference(source, plan).difference == expected


def test_workflow_analysis_is_explicit_and_never_calls_fact_generator():
    source, plan = incoming()
    class ForbiddenGenerator:
        def generate(self, request):
            pytest.fail("Derived calculations must not be rewritten by unchecked generation")
    workflow = BoundedSynthesisWorkflow()
    original = workflow.run(source, plan)
    assert original.mode == "TEMPLATE"
    outcome = workflow.run(source, plan, analysis_enabled=True, enabled=True, generator=ForbiddenGenerator())
    assert outcome.mode == "VERIFIED_ANALYSIS"
    assert outcome.generation_calls == outcome.revisions_attempted == outcome.total_tokens == 0
    assert outcome.answer.audit.percentage_display == Decimal("20.00")


def test_workflow_rejects_invalid_analysis_before_generator():
    source, plan = incoming(end="2026-12-31")
    with pytest.raises(ValueError, match="NOT_COMPARABLE"):
        BoundedSynthesisWorkflow().run(source, plan, analysis_enabled=True)
