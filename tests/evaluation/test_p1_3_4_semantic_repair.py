"""Offline semantic repair contracts for P1.3.4."""

from agent.reasoning_models import Evidence
from core.answer_grounding import sanitize_answer
from core.evidence_coverage import evaluate_coverage
from core.financial_grounding import extract_normalized_numbers, numbers_equivalent
from retrieval.periods import period_scoped_row_numbers


def _evidence(content: str, *, company: str = "NVIDIA", period: str = "Q1_FY2027") -> Evidence:
    return Evidence(
        content=content,
        source=f"{company}_{period}.pdf",
        company=company,
        metadata={"company": company, "periods": period, "quarter": period},
    )


def test_chinese_billion_unit_is_normalized_without_treating_75_2b_as_7_52b() -> None:
    chinese = extract_normalized_numbers("752 亿美元")[0]
    english = extract_normalized_numbers("$75.2 billion")[0]
    assert numbers_equivalent(chinese, english)
    assert not numbers_equivalent(extract_normalized_numbers("75.2 亿美元")[0], english)


def test_supported_chinese_core_claim_is_rewritten_to_an_equivalent_unit() -> None:
    result = sanitize_answer(
        "英伟达 2027 财年第一季度的数据中心业务表现如何？",
        "数据中心收入为 75.2 亿美元，同比增长 92%。",
        [_evidence(
            "NVIDIA Q1 FY2027 Record Data Center revenue of $75.2 billion, up 92% from a year ago."
        )],
    )
    assert "752 亿美元" in result.answer
    assert "证据不足" not in result.answer
    assert result.unsupported_count == 0


def test_period_scoped_table_row_does_not_use_q4_value_for_q2_claim() -> None:
    content = (
        "Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025 "
        "Total revenues 25,707 19,335 22,496 28,095 24,901"
    )
    value = period_scoped_row_numbers(content, "Q2_2025", "revenue")
    assert [item.value for item in value] == [22_496]


def test_explicit_query_period_is_inherited_by_unqualified_claims_from_comparative_table() -> None:
    content = (
        "Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025 "
        "Total revenues 25,707 19,335 22,496 28,095 24,901"
    )
    source = Evidence(
        content=content,
        source="Tesla_Q4_FY2025.pdf",
        company="Tesla",
        metadata={
            "company": "Tesla",
            "quarter": "Q4_2025",
            "periods": "Q4_2024|Q1_2025|Q2_2025|Q3_2025|Q4_2025",
            "metrics": "revenue",
        },
    )

    supported = sanitize_answer(
        "What was Tesla total revenue in Q2 2025?",
        "Total revenues were $22,496 million.",
        [source],
    )
    wrong_quarter = sanitize_answer(
        "What was Tesla total revenue in Q2 2025?",
        "Total revenues were $24.901 billion.",
        [source],
    )

    assert "$22,496 million" in supported.answer
    assert supported.unsupported_count == 0
    assert "$24.901 billion" not in wrong_quarter.answer
    assert wrong_quarter.unsupported_count == 1


def test_summary_coverage_reports_missing_headline_facts() -> None:
    result = evaluate_coverage(
        "总结苹果公司 2026 年第二季度的财务表现。",
        "只能确认服务业务表现。",
        [_evidence(
            "Apple Q2 2026 Services gross margin increased.",
            company="Apple",
            period="Q2_2026",
        )],
    )
    assert result.grade in {"PARTIAL", "FAILED"}
    assert any(item.fact.metric == "revenue" and not item.evidence_present for item in result.facts)


def test_business_development_summary_has_no_implicit_financial_coverage_checklist() -> None:
    result = evaluate_coverage(
        "Summarize Tesla's major business developments during Q2 2025.",
        "Tesla's Q2 business-development narrative is not present in the supplied filing.",
        [_evidence("Tesla Q2 2025 total revenue was $22,496 million.", company="Tesla", period="Q2_2025")],
    )

    assert result.required == ()
    assert result.facts == ()


def test_mixed_company_line_keeps_supported_claim_and_removes_wrong_period_claim() -> None:
    result = sanitize_answer(
        "Compare Tesla and NVIDIA revenue performance.",
        "NVIDIA revenue was $81.6B; Tesla revenue was $24.9B.",
        [
            _evidence(
                "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
                company="NVIDIA",
            ),
            Evidence(
                content="Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025 Total revenues 25,707 19,335 22,496 28,095 24,901",
                source="Tesla_Q2_2025.pdf",
                company="Tesla",
                metadata={"company": "Tesla", "quarter": "Q2_2025"},
            ),
        ],
    )
    assert "$81.6B" in result.answer
    assert "$24.9B" not in result.answer
