# ============================================================
# Complexity Analyzer — Rule-based Complexity Scoring
# ============================================================
# Pure function: TaskResult → ComplexityResult.
# No Provider, Router, Runtime, or LLM calls.
# Weighted multi-factor scoring with explainable output.
# ============================================================

from dataclasses import fields

from config.planner import ComplexityWeights

from .complexity_models import ComplexityModel
from .complexity_result import ComplexityResult
from .task_enums import ComplexityLevel, TaskType
from .task_result import TaskResult


class ComplexityAnalyzer:
    def __init__(self, weights: ComplexityWeights | None = None):
        self._weights = weights or ComplexityWeights()

    def _weights_dict(self) -> dict[str, float]:
        return {f.name: getattr(self._weights, f.name) for f in fields(ComplexityWeights)}

    # =========================
    # Level thresholds
    # =========================

    _LOW_MAX = 0.30
    _MEDIUM_MAX = 0.50

    # =========================
    # Latency by level (ms)
    # =========================

    _LATENCY = {
        ComplexityLevel.LOW: 700,
        ComplexityLevel.MEDIUM: 1500,
        ComplexityLevel.HIGH: 3000,
    }

    # =========================
    # Cost by level (USD)
    # =========================

    _COST = {
        ComplexityLevel.LOW: 0.002,
        ComplexityLevel.MEDIUM: 0.008,
        ComplexityLevel.HIGH: 0.020,
    }

    # =========================
    # Main Entry
    # =========================

    def analyze(
        self,
        task_result: TaskResult,
    ) -> ComplexityResult:
        entities = task_result.extracted_entities
        task_type = task_result.task.task_type

        companies = [e for e in entities if not e.isdigit()]
        years = [e for e in entities if e.isdigit()]

        factors = {
            "prompt_length": self._prompt_score(len(companies), len(years)),
            "company_count": self._company_score(len(companies)),
            "year_count": self._year_score(len(years)),
            "task_weight": self._task_type_score(task_type),
            "comparison": self._comparison_score(task_type, len(companies)),
        }

        w = self._weights_dict()
        score = sum(factors[k] * w[k] for k in w)

        level = self._score_to_level(score)
        estimated_tokens = self._estimate_tokens(len(companies), len(years), level)

        complexity = ComplexityModel(
            level=level,
            score=round(score, 4),
            estimated_tokens=estimated_tokens,
            estimated_latency_ms=self._LATENCY[level],
            estimated_cost=self._COST[level],
        )

        reason = self._build_reason(task_type, len(companies), len(years))

        return ComplexityResult(
            complexity=complexity,
            reason=reason,
            factors=factors,
        )

    # =========================
    # Factor Scoring
    # =========================

    def _prompt_score(self, company_count: int, year_count: int) -> float:
        base = 1 + company_count + year_count
        if base <= 1:
            return 0.2
        if base <= 3:
            return 0.5
        return 0.8

    def _company_score(self, count: int) -> float:
        if count == 0:
            return 0.0
        if count == 1:
            return 0.3
        if count == 2:
            return 0.6
        return 0.9

    def _year_score(self, count: int) -> float:
        if count == 0:
            return 0.0
        if count == 1:
            return 0.3
        if count == 2:
            return 0.5
        return 0.8

    def _task_type_score(self, task_type: TaskType) -> float:
        _map = {
            TaskType.CHAT: 0.0,
            TaskType.DOCUMENT_QA: 0.5,
            TaskType.SUMMARIZATION: 0.5,
            TaskType.OCR: 0.3,
            TaskType.IMAGE_ANALYSIS: 0.5,
            TaskType.COMPARISON: 0.7,
            TaskType.RESEARCH: 1.0,
            TaskType.FINANCIAL_ANALYSIS: 1.0,
            TaskType.CODE_GENERATION: 0.6,
            TaskType.UNKNOWN: 0.3,
        }
        return _map.get(task_type, 0.3)

    def _comparison_score(
        self,
        task_type: TaskType,
        company_count: int,
    ) -> float:
        if task_type == TaskType.COMPARISON and company_count >= 2:
            return 0.8
        if company_count >= 2:
            return 0.5
        return 0.0

    # =========================
    # Level Mapping
    # =========================

    def _score_to_level(self, score: float) -> ComplexityLevel:
        if score <= self._LOW_MAX:
            return ComplexityLevel.LOW
        if score <= self._MEDIUM_MAX:
            return ComplexityLevel.MEDIUM
        return ComplexityLevel.HIGH

    # =========================
    # Estimations
    # =========================

    def _estimate_tokens(
        self,
        company_count: int,
        year_count: int,
        level: ComplexityLevel,
    ) -> int:
        base = 128
        char_tokens = (1 + company_count + year_count) * 50
        company_tokens = company_count * 64
        year_tokens = year_count * 16

        _task_bonus = {
            ComplexityLevel.LOW: 100,
            ComplexityLevel.MEDIUM: 300,
            ComplexityLevel.HIGH: 500,
        }
        task_bonus = _task_bonus[level]

        return base + char_tokens + company_tokens + year_tokens + task_bonus

    # =========================
    # Reason
    # =========================

    def _build_reason(
        self,
        task_type: TaskType,
        company_count: int,
        year_count: int,
    ) -> str:
        parts = []

        if task_type == TaskType.COMPARISON and company_count >= 2:
            parts.append("Multi-company comparison")
        elif task_type == TaskType.COMPARISON:
            parts.append("Comparison task")
        elif task_type == TaskType.FINANCIAL_ANALYSIS:
            parts.append("Financial analysis task")
        elif task_type == TaskType.RESEARCH:
            parts.append("Research task")
        elif task_type == TaskType.DOCUMENT_QA:
            parts.append("Document QA task")

        if company_count >= 3:
            parts.append("multiple companies")
        elif company_count == 2:
            parts.append("two companies")

        if year_count >= 2:
            parts.append("multiple years")

        if not parts:
            return "Simple task"

        return ", ".join(parts)
