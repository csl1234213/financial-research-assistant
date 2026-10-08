from agent.reasoning_models import Evidence
from core.answer_grounding import sanitize_answer
from core.typesafe_citation import (
    CitationAction,
    CitationRelation,
    judge_citation,
)


def test_supported_numeric_claim_is_typed_accept():
    judgment = judge_citation(
        "NVIDIA Q1 FY2027 revenue was $81.6B.",
        "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
        metadata={"company": "NVIDIA", "quarter": "Q1_FY2027"},
    )
    assert judgment.relation is CitationRelation.SUPPORTS
    assert judgment.action is CitationAction.ACCEPT


def test_wrong_numeric_value_is_typed_reject():
    judgment = judge_citation(
        "NVIDIA Q1 FY2027 revenue was $91B.",
        "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
        metadata={"company": "NVIDIA", "quarter": "Q1_FY2027"},
    )
    assert judgment.relation is CitationRelation.CONTRADICTS
    assert judgment.action is CitationAction.REJECT


def test_wrong_period_is_rejected_before_numeric_overlap():
    judgment = judge_citation(
        "Tesla Q2 2025 revenue was $22.5B.",
        "Tesla Q4 2025 revenue was $24.9 billion.",
        metadata={"company": "Tesla", "quarter": "Q4_2025"},
    )
    assert judgment.relation is CitationRelation.CONTRADICTS
    assert judgment.action is CitationAction.REJECT


def test_wrong_company_is_rejected():
    judgment = judge_citation(
        "Apple revenue was $100B.",
        "NVIDIA revenue was $81.6 billion.",
        metadata={"company": "NVIDIA"},
    )
    assert judgment.relation is CitationRelation.CONTRADICTS
    assert judgment.action is CitationAction.REJECT


def test_missing_exact_quote_is_fabricated():
    judgment = judge_citation(
        "Revenue was $81.6B.",
        "NVIDIA reported revenue of $81.6 billion.",
        exact_quote="Revenue was $81.6B.",
    )
    assert judgment.relation is CitationRelation.FABRICATED
    assert judgment.action is CitationAction.REJECT


def test_weak_qualitative_overlap_requires_review():
    judgment = judge_citation(
        "The filing proves a strong competitive advantage.",
        "The filing lists quarterly revenue and operating expenses.",
    )
    assert judgment.relation is CitationRelation.SAYS_NOTHING
    assert judgment.action is CitationAction.REVIEW


def test_chinese_metric_and_numeric_normalization_is_supported():
    judgment = judge_citation(
        "英伟达第一财季营收为816亿美元。",
        "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
        metadata={"company": "NVIDIA", "quarter": "Q1_FY2027"},
    )
    assert judgment.relation is CitationRelation.SUPPORTS
    assert judgment.action is CitationAction.ACCEPT


def test_production_sanitizer_exposes_typed_judgment_for_explicit_citation():
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA Q1 FY2027 revenue was $91B [Evidence 1].",
        [Evidence(
            content="NVIDIA Q1 FY2027 revenue was $81.6 billion.",
            source="NVIDIA_Q1_FY2027.pdf",
            company="NVIDIA",
            metadata={"quarter": "Q1_FY2027", "chunk_id": "nvidia-q1"},
        )],
    )
    assert result.judgments
    assert result.judgments[0].relation is CitationRelation.CONTRADICTS
    assert result.judgments[0].action is CitationAction.REJECT
    assert "$91B" not in result.answer


def test_production_sanitizer_does_not_promote_typesafe_review_to_supported_prose():
    result = sanitize_answer(
        "What competitive advantage does NVIDIA report?",
        "The filing proves a strong competitive advantage. [Evidence 1].",
        [Evidence(
            content="The filing lists quarterly revenue and operating expenses.",
            source="NVIDIA_Q1_FY2027.pdf",
            company="NVIDIA",
            metadata={"quarter": "Q1_FY2027", "chunk_id": "nvidia-q1"},
        )],
    )
    assert result.judgments
    assert result.judgments[0].action is CitationAction.REVIEW
    assert "strong competitive advantage" not in result.answer
    assert "insufficient" in result.answer.lower()
