import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from prompt_builder import (
    FINANCIAL_COMPARE_PROMPT_VERSION,
    FINANCIAL_RAG_PROMPT_VERSION,
    PROMPT_RULES,
    build_compare_prompt,
    build_direct_chat_prompt,
    build_prompt,
    get_prompt_system_prompt,
)


@pytest.mark.unit
class TestBuildPrompt:
    def test_explicit_ui_language_overrides_question_language(self):
        english = build_prompt(
            "贵州茅台2025年营收是多少？",
            "Revenue was CNY 168.84 billion.",
            response_language="en",
        )
        chinese = build_prompt(
            "What was Guizhou Moutai's FY2025 revenue?",
            "Revenue was CNY 168.84 billion.",
            response_language="zh-CN",
        )

        assert "regardless of the question or conversation language" in english
        assert "English number/currency conventions" in english
        assert "Simplified Chinese, regardless of the question" in chinese
        assert "Chinese financial number/currency conventions" in chinese

        assert "system-level requirement" in get_prompt_system_prompt(
            "financial_rag",
            response_language="en",
        )
        assert "Chinese financial units" in get_prompt_system_prompt(
            "direct_chat",
            response_language="zh-CN",
        )

    def test_prompt_contains_question(self):
        prompt = build_prompt(
            question="What is Apple's revenue?",
            context="Apple revenue was $383B in 2023.",
        )
        assert "What is Apple's revenue?" in prompt

    def test_prompt_contains_context(self):
        prompt = build_prompt(
            question="What is Apple's revenue?",
            context="Apple revenue was $383B in 2023.",
        )
        assert "Apple revenue was $383B in 2023" in prompt

    def test_prompt_contains_prompt_rules(self):
        prompt = build_prompt(
            question="What is Apple's revenue?",
            context="Apple revenue was $383B in 2023.",
        )
        assert "professional financial analyst" in prompt

    def test_prompt_has_evidence_section(self):
        prompt = build_prompt(
            question="test",
            context="some context",
        )
        assert "EVIDENCE" in prompt

    def test_prompt_has_question_section(self):
        prompt = build_prompt(
            question="test",
            context="some context",
        )
        assert "QUESTION" in prompt

    def test_prompt_has_response_format(self):
        prompt = build_prompt(
            question="test",
            context="some context",
        )
        assert "RESPONSE FORMAT" in prompt

    def test_prompt_has_evidence_citation_instruction(self):
        prompt = build_prompt(
            question="test",
            context="some context",
        )
        assert "[Evidence 1]" in prompt

    def test_prompt_requires_question_language_without_relaxing_grounding(self):
        prompt = build_prompt(
            question="特斯拉的收入增长如何？",
            context="Tesla automotive revenue was 82.4 billion USD.",
        )

        assert "same language as the QUESTION" in prompt
        assert "ONLY using information from the Evidence section" in prompt
        assert "Do NOT use external knowledge" in prompt
        assert "exactly as [Evidence N]" in prompt

    def test_prompt_prevents_flattened_table_period_misalignment(self):
        prompt = build_prompt(
            question="Analyze Tesla Q2 automotive revenue.",
            context=(
                "Q1-2025 Q2-2025 Q4-2025 YoY "
                "Total automotive revenues 13,967 16,661 17,693 -11%"
            ),
        )

        assert "align each value with its column header" in prompt
        assert "latest displayed period" in prompt
        assert "year-over-year and quarter-over-quarter" in prompt
        assert "prior-year comparison" in prompt
        assert "value is absent" in prompt

    def test_prompt_uses_document_aware_financial_period_rules(self):
        prompt = build_prompt(
            "What was Apple's operating cash flow in Q2 2026?",
            "Three Months Ended | Six Months Ended | Operating cash flow 82,627",
        )
        assert "internal evidence ledger" in prompt
        assert "reporting period" in prompt
        assert "duration" in prompt
        assert "three-month and six-month values separate" in prompt
        assert "filename is never authoritative" in prompt
        assert "outlook value" in prompt

    def test_prompt_handles_tesla_table_and_nvidia_actual_vs_outlook(self):
        prompt = build_compare_prompt(
            "Compare Tesla Q2 2025 revenue with NVIDIA Q1 FY2027 revenue.",
            "Q4-2024 Q1-2025 Q2-2025 | Q1 actual | Q2 outlook",
        )
        assert "exact requested column" in prompt
        assert "Q4/FY2025" in prompt
        assert "Q2 outlook is not Q1 actual" in prompt
        assert "actual/" in prompt

    def test_prompt_limits_repeated_insufficient_evidence_text(self):
        prompt = build_prompt("Summarize Apple Q2 2026.", "partial evidence")
        assert "one concise evidence-limitation sentence" in prompt
        assert "do not repeat" in prompt
        assert "refusal" in prompt

    def test_prompt_requires_cited_causal_evidence_for_driver_questions(self):
        prompt = build_prompt(
            "Why did NVIDIA's Data Center business grow?",
            "AI-factory and agentic-AI management commentary.",
        )
        assert "explicitly cited causal or" in prompt
        assert "Do not substitute" in prompt
        assert "correlation or a safe-harbor disclaimer" in prompt

    @pytest.mark.parametrize("question", [
        "What is Apple's revenue for Q2 2026?",
        "苹果 2026 年第二季度的营收是多少？",
    ])
    def test_metric_fact_has_no_mandatory_report_sections(self, question):
        prompt = build_prompt(question, "Apple revenue evidence")

        assert "Direct financial answer:" in prompt
        assert "Answer only the requested metric or fact" in prompt
        assert "\nRisks\n" not in prompt
        assert "\nKey Findings\n" not in prompt

    def test_summary_does_not_force_risk_or_outlook_sections(self):
        prompt = build_prompt("Summarize Apple's Q2 2026 financial results.", "evidence")

        assert "Financial summary:" in prompt
        assert "supported headline facts" in prompt
        assert "component rows distinct from financial statement totals" in prompt
        assert "\nRisks\n" not in prompt

    def test_prompt_no_history_section_empty(self):
        prompt = build_prompt(
            question="test",
            context="some context",
        )
        assert "CONVERSATION HISTORY" in prompt

    def test_prompt_with_history(self):
        prompt = build_prompt(
            question="What about Tesla?",
            context="Tesla delivered 1.8M vehicles.",
            history=[
                {"q": "What is Apple's revenue?", "a": "$383B"},
                {"q": "What about profit?", "a": "$97B net income"},
            ],
        )
        assert "What is Apple's revenue?" in prompt
        assert "$383B" in prompt
        assert "What about profit?" in prompt
        assert "$97B net income" in prompt

    def test_prompt_history_truncated_to_last_3(self):
        prompt = build_prompt(
            question="Latest?",
            context="context",
            history=[
                {"q": "Q1", "a": "A1"},
                {"q": "Q2", "a": "A2"},
                {"q": "Q3", "a": "A3"},
                {"q": "Q4", "a": "A4"},
                {"q": "Q5", "a": "A5"},
            ],
        )
        assert "Q1" not in prompt
        assert "Q2" not in prompt
        assert "Q3" in prompt
        assert "Q4" in prompt
        assert "Q5" in prompt

    def test_prompt_returns_string(self):
        prompt = build_prompt(
            question="test",
            context="context",
        )
        assert isinstance(prompt, str)


@pytest.mark.unit
class TestBuildComparePrompt:
    def test_compare_prompt_contains_question(self):
        prompt = build_compare_prompt(
            question="Compare Apple and Tesla",
            context="Apple data... Tesla data...",
        )
        assert "Compare Apple and Tesla" in prompt

    def test_compare_prompt_contains_context(self):
        prompt = build_compare_prompt(
            question="Compare Apple and Tesla",
            context="Apple data... Tesla data...",
        )
        assert "Apple data... Tesla data..." in prompt

    def test_compare_prompt_has_business_strategy_section(self):
        prompt = build_compare_prompt(
            question="Compare Apple and Tesla",
            context="data",
        )
        assert "Business Strategy" in prompt

    def test_compare_prompt_has_ai_technology_section(self):
        prompt = build_compare_prompt(
            question="Compare Apple and Tesla",
            context="data",
        )
        assert "AI Technology" in prompt

    def test_compare_prompt_has_infrastructure_section(self):
        prompt = build_compare_prompt(
            question="Compare Apple and Tesla",
            context="data",
        )
        assert "Infrastructure" in prompt

    def test_compare_prompt_has_competitive_advantages_section(self):
        prompt = build_compare_prompt(
            question="Compare Apple and Tesla",
            context="data",
        )
        assert "Competitive Advantages" in prompt

    def test_broad_compare_risk_dimension_is_optional(self):
        prompt = build_compare_prompt(
            question="Compare Apple and Tesla",
            context="data",
        )
        assert "and Risks. These are optional" in prompt
        assert "Never skip a section" not in prompt

    def test_compare_prompt_includes_analyst_role(self):
        prompt = build_compare_prompt(
            question="test",
            context="data",
        )
        assert "financial analyst" in prompt

    def test_compare_prompt_returns_string(self):
        prompt = build_compare_prompt(
            question="test",
            context="data",
        )
        assert isinstance(prompt, str)

    def test_compare_prompt_requires_question_language_and_evidence_only(self):
        prompt = build_compare_prompt(
            question="比较特斯拉和英伟达",
            context="evidence",
        )

        assert "same language as the QUESTION" in prompt
        assert "Use ONLY the provided context" in prompt
        assert "exactly as [Evidence N]" in prompt

    @pytest.mark.parametrize("question", [
        "Compare Tesla Q2 2025 revenue with NVIDIA Q1 FY2027 revenue.",
        "比较特斯拉 2025 年第二季度和英伟达 FY2027 第一季度的营收。",
        "Compare Apple and NVIDIA gross margins.",
        "比较苹果和英伟达的毛利率。",
    ])
    def test_metric_comparison_has_focused_format(self, question):
        prompt = build_compare_prompt(question, "Revenue, AI strategy and risks evidence")

        assert "Focused financial comparison:" in prompt
        assert "Compare only the financial metrics explicitly requested" in prompt
        assert "reporting period" in prompt
        assert "unit/currency" in prompt
        assert "cite both operands" in prompt
        assert "Business Strategy" not in prompt
        assert "AI Technology" not in prompt
        assert "Investment Implications" not in prompt
        assert "Never skip a section" not in prompt

    def test_chinese_and_english_metric_comparisons_receive_same_scope(self):
        english = build_compare_prompt("Compare Tesla and NVIDIA revenue.", "context")
        chinese = build_compare_prompt("比较特斯拉和英伟达的营收。", "context")

        def response_format(prompt):
            return prompt.split("RESPONSE FORMAT\n", 1)[1]

        assert response_format(english) == response_format(chinese)

    def test_rag_and_compare_routes_both_focus_metric_comparisons(self):
        question = "Compare Apple's revenue in Q1 and Q2 2026."

        for builder in (build_prompt, build_compare_prompt):
            prompt = builder(question, "Apple quarterly financial evidence")
            assert "Focused financial comparison:" in prompt
            assert "Compare only the financial metrics explicitly requested" in prompt

    def test_broad_comparison_does_not_inject_unrequested_company(self):
        prompt = build_compare_prompt("Compare Apple and Microsoft strategies.", "evidence")

        assert "Question-led comparison:" in prompt
        assert "Business Strategy" in prompt
        assert "These are optional" in prompt
        assert "Tesla:" not in prompt
        assert "NVIDIA:" not in prompt

    def test_strategy_request_is_not_expanded_by_retrieved_numeric_data(self):
        prompt = build_compare_prompt(
            "Compare Apple and Microsoft strategies.",
            "Apple revenue was $94 billion; Microsoft operating income was $32 billion.",
        )

        assert "Question-led comparison:" in prompt
        assert "Focused financial comparison:" not in prompt


@pytest.mark.unit
class TestPromptRules:
    def test_prompt_rules_is_string(self):
        assert isinstance(PROMPT_RULES, str)

    def test_prompt_rules_contains_key_instructions(self):
        assert "financial analyst" in PROMPT_RULES
        assert "Evidence" in PROMPT_RULES
        assert "invent facts" in PROMPT_RULES
        assert "every number" in PROMPT_RULES
        assert "internal English representation" in PROMPT_RULES
        assert "final answer" in PROMPT_RULES

    def test_grounded_prompts_use_new_immutable_versions(self):
        assert FINANCIAL_RAG_PROMPT_VERSION == "2.4.1"
        assert FINANCIAL_COMPARE_PROMPT_VERSION == "2.4.1"


@pytest.mark.unit
def test_direct_chat_prompt_is_versioned_and_contains_role_history():
    prompt = build_direct_chat_prompt(
        "What is AI?",
        history=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "How can I help?"},
        ],
    )

    assert "User: Hello" in prompt
    assert "Assistant: How can I help?" in prompt
    assert "User: What is AI?" in prompt
