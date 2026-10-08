import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.runner import (
    load_dataset,
    run_dataset_evaluation,
    run_single_evaluation,
    save_report,
)


class TestRunnerSingle:
    @patch("evaluation.runner.run_agent")
    def test_run_single_evaluation_returns_structure(self, mock_run_agent):
        mock_run_agent.return_value = {
            "answer": "NVIDIA Q3财报显示营收同比增长94%。",
            "thread_id": "eval_test",
            "tools_used": ["search", "financial_analysis"],
            "sources": [{"url": "https://nvidia.com/earnings"}],
            "companies": ["NVIDIA"],
            "quality_score": 90.0,
        }

        result = run_single_evaluation(
            question="分析NVIDIA Q3财报",
            expected_tools=["search", "financial_analysis"],
            expected_sources=["https://nvidia.com/earnings"],
            criteria=["revenue_growth"],
            thread_id="eval_test",
        )

        assert "question" in result
        assert "answer" in result
        assert "tools_used" in result
        assert "sources" in result
        assert "companies" in result
        assert "duration" in result
        assert "evaluation" in result
        assert "score" in result["evaluation"]
        assert result["evaluation"]["score"] >= 0

    @patch("evaluation.runner.run_agent")
    def test_run_single_evaluation_with_tenant(self, mock_run_agent):
        mock_run_agent.return_value = {
            "answer": "Analysis complete.",
            "thread_id": "eval_tenant",
            "tools_used": ["search"],
            "sources": [],
            "companies": [],
            "quality_score": 80.0,
        }

        result = run_single_evaluation(
            question="测试",
            expected_tools=["search"],
            expected_sources=[],
            criteria=["test"],
            tenant_id=1,
            user_id=1,
        )

        mock_run_agent.assert_called_once_with(
            question="测试",
            thread_id="eval",
            tenant_id=1,
            user_id=1,
        )
        assert result["evaluation"]["score"] >= 0

    @patch("evaluation.runner.run_agent")
    def test_run_single_evaluation_handles_fallback(self, mock_run_agent):
        mock_run_agent.return_value = {
            "answer": "Unable to process the question. Fallback mode.",
            "thread_id": "eval_fallback",
            "tools_used": [],
            "sources": [],
            "companies": [],
            "quality_score": 0.0,
        }

        result = run_single_evaluation(
            question="不存在的公司XYZ",
            expected_tools=["search"],
            expected_sources=[],
            criteria=["error_handling"],
        )

        assert result["evaluation"]["score"] < 70.0
        assert result["evaluation"]["passed"] is False


class TestRunnerBatch:
    @patch("evaluation.runner.run_agent")
    def test_run_dataset_evaluation_with_limit(self, mock_run_agent):
        mock_run_agent.return_value = {
            "answer": "测试分析结果。收入增长良好，利润率稳定。",
            "thread_id": "eval_batch",
            "tools_used": ["search", "financial_analysis"],
            "sources": [{"url": "https://example.com"}],
            "companies": ["TestCorp"],
            "quality_score": 85.0,
        }

        report = run_dataset_evaluation(
            dataset_name="financial_qa.json",
            limit=3,
            verbose=False,
        )

        assert "summary" in report
        assert "results" in report
        assert report["total_questions"] == 3
        assert len(report["results"]) == 3
        assert "average_score" in report["summary"]
        assert "metric_averages" in report["summary"]

    @patch("evaluation.runner.run_agent")
    def test_run_dataset_evaluation_all_fields(self, mock_run_agent):
        mock_run_agent.return_value = {
            "answer": "分析结果。",
            "thread_id": "eval_all",
            "tools_used": ["search"],
            "sources": [],
            "companies": [],
            "quality_score": 70.0,
        }

        report = run_dataset_evaluation(
            dataset_name="financial_qa.json",
            limit=2,
            verbose=False,
        )

        assert "dataset" in report
        assert "duration" in report
        assert "timestamp" in report
        for result in report["results"]:
            assert "id" in result
            assert "question" in result
            assert "evaluation" in result


class TestSaveReport:
    def test_save_report_creates_file(self):
        report = {"test": True, "score": 95.0}
        path = save_report(report, filename="test_report.json")
        assert path.exists()
        assert path.suffix == ".json"

        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == report

        path.unlink()

    def test_save_report_auto_filename(self):
        report = {"test": True}
        path = save_report(report)
        assert path.exists()
        assert path.name.startswith("eval_report_")
        path.unlink()

    def test_load_dataset_returns_valid_data(self):
        data = load_dataset("financial_qa.json")
        assert isinstance(data, list)
        assert len(data) >= 20
