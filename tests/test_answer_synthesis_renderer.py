from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from core.answer_synthesis_contracts import AnswerType, VerificationFailure
from core.answer_synthesis_planner import DeterministicAnswerPlanner
from core.answer_synthesis_renderer import NumericPresentation, RestrictedAnswerRenderer, RestrictedOutputVerifier
from tests.test_answer_synthesis_planner import evidence, source


def ready_input(*items, locale="zh-CN", answer_type=AnswerType.FACT):
    return replace(
        source(*(items or (evidence(),)), answer_type=answer_type),
        locale=locale,
        required_dimensions={"metric": "total_assets", "scope": "CONSOLIDATED"},
    )


@pytest.mark.parametrize("name,valid", [("贵州茅台", True), ("Microsoft", False), ("贵州茅台\n", False)])
def test_company_display_does_not_change_or_spoof_identity(name, valid):
    item = evidence()
    item = replace(item, company="moutai", provenance={**item.provenance, "company_name_zh": name})
    incoming = ready_input(item)
    plan = DeterministicAnswerPlanner().plan(incoming)
    if not valid:
        with pytest.raises(ValueError):
            RestrictedAnswerRenderer().render(incoming, plan)
        return
    rendered = RestrictedAnswerRenderer().render(incoming, plan)
    assert "贵州茅台" in rendered.text
    assert plan.claims[0].observation["company"] == "moutai"
    english = replace(incoming, locale="en")
    assert "moutai" in RestrictedAnswerRenderer().render(english, plan).text


def test_chinese_decimal_conversion_is_auditable():
    amount = Decimal("51690610946.50")
    presentation = NumericPresentation.build(amount, currency="CNY", unit="CNY_YUAN", locale="zh-CN")
    assert presentation.original_value == amount
    assert presentation.divisor == Decimal("100000000")
    assert presentation.displayed_value == Decimal("516.91")
    assert presentation.rounded
    assert presentation.text == "约人民币 516.91 亿元"


@pytest.mark.parametrize("name,valid", [("Kweichow Moutai", True), ("Apple", False), ("Kweichow Moutai [2]", False)])
def test_english_company_projection_is_identity_checked(name, valid):
    item = evidence()
    item = replace(item, company="moutai", provenance={**item.provenance, "company_name_en": name})
    incoming = ready_input(item, locale="en")
    plan = DeterministicAnswerPlanner().plan(incoming)
    if not valid:
        with pytest.raises(ValueError):
            RestrictedAnswerRenderer().render(incoming, plan)
    else:
        assert "Kweichow Moutai" in RestrictedAnswerRenderer().render(incoming, plan).text
        assert plan.claims[0].observation["company"] == "moutai"


def test_english_uses_english_number_and_currency_format():
    presentation = NumericPresentation.build(Decimal("51690610946.50"), currency="CNY", unit="CNY_YUAN", locale="en")
    assert presentation.text == "approximately 51.69 billion CNY"
    assert "亿" not in presentation.text


@pytest.mark.parametrize(
    "amount,expected",
    [
        ("0", "人民币 0 元"),
        ("1234.56", "人民币 1,234.56 元"),
        ("-100000000", "人民币 -1.00 亿元"),
        ("0.00001", "人民币 0.00001 元"),
    ],
)
def test_no_loss_of_small_zero_or_negative_values(amount, expected):
    rendered = NumericPresentation.build(Decimal(amount), currency="CNY", unit="CNY_YUAN", locale="zh-CN")
    assert rendered.text == expected
    assert not rendered.rounded


def test_presentation_does_not_depend_on_ambient_decimal_precision():
    with localcontext() as context:
        context.prec = 3
        rendered = NumericPresentation.build(Decimal("51690610946.50"), currency="CNY", unit="CNY_YUAN", locale="zh-CN")
    assert rendered.displayed_value == Decimal("516.91")


def test_display_threshold_does_not_round_up_under_low_ambient_precision():
    with localcontext() as context:
        context.prec = 3
        rendered = NumericPresentation.build(Decimal("99999999.99"), currency="CNY", unit="CNY_YUAN", locale="zh-CN")
    assert rendered.divisor == 1
    assert rendered.text == "人民币 99,999,999.99 元"


@pytest.mark.parametrize(
    "value,currency,unit,locale",
    [
        (1.23, "CNY", "CNY_YUAN", "zh-CN"),
        (Decimal("NaN"), "CNY", "CNY_YUAN", "zh-CN"),
        (Decimal(1), "USD", "CNY_YUAN", "en"),
        (Decimal(1), "CNY", "CNY_MILLION", "zh-CN"),
        (Decimal(1), "EUR", "EUR_UNIT", "en"),
        (Decimal(1), "CNY", "CNY_YUAN", "zh-TW"),
    ],
)
def test_unsupported_or_ambiguous_numeric_presentation_is_rejected(value, currency, unit, locale):
    with pytest.raises(ValueError):
        NumericPresentation.build(value, currency=currency, unit=unit, locale=locale)


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_template_output_preserves_scope_period_metric_and_citation(locale):
    incoming = ready_input(locale=locale)
    plan = DeterministicAnswerPlanner().plan(incoming)
    rendered = RestrictedAnswerRenderer().render(incoming, plan)
    assert "2025-12-31" in rendered.text and "[1]" in rendered.text
    assert rendered.citation_evidence_ids == ("e1",)
    assert rendered.presentations[0].original_value == Decimal("123.45")
    assert RestrictedOutputVerifier().verify(incoming, plan, rendered).passed


@pytest.mark.parametrize("extra", [" Sales expenses caused declining profit.", " 总负债为0。", " [999]"])
def test_any_new_statement_or_citation_is_rejected(extra):
    incoming = ready_input()
    plan = DeterministicAnswerPlanner().plan(incoming)
    rendered = RestrictedAnswerRenderer().render(incoming, plan)
    checked = RestrictedOutputVerifier().verify(incoming, plan, replace(rendered, text=rendered.text + extra))
    assert not checked.passed
    assert VerificationFailure.UNSUPPORTED_CLAIM in checked.failures


def test_renderer_cannot_be_used_to_bypass_unverified_or_wrong_query_plan():
    incoming = source(evidence())
    plan = DeterministicAnswerPlanner().plan(incoming)
    with pytest.raises(ValueError):
        RestrictedAnswerRenderer().render(incoming, plan)
    incoming = ready_input(answer_type=AnswerType.CAUSAL_ANALYSIS)
    plan = DeterministicAnswerPlanner().plan(incoming)
    with pytest.raises(ValueError):
        RestrictedAnswerRenderer().render(incoming, plan)


def test_citation_identity_or_value_mutation_is_rejected():
    incoming = ready_input()
    plan = DeterministicAnswerPlanner().plan(incoming)
    rendered = RestrictedAnswerRenderer().render(incoming, plan)
    swapped = replace(rendered, citation_evidence_ids=("wrong-source",))
    assert (
        VerificationFailure.CITATION_WRONG_SOURCE in RestrictedOutputVerifier().verify(incoming, plan, swapped).failures
    )
    altered = replace(rendered, presentations=(replace(rendered.presentations[0], original_value=Decimal(999)),))
    assert VerificationFailure.NUMERIC_MUTATION in RestrictedOutputVerifier().verify(incoming, plan, altered).failures


def test_comparison_with_incompatible_scopes_is_not_rendered_as_a_comparison():
    incoming = replace(
        ready_input(evidence(), evidence("e2", scope="PARENT_COMPANY"), answer_type=AnswerType.COMPARISON),
        required_dimensions={"metric": "total_assets"},
    )
    plan = DeterministicAnswerPlanner().plan(incoming)
    with pytest.raises(ValueError):
        RestrictedAnswerRenderer().render(incoming, plan)
