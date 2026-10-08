import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from core.intent_analyzer import IntentAnalyzer


@pytest.mark.unit
class TestIntentAnalyzerSingleCompany:
    def test_apple_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("What is Apple's revenue?")
        assert result["intent"] == "SINGLE_COMPANY"
        assert result["companies"] == ["Apple"]

    def test_tesla_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Tesla delivery numbers")
        assert result["intent"] == "SINGLE_COMPANY"
        assert result["companies"] == ["Tesla"]

    def test_nvidia_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("NVIDIA GPU sales")
        assert result["intent"] == "SINGLE_COMPANY"
        assert result["companies"] == ["NVIDIA"]

    def test_amd_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("AMD processor market share")
        assert result["intent"] == "SINGLE_COMPANY"
        assert result["companies"] == ["AMD"]

    def test_chinese_apple_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("苹果的营收是多少")
        assert result["intent"] == "SINGLE_COMPANY"
        assert result["companies"] == ["Apple"]

    def test_chinese_tesla_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("特斯拉的交付量")
        assert result["intent"] == "SINGLE_COMPANY"
        assert result["companies"] == ["Tesla"]

    def test_chinese_nvidia_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("英伟达的股价")
        assert result["intent"] == "SINGLE_COMPANY"
        assert result["companies"] == ["NVIDIA"]


@pytest.mark.unit
class TestIntentAnalyzerCompare:
    def test_vs_keyword_returns_compare(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Apple vs Tesla revenue")
        assert result["intent"] == "COMPARE_COMPANIES"
        assert "Apple" in result["companies"]
        assert "Tesla" in result["companies"]

    def test_compare_keyword_returns_compare(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Compare Apple and Tesla")
        assert result["intent"] == "COMPARE_COMPANIES"
        assert "Apple" in result["companies"]
        assert "Tesla" in result["companies"]

    def test_versus_keyword_returns_compare(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Apple versus NVIDIA market cap")
        assert result["intent"] == "COMPARE_COMPANIES"
        assert "Apple" in result["companies"]
        assert "NVIDIA" in result["companies"]

    def test_chinese_compare_returns_compare(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("对比苹果和特斯拉")
        assert result["intent"] == "COMPARE_COMPANIES"
        assert "Apple" in result["companies"]
        assert "Tesla" in result["companies"]

    def test_chinese_vs_returns_compare(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("比较特斯拉和英伟达")
        assert result["intent"] == "COMPARE_COMPANIES"
        assert "Tesla" in result["companies"]
        assert "NVIDIA" in result["companies"]

    def test_compare_with_case_insensitive(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("apple VS tesla")
        assert result["intent"] == "COMPARE_COMPANIES"
        assert "Apple" in result["companies"]
        assert "Tesla" in result["companies"]


@pytest.mark.unit
class TestIntentAnalyzerGlobal:
    def test_no_company_returns_global(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("What are the market trends?")
        assert result["intent"] == "GLOBAL_RESEARCH"
        assert result["companies"] is None

    def test_general_question_returns_global(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("How is the economy doing?")
        assert result["intent"] == "GLOBAL_RESEARCH"
        assert result["companies"] is None

    def test_financial_question_returns_global(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Interest rate impact on tech sector")
        assert result["intent"] == "GLOBAL_RESEARCH"
        assert result["companies"] is None


@pytest.mark.unit
class TestIntentAnalyzerDirectChat:
    def test_hello_returns_direct_chat(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Hello")
        assert result["intent"] == "DIRECT_CHAT"
        assert result["companies"] is None

    def test_hi_returns_direct_chat(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Hi")
        assert result["intent"] == "DIRECT_CHAT"
        assert result["companies"] is None

    def test_what_is_ai_returns_direct_chat(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("What is AI?")
        assert result["intent"] == "DIRECT_CHAT"
        assert result["companies"] is None

    def test_explain_python_returns_direct_chat(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Explain Python")
        assert result["intent"] == "DIRECT_CHAT"
        assert result["companies"] is None


@pytest.mark.unit
class TestIntentAnalyzerEdgeCases:
    def test_empty_query_returns_direct_chat(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("")
        assert result["intent"] == "DIRECT_CHAT"

    def test_document_ids_always_none(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Apple revenue")
        assert result["document_ids"] is None

    def test_unknown_companies_returns_global(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Acme revenue 2024")
        assert result["intent"] == "GLOBAL_RESEARCH"

    def test_company_in_canonical_entity_catalog_returns_single_company(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Microsoft revenue 2024")
        assert result["intent"] == "FINANCIAL_FACT_QUERY"
        assert result["companies"] == ["Microsoft"]
        assert result["canonical_metric"] == "revenue"
        assert result["fiscal_year"] == "2024"

    def test_multiple_companies_without_compare_returns_unknown(self):
        analyzer = IntentAnalyzer()
        result = analyzer.analyze("Apple Tesla revenue")
        assert result["intent"] == "UNKNOWN"
        assert "Apple" in result["companies"]
        assert "Tesla" in result["companies"]
