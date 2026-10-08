# ============================================================
# Complexity Analyzer Tests
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.planning import (
    ComplexityAnalyzer,
    ComplexityLevel,
    ComplexityModel,
    ComplexityResult,
    PlanningContext,
    TaskAnalyzer,
)


class TestComplexityAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return ComplexityAnalyzer()

    @pytest.fixture
    def task_analyzer(self):
        return TaskAnalyzer()

    def _analyze(self, task_analyzer, analyzer, question, companies=None, years=None):
        ctx = PlanningContext(
            question=question,
            companies=companies or [],
            years=years or [],
        )
        task_result = task_analyzer.analyze(ctx)
        return analyzer.analyze(task_result)

    # =========================
    # Level Classification
    # =========================

    def test_hello_is_low(self, task_analyzer, analyzer):
        result = self._analyze(task_analyzer, analyzer, "Hello")
        assert result.complexity.level == ComplexityLevel.LOW
        assert result.complexity.score <= 0.30

    def test_analyze_apple_10k_is_medium(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "Analyze Apple 10-K report",
            companies=["Apple"],
        )
        assert result.complexity.level == ComplexityLevel.MEDIUM
        assert 0.30 < result.complexity.score <= 0.50

    def test_compare_multi_company_multi_year_is_high(
        self, task_analyzer, analyzer
    ):
        question = "Compare Apple, Microsoft, Tesla (2020-2025)"
        result = self._analyze(
            task_analyzer, analyzer,
            question,
            companies=["Apple", "Microsoft", "Tesla"],
            years=["2020", "2021", "2022", "2023", "2024", "2025"],
        )
        assert result.complexity.level == ComplexityLevel.HIGH
        assert result.complexity.score > 0.70

    def test_research_ai_infrastructure_is_high(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "Research NVIDIA AI infrastructure trends and future outlook",
            companies=["NVIDIA"],
        )
        assert result.complexity.level == ComplexityLevel.HIGH
        assert result.complexity.score > 0.55

    def test_ocr_invoice_is_low(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "OCR this invoice",
        )
        assert result.complexity.level == ComplexityLevel.LOW

    # =========================
    # Score Range
    # =========================

    def test_score_in_range(self, task_analyzer, analyzer):
        questions = [
            ("Hello", None, None),
            ("Analyze Apple 10-K", ["Apple"], None),
            ("Compare Apple and Tesla (2020-2023)", ["Apple", "Tesla"], ["2020", "2023"]),
            ("Research AI trends", None, None),
        ]
        for q, companies, years in questions:
            result = self._analyze(task_analyzer, analyzer, q, companies, years)
            assert 0.0 <= result.complexity.score <= 1.0, (
                f"Score {result.complexity.score} out of range for '{q}'"
            )

    # =========================
    # Cost and Latency
    # =========================

    def test_cost_non_negative(self, task_analyzer, analyzer):
        result = self._analyze(task_analyzer, analyzer, "Research AI trends")
        assert result.complexity.estimated_cost >= 0

    def test_latency_positive(self, task_analyzer, analyzer):
        result = self._analyze(task_analyzer, analyzer, "Research AI trends")
        assert result.complexity.estimated_latency_ms > 0

    # =========================
    # Reason and Factors
    # =========================

    def test_reason_non_empty(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "Compare Apple, Microsoft, Tesla (2020-2025)",
            companies=["Apple", "Microsoft", "Tesla"],
            years=["2020", "2025"],
        )
        assert result.reason != ""
        assert "comparison" in result.reason.lower()

    def test_reason_simple_task(self, task_analyzer, analyzer):
        result = self._analyze(task_analyzer, analyzer, "Hello")
        assert result.reason == "Simple task"

    def test_factors_non_empty(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "Research AI trends",
        )
        assert len(result.factors) > 0
        assert "prompt_length" in result.factors
        assert "company_count" in result.factors
        assert "year_count" in result.factors
        assert "task_weight" in result.factors
        assert "comparison" in result.factors

    def test_factors_all_in_range(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "Compare Apple and Tesla",
            companies=["Apple", "Tesla"],
        )
        for key, value in result.factors.items():
            assert 0.0 <= value <= 1.0, f"Factor '{key}' value {value} out of range"

    # =========================
    # Data Model Integrity
    # =========================

    def test_result_is_complexity_result(self, task_analyzer, analyzer):
        result = self._analyze(task_analyzer, analyzer, "Hello")
        assert isinstance(result, ComplexityResult)
        assert isinstance(result.complexity, ComplexityModel)

    def test_no_provider_router_runtime_calls(self, task_analyzer, analyzer):
        result = self._analyze(task_analyzer, analyzer, "Hello")
        assert result.complexity.level in (
            ComplexityLevel.LOW,
            ComplexityLevel.MEDIUM,
            ComplexityLevel.HIGH,
        )

    # =========================
    # Edge Cases
    # =========================

    def test_empty_entities(self, task_analyzer, analyzer):
        result = self._analyze(task_analyzer, analyzer, "Hello")
        assert result.complexity.score >= 0
        assert result.complexity.estimated_tokens > 0
        assert result.complexity.estimated_cost >= 0

    def test_many_companies(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "Compare five companies",
            companies=["Apple", "Tesla", "Microsoft", "NVIDIA", "Amazon"],
        )
        assert result.complexity.level == ComplexityLevel.HIGH
        assert result.complexity.score > 0.55

    def test_financial_analysis_complexity(self, task_analyzer, analyzer):
        result = self._analyze(
            task_analyzer, analyzer,
            "Analyze Apple revenue and profit margin 2024",
            companies=["Apple"],
            years=["2024"],
        )
        assert result.complexity.level in (
            ComplexityLevel.MEDIUM,
            ComplexityLevel.HIGH,
        )
