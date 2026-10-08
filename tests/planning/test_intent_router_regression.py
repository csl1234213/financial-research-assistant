import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.intent_analyzer import IntentAnalyzer

# ============================================================
# Intent Router Regression Matrix
# ============================================================

@pytest.mark.unit
class TestIntentRouterRegression:

    def setup_method(self):
        self.analyzer = IntentAnalyzer()

    # DIRECT_CHAT
    @pytest.mark.parametrize("query", [
        "Hello",
        "Hi",
        "Hey",
        "Good morning",
        "How are you?",
        "What is AI?",
        "Explain Python",
        "Tell me a joke",
        "Who are you?",
        "What can you do?",
        "Thank you",
        "Bye",
    ])
    def test_direct_chat(self, query):
        result = self.analyzer.analyze(query)
        assert result["intent"] == "DIRECT_CHAT", f"Expected DIRECT_CHAT for '{query}'"
        assert result["companies"] is None

    # SINGLE_COMPANY
    @pytest.mark.parametrize("query,expected_company", [
        ("Analyze Tesla revenue", "Tesla"),
        ("Tesla risk analysis", "Tesla"),
        ("Apple financial performance", "Apple"),
        ("NVIDIA GPU sales", "NVIDIA"),
        ("AMD market share", "AMD"),
    ])
    def test_single_company(self, query, expected_company):
        result = self.analyzer.analyze(query)
        assert result["intent"] == "SINGLE_COMPANY", f"Expected SINGLE_COMPANY for '{query}'"
        assert expected_company in result["companies"]

    # GLOBAL_RESEARCH
    @pytest.mark.parametrize("query", [
        "Market trend 2026",
        "Interest rate impact on tech sector",
        "What are the market trends?",
        "How is the economy doing?",
        "Financial sector outlook",
        "Stock market analysis",
        "Investment strategy 2026",
        "行业趋势分析",
        "市场风险分析",
    ])
    def test_global_research(self, query):
        result = self.analyzer.analyze(query)
        assert result["intent"] == "GLOBAL_RESEARCH", f"Expected GLOBAL_RESEARCH for '{query}'"
        assert result["companies"] is None

    # COMPARE
    @pytest.mark.parametrize("query", [
        "Compare Apple and Tesla",
        "Apple vs Tesla revenue",
        "NVIDIA versus AMD",
        "对比苹果和特斯拉",
    ])
    def test_compare_companies(self, query):
        result = self.analyzer.analyze(query)
        assert result["intent"] == "COMPARE_COMPANIES", f"Expected COMPARE_COMPANIES for '{query}'"

    # Edge
    def test_company_with_research_keyword(self):
        result = self.analyzer.analyze("Analyze Tesla revenue growth and risk")
        assert result["intent"] == "SINGLE_COMPANY"
        assert "Tesla" in result["companies"]
