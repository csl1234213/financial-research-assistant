import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from research_mode import detect_research_mode


@pytest.mark.unit
class TestDetectResearchMode:
    def test_compare_mode(self):
        assert detect_research_mode("compare Apple and Tesla") == "compare"
        assert detect_research_mode("Apple vs Tesla") == "compare"
        assert detect_research_mode("Tesla versus Apple") == "compare"
        assert detect_research_mode("difference between Apple and Tesla") == "compare"

    def test_leader_mode(self):
        assert detect_research_mode("who is stronger Apple or Tesla") == "leader"
        assert detect_research_mode("who is the leader in AI") == "leader"
        assert detect_research_mode("which company is dominant") == "leader"

    def test_risk_mode(self):
        assert detect_research_mode("what are the risks for Apple") == "risk"
        assert detect_research_mode("challenges facing Tesla") == "risk"

    def test_growth_mode(self):
        assert detect_research_mode("Apple growth outlook") == "growth"
        assert detect_research_mode("future opportunities for Tesla") == "growth"

    def test_investment_mode(self):
        assert detect_research_mode("investment outlook for Apple") == "investment"
        assert detect_research_mode("should I buy Tesla stock") == "investment"

    def test_default_mode(self):
        assert detect_research_mode("what is revenue") == "default"
        assert detect_research_mode("general information") == "default"
