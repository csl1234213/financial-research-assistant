import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.evaluator import evaluate_agent_response, evaluate_batch


class TestEvaluateAgentResponse:
    def test_good_response_scores_high(self):
        result = evaluate_agent_response(
            answer="NVIDIA Q3财报显示营收308亿美元，同比增长94%。数据中心业务收入创历史新高。毛利率75%。",
            question="分析NVIDIA Q3财报",
            tools_used=["search", "financial_analysis"],
            sources=[{"url": "https://nvidia.com/earnings"}],
            companies=["NVIDIA"],
            expected_tools=["search", "financial_analysis"],
            expected_sources=["https://nvidia.com/earnings"],
            criteria=["revenue_growth", "segment_breakdown", "margin_analysis"],
        )
        assert result["score"] >= 50.0
        assert result["retrieval_score"] >= 80.0
        assert result["tool_score"] >= 80.0
        assert result["quality_score"] >= 40.0
        assert result["hallucination_score"] >= 80.0
        assert len(result["issues"]) == 0
        assert result["passed"] is True

    def test_bad_response_scores_low(self):
        result = evaluate_agent_response(
            answer="好的",
            question="分析NVIDIA Q3财报",
            tools_used=[],
            sources=[],
            companies=[],
            expected_tools=["search", "financial_analysis"],
            expected_sources=["https://nvidia.com/earnings"],
            criteria=["revenue_growth", "segment_breakdown"],
        )
        assert result["score"] < 50.0
        assert result["passed"] is False

    def test_fallback_response_detected(self):
        result = evaluate_agent_response(
            answer="Unable to process the question. Fallback mode activated.",
            question="分析NVIDIA",
            tools_used=[],
            sources=[],
            companies=[],
            expected_tools=["search"],
            expected_sources=[],
            criteria=["revenue_growth"],
        )
        assert result["score"] < 70.0
        assert any(i["type"] == "fallback" for i in result["issues"])

    def test_empty_response_critical(self):
        result = evaluate_agent_response(
            answer="",
            question="分析NVIDIA",
            tools_used=[],
            sources=[],
            companies=[],
            expected_tools=["search"],
            expected_sources=[],
            criteria=["revenue_growth"],
        )
        assert result["passed"] is False
        assert any(i["type"] == "empty_response" for i in result["issues"])

    def test_returns_all_fields(self):
        result = evaluate_agent_response(
            answer="Test answer",
            question="Test question",
            tools_used=["search"],
            sources=[],
            companies=[],
            expected_tools=["search"],
            expected_sources=[],
            criteria=["test"],
        )
        required_fields = {
            "score", "retrieval_score", "tool_score",
            "quality_score", "hallucination_score", "issues", "passed",
        }
        assert required_fields.issubset(set(result.keys()))

    def test_scores_bounded_0_to_100(self):
        result = evaluate_agent_response(
            answer="Test answer",
            question="Test question",
            tools_used=["search"],
            sources=[],
            companies=[],
            expected_tools=["search"],
            expected_sources=[],
            criteria=["test"],
        )
        for key in ("score", "retrieval_score", "tool_score", "quality_score", "hallucination_score"):
            assert 0 <= result[key] <= 100, f"{key} out of bounds: {result[key]}"


class TestEvaluateBatch:
    def test_empty_batch(self):
        result = evaluate_batch([])
        assert result["total"] == 0
        assert result["passed"] == 0
        assert result["failed"] == 0
        assert result["average_score"] == 0.0

    def test_single_result(self):
        results = [
            {
                "score": 85.0,
                "retrieval_score": 90.0,
                "tool_score": 100.0,
                "quality_score": 80.0,
                "hallucination_score": 75.0,
                "issues": [],
                "passed": True,
            }
        ]
        batch = evaluate_batch(results)
        assert batch["total"] == 1
        assert batch["passed"] == 1
        assert batch["failed"] == 0
        assert batch["average_score"] == 85.0

    def test_mixed_results(self):
        results = [
            {"score": 90.0, "retrieval_score": 95.0, "tool_score": 100.0, "quality_score": 85.0, "hallucination_score": 80.0, "issues": [], "passed": True},
            {"score": 30.0, "retrieval_score": 0.0, "tool_score": 0.0, "quality_score": 20.0, "hallucination_score": 80.0, "issues": [{"type": "error", "severity": "critical"}], "passed": False},
        ]
        batch = evaluate_batch(results)
        assert batch["total"] == 2
        assert batch["passed"] == 1
        assert batch["failed"] == 1
        assert batch["average_score"] == 60.0

    def test_metric_averages(self):
        results = [
            {"score": 80.0, "retrieval_score": 90.0, "tool_score": 100.0, "quality_score": 70.0, "hallucination_score": 80.0, "issues": [], "passed": True},
            {"score": 60.0, "retrieval_score": 70.0, "tool_score": 80.0, "quality_score": 50.0, "hallucination_score": 60.0, "issues": [], "passed": True},
        ]
        batch = evaluate_batch(results)
        assert "metric_averages" in batch
        avg = batch["metric_averages"]
        assert avg["retrieval_score"] == 80.0
        assert avg["tool_score"] == 90.0
        assert avg["quality_score"] == 60.0
        assert avg["hallucination_score"] == 70.0
