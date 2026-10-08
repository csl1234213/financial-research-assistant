import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.reasoning_models import ReasoningResult
from core.report_builder import build_research_report


@pytest.mark.unit
class TestReportBuilderBasic:
    def test_report_labels_follow_explicit_ui_language(self):
        report = build_research_report(
            question="贵州茅台2025年营收是多少？",
            answer="Revenue was CNY 168.84 billion.",
            citations=[],
            evidence_stats={},
            response_language="en",
        )
        assert "# Research Report" in report
        assert "## Answer (LLM Answer)" in report

    def test_report_contains_question(self):
        report = build_research_report(
            question="What is Apple's revenue?",
            answer="Apple's revenue was $383B.",
            citations=[],
            evidence_stats={},
        )
        assert "What is Apple's revenue?" in report

    def test_report_contains_answer(self):
        report = build_research_report(
            question="What is Apple's revenue?",
            answer="Apple's revenue was $383B.",
            citations=[],
            evidence_stats={},
        )
        assert "Apple's revenue was $383B" in report

    def test_report_has_title(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
        )
        assert "# Research Report" in report

    def test_report_has_question_section(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
        )
        assert "## Question" in report

    def test_report_has_answer_section(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
        )
        assert "## Answer (LLM Answer)" in report

    def test_report_distinguishes_llm_and_agent_analysis(self):
        report = build_research_report(
            question="test",
            answer="model answer",
            citations=[],
            evidence_stats={},
        )

        assert "## Answer (LLM Answer)" in report
        assert "## Agent Evidence Analysis" in report
        assert report.index("## Answer (LLM Answer)") < report.index(
            "## Agent Evidence Analysis"
        )

    def test_chinese_question_localizes_report_structure(self):
        rr = ReasoningResult(
            facts=["Tesla automotive revenue was 82.4 billion USD."],
            risks=["Pricing pressure."],
            conclusion="Collected one financial fact.",
        )
        report = build_research_report(
            question="特斯拉 2025 年的营收增长趋势如何？",
            answer="证据显示总营收同比下降。[Evidence 1]",
            citations=[],
            evidence_stats={"Tesla_Q2_2025.pdf": 2},
            reasoning_result=rr,
        )

        assert "# 研究报告" in report
        assert "## 问题" in report
        assert "## 回答（LLM 模型回答）" in report
        assert "## 智能体证据分析" in report
        assert "## 关键事实" in report
        assert "## 风险信号" in report
        assert "## AI 结论" in report
        assert "## 来源覆盖" in report
        assert "Tesla_Q2_2025.pdf: 2 个文本块" in report

    def test_report_has_source_coverage_section(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
        )
        assert "## Source Coverage" in report


@pytest.mark.unit
class TestReportBuilderWithEvidenceStats:
    def test_evidence_stats_appear_in_report(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={"apple.pdf": 5, "tesla.pdf": 3},
        )
        assert "apple.pdf: 5 chunks" in report
        assert "tesla.pdf: 3 chunks" in report

    def test_empty_evidence_stats_no_chunks(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
        )
        assert "## Source Coverage" in report


@pytest.mark.unit
class TestReportBuilderWithReasoningResult:
    def test_facts_section_when_present(self):
        rr = ReasoningResult(facts=["Revenue grew 10%", "Profit margin at 25%"])
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## Key Facts" in report
        assert "Revenue grew 10%" in report
        assert "Profit margin at 25%" in report

    def test_risks_section_when_present(self):
        rr = ReasoningResult(risks=["Regulatory risk", "Market competition"])
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## Risk Signals" in report
        assert "Regulatory risk" in report
        assert "Market competition" in report

    def test_opportunities_section_when_present(self):
        rr = ReasoningResult(opportunities=["AI expansion", "New markets"])
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## Opportunity Signals" in report
        assert "AI expansion" in report
        assert "New markets" in report

    def test_conclusion_section_when_present(self):
        rr = ReasoningResult(conclusion="Apple is a strong buy.")
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## AI Conclusion" in report
        assert "Apple is a strong buy." in report

    def test_no_facts_when_empty(self):
        rr = ReasoningResult()
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## Key Facts" not in report

    def test_no_risks_when_empty(self):
        rr = ReasoningResult()
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## Risk Signals" not in report

    def test_no_opportunities_when_empty(self):
        rr = ReasoningResult()
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## Opportunity Signals" not in report

    def test_no_conclusion_when_empty(self):
        rr = ReasoningResult()
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=rr,
        )
        assert "## AI Conclusion" not in report

    def test_no_reasoning_result_skips_all_sections(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
            reasoning_result=None,
        )
        assert "## Key Facts" not in report
        assert "## Risk Signals" not in report
        assert "## Opportunity Signals" not in report
        assert "## AI Conclusion" not in report

    def test_full_reasoning_result_includes_all_sections(self):
        rr = ReasoningResult(
            facts=["Revenue $383B"],
            risks=["Supply chain"],
            opportunities=["AI"],
            conclusion="Strong buy.",
        )
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={"apple.pdf": 10},
            reasoning_result=rr,
        )
        assert "## Key Facts" in report
        assert "## Risk Signals" in report
        assert "## Opportunity Signals" in report
        assert "## AI Conclusion" in report
        assert "## Source Coverage" in report


@pytest.mark.unit
class TestReportBuilderMarkdown:
    def test_report_is_string(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
        )
        assert isinstance(report, str)

    def test_report_uses_markdown_headings(self):
        report = build_research_report(
            question="test",
            answer="test answer",
            citations=[],
            evidence_stats={},
        )
        assert report.startswith("\n")
        assert "# " in report
