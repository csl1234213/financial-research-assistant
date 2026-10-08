import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.execution_result import ExecutionResult
from agent.reasoning_engine import ReasoningEngine
from agent.reasoning_models import Evidence, ReasoningResult


class TestReasoningEngine:
    @pytest.fixture
    def engine(self):
        return ReasoningEngine()

    def test_analyze_empty(self, engine):
        result = engine.analyze([])
        assert isinstance(result, ReasoningResult)
        assert result.facts == []
        assert result.risks == []
        assert result.opportunities == []
        assert "0 financial facts" in result.conclusion

    def test_analyze_with_evidence(self, engine):
        ev = Evidence(
            content="Revenue grew 10% year over year with strong margins.",
            source="apple.pdf",
            company="Apple",
            confidence=0.95,
        )
        exec_result = ExecutionResult(
            step_id=1,
            success=True,
            output=[ev],
        )
        result = engine.analyze([exec_result])
        assert isinstance(result, ReasoningResult)
        assert len(result.facts) >= 1
        assert "Revenue grew" in result.facts[0]

    def test_failed_execution_skipped(self, engine):
        exec_result = ExecutionResult(
            step_id=1,
            success=False,
            error="No handler",
        )
        result = engine.analyze([exec_result])
        assert result.facts == []
        assert result.risks == []

    def test_none_output_skipped(self, engine):
        exec_result = ExecutionResult(
            step_id=1,
            success=True,
            output=None,
        )
        result = engine.analyze([exec_result])
        assert result.facts == []

    def test_extract_facts_from_revenue(self, engine):
        ev = Evidence(content="Revenue increased 15% to $100B.", company="Apple")
        exec_result = ExecutionResult(step_id=1, success=True, output=[ev])
        result = engine.analyze([exec_result])
        assert len(result.facts) >= 1

    def test_extract_facts_from_profit(self, engine):
        ev = Evidence(content="Profit margin improved to 25%.", company="Apple")
        exec_result = ExecutionResult(step_id=1, success=True, output=[ev])
        result = engine.analyze([exec_result])
        assert len(result.facts) >= 1

    def test_extract_risks(self, engine):
        ev = Evidence(
            content="The company faces significant risk from supply chain challenges.",
            company="Apple",
        )
        exec_result = ExecutionResult(step_id=1, success=True, output=[ev])
        result = engine.analyze([exec_result])
        assert len(result.risks) >= 1

    def test_extract_opportunities(self, engine):
        ev = Evidence(
            content="Strong growth in AI segment with expanding market share.",
            company="NVIDIA",
        )
        exec_result = ExecutionResult(step_id=1, success=True, output=[ev])
        result = engine.analyze([exec_result])
        assert len(result.opportunities) >= 1

    def test_conclusion_summary(self, engine):
        ev1 = Evidence(content="Revenue grew 10%.", company="Apple")
        ev2 = Evidence(content="Risk from supply chain challenges.", company="Apple")
        ev3 = Evidence(content="Strong growth in AI.", company="Apple")
        exec_result = ExecutionResult(step_id=1, success=True, output=[ev1, ev2, ev3])
        result = engine.analyze([exec_result])
        assert "1 financial facts" in result.conclusion
        assert "1 risk signals" in result.conclusion
        assert "1 opportunity signals" in result.conclusion

    def test_group_by_company(self, engine):
        ev1 = Evidence(content="Apple revenue.", company="Apple")
        ev2 = Evidence(content="NVIDIA revenue.", company="NVIDIA")
        ev3 = Evidence(content="Apple profit.", company="Apple")
        grouped = engine.group_by_company([ev1, ev2, ev3])
        assert "Apple" in grouped
        assert "NVIDIA" in grouped
        assert len(grouped["Apple"]) == 2
        assert len(grouped["NVIDIA"]) == 1
