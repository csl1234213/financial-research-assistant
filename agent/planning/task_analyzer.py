# ============================================================
# Task Analyzer — Rule-based Task Classification
# ============================================================
# Analyzes a PlanningContext and produces a TaskResult.
# Pure function — no Provider, no Router, no Runtime calls.
# Input: PlanningContext (question, companies, years, metadata)
# Output: TaskResult (task, reason, entities, estimated_tokens)
# ============================================================

from .entity_extractor import (
    extract_companies as extract_companies_from_question,
)
from .entity_extractor import (
    extract_years as extract_years_from_question,
)
from .keyword_rules import classify_by_keyword, is_company_performance_question
from .planning_context import PlanningContext
from .task_enums import (
    ComplexityLevel,
    TaskType,
)
from .task_models import TaskModel
from .task_result import TaskResult


class TaskAnalyzer:
    def analyze(
        self,
        context: PlanningContext,
    ) -> TaskResult:
        q = context.question
        q_lower = q.lower()

        task_type, matched_keyword = classify_by_keyword(q_lower)
        companies = self._merge_entities(
            context.companies,
            extract_companies_from_question(q),
        )
        if (
            task_type == TaskType.CHAT
            and matched_keyword != "general concept"
            and companies
            and is_company_performance_question(q_lower)
        ):
            task_type, matched_keyword = TaskType.DOCUMENT_QA, "company business performance"
        years = self._merge_entities(
            context.years,
            extract_years_from_question(q),
        )

        entities = companies + years
        task = TaskModel(
            task_type=task_type,
            confidence=self._confidence(task_type, matched_keyword),
            complexity=self._estimate_complexity(task_type, len(companies)),
        )
        reason = self._build_reason(task_type, matched_keyword)
        estimated_tokens = self._estimate_tokens(len(q), len(companies), len(years))

        return TaskResult(
            task=task,
            reason=reason,
            extracted_entities=entities,
            estimated_tokens=estimated_tokens,
        )

    # =========================
    # Helpers
    # =========================

    def _merge_entities(
        self,
        context_entities: list[str],
        extracted: list[str],
    ) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for e in context_entities:
            if e not in seen:
                seen.add(e)
                result.append(e)

        for e in extracted:
            if e not in seen:
                seen.add(e)
                result.append(e)

        return result

    def _confidence(
        self,
        task_type: TaskType,
        matched_keyword: str | None,
    ) -> float:
        if matched_keyword is not None:
            return 0.95
        if task_type == TaskType.CHAT:
            return 0.8
        return 0.5

    def _estimate_complexity(
        self,
        task_type: TaskType,
        company_count: int,
    ) -> ComplexityLevel:
        if task_type in (TaskType.RESEARCH, TaskType.FINANCIAL_ANALYSIS):
            if company_count >= 2:
                return ComplexityLevel.HIGH
            return ComplexityLevel.MEDIUM
        if task_type == TaskType.COMPARISON:
            return ComplexityLevel.HIGH if company_count >= 2 else ComplexityLevel.MEDIUM
        if company_count >= 2:
            return ComplexityLevel.MEDIUM
        return ComplexityLevel.LOW

    def _build_reason(
        self,
        task_type: TaskType,
        matched_keyword: str | None,
    ) -> str:
        if matched_keyword is not None:
            return f"Detected {task_type.value} keyword: '{matched_keyword}'"
        if task_type == TaskType.FINANCIAL_ANALYSIS:
            return "Detected financial analysis task"
        return f"Default {task_type.value}"

    def _estimate_tokens(
        self,
        question_len: int,
        company_count: int,
        year_count: int,
    ) -> int:
        base = 128
        per_company = 32
        per_year = 8
        per_char = question_len // 4

        return base + per_char + per_company * company_count + per_year * year_count
