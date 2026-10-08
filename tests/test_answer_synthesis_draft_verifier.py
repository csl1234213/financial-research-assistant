import pytest

from core.answer_synthesis_contracts import AnswerType, VerificationFailure
from core.answer_synthesis_draft_verifier import ControlledFactDraftVerifier, factual_sentence_variants
from core.answer_synthesis_planner import DeterministicAnswerPlanner
from core.answer_synthesis_workflow import BoundedSynthesisWorkflow, DraftCandidate
from tests.test_answer_synthesis_planner import evidence
from tests.test_answer_synthesis_renderer import ready_input
from tests.test_answer_synthesis_workflow import Generator


def prepared(locale="zh-CN", **kwargs):
    source = ready_input(locale=locale, **kwargs)
    plan = DeterministicAnswerPlanner().plan(source)
    return source, plan


@pytest.mark.parametrize("locale", ["zh-CN", "en"])
def test_factual_sentence_reordering_is_extractable_without_changing_fields(locale):
    source, plan = prepared(locale)
    variants = factual_sentence_variants(source, plan)[0]
    assert len(variants) > 1
    for text in variants:
        claims = ControlledFactDraftVerifier().extract(source, plan, text)
        assert claims[0].claim_id == plan.claims[0].claim_id
        assert claims[0].evidence_id == "e1"
        assert ControlledFactDraftVerifier().verify(source, plan, text).passed


@pytest.mark.parametrize(
    "old,new",
    [
        ("123.45", "999.45"),
        ("2025-12-31", "2024-12-31"),
        ("贵州茅台", "Tesla"),
        ("合并报表", "母公司报表"),
        ("资产总计", "负债合计"),
        ("人民币", "美元"),
        (" 元", " 亿元"),
        ("为", "不为"),
        ("[1]", "[999]"),
        ("[1]", ""),
    ],
)
def test_semantic_and_numeric_mutations_not_accepted(old, new):
    source, plan = prepared()
    text = factual_sentence_variants(source, plan)[0][1]
    assert old in text
    checked = ControlledFactDraftVerifier().verify(source, plan, text.replace(old, new))
    assert not checked.passed and VerificationFailure.UNSUPPORTED_CLAIM in checked.failures


@pytest.mark.parametrize(
    "addition", ["\n费用增加导致利润下降。", "\n公司增长势头强劲。", " 因为收入增长。", "\n市值为999亿。"]
)
def test_all_unconsumed_claims_fail_including_nonnumeric_narrative(addition):
    source, plan = prepared()
    text = factual_sentence_variants(source, plan)[0][1] + addition
    checked = ControlledFactDraftVerifier().verify(source, plan, text)
    assert not checked.passed


def test_duplicate_claim_does_not_hide_an_omitted_period():
    source = ready_input(evidence(), evidence("e2", "2024-12-31", "100"), answer_type=AnswerType.TREND)
    plan = DeterministicAnswerPlanner().plan(source)
    variants = factual_sentence_variants(source, plan)
    duplicated = "\n\n".join([variants[0][1], variants[0][1]])
    assert not ControlledFactDraftVerifier().verify(source, plan, duplicated).passed
    reversed_order = "\n\n".join([variants[1][1], variants[0][1]])
    assert not ControlledFactDraftVerifier().verify(source, plan, reversed_order).passed


def test_currency_scale_rounding_qualifier_cannot_be_omitted():
    source = ready_input(evidence(value="51690610946.50"))
    plan = DeterministicAnswerPlanner().plan(source)
    text = factual_sentence_variants(source, plan)[0][1]
    assert "约人民币 516.91 亿元" in text
    assert not ControlledFactDraftVerifier().verify(source, plan, text.replace("约人民币", "人民币")).passed


def test_workflow_can_release_verified_fact_paraphrase_without_relaxing_causality_gate():
    source, plan = prepared()
    text = factual_sentence_variants(source, plan)[0][1]
    generator = Generator([DraftCandidate(text, 15)])
    result = BoundedSynthesisWorkflow().run(source, plan, generator=generator, enabled=True)
    assert result.mode == "VERIFIED_FACT_DRAFT" and result.answer.text == text
    assert result.answer.citation_evidence_ids == ("e1",)
    unsafe = Generator([DraftCandidate(text + " 费用增加导致利润下降。", 15)] * 3)
    rejected = BoundedSynthesisWorkflow().run(source, plan, generator=unsafe, enabled=True)
    assert rejected.mode == "SAFE_FALLBACK"


def test_overlong_or_invalid_citation_does_not_crash_verifier():
    source, plan = prepared()
    text = factual_sentence_variants(source, plan)[0][1].replace("[1]", "[" + "9" * 5000 + "]")
    assert not ControlledFactDraftVerifier().verify(source, plan, text).passed


def test_unknown_or_mixed_language_sentence_cannot_inherit_evidence_identity():
    source, plan = prepared("en")
    chinese, chinese_plan = prepared("zh-CN")
    text = factual_sentence_variants(chinese, chinese_plan)[0][1]
    assert not ControlledFactDraftVerifier().verify(source, plan, text).passed
