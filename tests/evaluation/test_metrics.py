import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.metrics import (
    answer_quality_score,
    calculate_overall_score,
    hallucination_score,
    retrieval_score,
    tool_selection_score,
)


class TestRetrievalScore:
    def test_perfect_match(self):
        sources = [{"url": "https://nvidia.com/earnings"}, {"url": "https://tesla.com"}]
        expected = ["https://nvidia.com/earnings", "https://tesla.com"]
        score = retrieval_score(sources, expected)
        assert score == 100.0

    def test_partial_match(self):
        sources = [{"url": "https://nvidia.com/earnings"}]
        expected = ["https://nvidia.com/earnings", "https://apple.com"]
        score = retrieval_score(sources, expected)
        assert 0 < score < 100.0

    def test_no_match(self):
        sources = [{"url": "https://google.com"}]
        expected = ["https://nvidia.com/earnings"]
        score = retrieval_score(sources, expected)
        assert score == 0.0

    def test_empty_sources(self):
        sources = []
        expected = ["https://nvidia.com/earnings"]
        score = retrieval_score(sources, expected)
        assert score == 0.0

    def test_empty_expected_sources(self):
        sources = [{"url": "https://nvidia.com/earnings"}]
        expected = []
        score = retrieval_score(sources, expected)
        assert score == 100.0

    def test_both_empty(self):
        score = retrieval_score([], [])
        assert score == 100.0

    def test_string_sources(self):
        sources = ["https://nvidia.com/earnings"]
        expected = ["https://nvidia.com/earnings"]
        score = retrieval_score(sources, expected)
        assert score == 100.0

    def test_url_normalization(self):
        sources = [{"url": "https://NVIDIA.com/earnings/"}]
        expected = ["https://nvidia.com/earnings"]
        score = retrieval_score(sources, expected)
        assert score == 100.0


class TestToolSelectionScore:
    def test_perfect_match(self):
        tools = ["search", "financial_analysis"]
        expected = ["search", "financial_analysis"]
        score = tool_selection_score(tools, expected)
        assert score == 100.0

    def test_partial_match(self):
        tools = ["search"]
        expected = ["search", "financial_analysis"]
        score = tool_selection_score(tools, expected)
        assert 0 < score < 100.0

    def test_no_match(self):
        tools = ["search"]
        expected = ["financial_analysis"]
        score = tool_selection_score(tools, expected)
        assert score == 0.0

    def test_empty_tools(self):
        score = tool_selection_score([], ["search"])
        assert score == 0.0

    def test_empty_expected(self):
        score = tool_selection_score(["search", "financial_analysis"], [])
        assert score == 100.0

    def test_case_insensitive(self):
        tools = ["Search", "Financial_Analysis"]
        expected = ["search", "financial_analysis"]
        score = tool_selection_score(tools, expected)
        assert score == 100.0


class TestAnswerQualityScore:
    def test_good_answer(self):
        answer = "NVIDIA Q3财报显示营收同比增长94%，数据中心业务收入创历史新高，毛利率达到75%。"
        question = "分析NVIDIA财报"
        criteria = ["revenue_growth", "segment_breakdown", "margin_analysis"]
        score = answer_quality_score(answer, question, criteria)
        assert score >= 50.0

    def test_short_answer(self):
        answer = "好的。"
        question = "分析NVIDIA财报"
        criteria = ["revenue_growth"]
        score = answer_quality_score(answer, question, criteria)
        assert score < 50.0

    def test_empty_answer(self):
        score = answer_quality_score("", "test", ["revenue_growth"])
        assert score == 0.0

    def test_fallback_response(self):
        answer = "Unable to process the question. Fallback mode."
        question = "分析NVIDIA"
        criteria = ["revenue_growth"]
        score = answer_quality_score(answer, question, criteria)
        assert score < 50.0

    def test_criteria_coverage(self):
        answer = "营收增长强劲，毛利率稳定，市场份额扩大，估值合理。"
        question = "分析公司"
        criteria = ["revenue_growth", "margin_analysis", "market_share"]
        score = answer_quality_score(answer, question, criteria)
        assert score >= 40.0

    def test_no_criteria(self):
        answer = "A detailed analysis of the company's financial performance."
        question = "分析公司"
        score = answer_quality_score(answer, question, [])
        assert score >= 50.0


class TestHallucinationScore:
    def test_no_hallucination(self):
        answer = "NVIDIA数据中心业务营收达到308亿美元，同比增长112%。"
        sources = [{"url": "https://nvidia.com/earnings"}]
        companies = ["NVIDIA"]
        score = hallucination_score(answer, sources, companies)
        assert score >= 80.0

    def test_guaranteed_return_marker(self):
        answer = "这支股票 guaranteed return 100% in 3 months。"
        score = hallucination_score(answer, [], [])
        assert score <= 90.0

    def test_risk_free_marker(self):
        answer = "This is a risk-free investment opportunity."
        score = hallucination_score(answer, [], [])
        assert score <= 90.0

    def test_empty_answer(self):
        score = hallucination_score("", [], [])
        assert score == 100.0

    def test_with_sources_bonus(self):
        answer = "The company shows strong growth."
        sources = [{"url": "https://example.com"}]
        companies = ["NVIDIA"]
        score = hallucination_score(answer, sources, companies)
        assert score > 80.0

    def test_score_bounded(self):
        answer = "Test analysis"
        score = hallucination_score(answer, [], [])
        assert 0 <= score <= 100


class TestOverallScore:
    def test_perfect_scores(self):
        score = calculate_overall_score(100.0, 100.0, 100.0, 100.0)
        assert score == 100.0

    def test_zero_scores(self):
        score = calculate_overall_score(0.0, 0.0, 0.0, 0.0)
        assert score == 0.0

    def test_weighted_average(self):
        score = calculate_overall_score(80.0, 90.0, 70.0, 85.0)
        expected = 80.0 * 0.25 + 90.0 * 0.20 + 70.0 * 0.35 + 85.0 * 0.20
        assert score == round(expected, 1)

    def test_custom_weights(self):
        custom_weights = {"retrieval": 0.4, "tool": 0.1, "quality": 0.4, "hallucination": 0.1}
        score = calculate_overall_score(100.0, 0.0, 0.0, 0.0, weights=custom_weights)
        assert score == 40.0
