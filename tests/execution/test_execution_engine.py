# ============================================================
# Execution Engine Tests
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.execution import (
    ExecutionContext,
    ExecutionEngine,
    ExecutionStrategyType,
    StrategyRegistry,
)
from agent.planning import (
    ComplexityLevel,
    ComplexityResult,
    TaskResult,
    TaskType,
)
from agent.planning.complexity_models import ComplexityModel
from agent.planning.task_models import TaskModel
from llm.router import RoutingContext


def _make_context(
    task_type: TaskType,
    complexity: ComplexityLevel = ComplexityLevel.LOW,
    entities: list | None = None,
) -> ExecutionContext:
    task = TaskModel(task_type=task_type, complexity=complexity)
    task_result = TaskResult(
        task=task,
        reason="test",
        extracted_entities=entities or [],
    )
    complexity_model = ComplexityModel(level=complexity, score=0.3)
    complexity_result = ComplexityResult(
        complexity=complexity_model,
        reason="test",
    )
    routing = RoutingContext(task=task_type)
    return ExecutionContext(
        task=task_result,
        complexity=complexity_result,
        routing=routing,
    )


class TestExecutionEngine:

    @pytest.fixture(autouse=True)
    def _setup(self):
        original_registry = {
            name: StrategyRegistry.get(name)
            for name in StrategyRegistry.list_strategies()
        }
        from agent.execution.strategies import (
            DirectLLMStrategy,
            MultiStepStrategy,
            ParallelStrategy,
            RagStrategy,
            ToolCallingStrategy,
        )

        built_in_strategies = (
            ("rag", RagStrategy),
            ("direct_llm", DirectLLMStrategy),
            ("parallel", ParallelStrategy),
            ("multi_step", MultiStepStrategy),
            ("tool_calling", ToolCallingStrategy),
        )
        StrategyRegistry.clear()
        for name, strategy in built_in_strategies:
            StrategyRegistry.register(name, strategy)

        self.engine = ExecutionEngine()
        try:
            yield
        finally:
            StrategyRegistry.clear()
            for name, strategy in original_registry.items():
                StrategyRegistry.register(name, strategy)

    # =========================
    # Strategy Selection
    # =========================

    def test_direct_llm_for_chat_low(self):
        ctx = _make_context(TaskType.CHAT, ComplexityLevel.LOW)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.DIRECT_LLM
        assert "chat" in result.reason.lower()

    def test_direct_llm_for_summarization_medium(self):
        ctx = _make_context(TaskType.SUMMARIZATION, ComplexityLevel.MEDIUM)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.DIRECT_LLM

    def test_rag_for_document_qa_medium(self):
        ctx = _make_context(TaskType.DOCUMENT_QA, ComplexityLevel.MEDIUM)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.RAG
        assert result.use_retrieval is True

    def test_rag_for_financial_analysis_low(self):
        ctx = _make_context(TaskType.FINANCIAL_ANALYSIS, ComplexityLevel.LOW)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.RAG

    def test_rag_for_research_medium(self):
        ctx = _make_context(TaskType.RESEARCH, ComplexityLevel.MEDIUM)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.RAG

    def test_multi_step_for_comparison_high(self):
        ctx = _make_context(TaskType.COMPARISON, ComplexityLevel.HIGH)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.MULTI_STEP
        assert result.estimated_steps > 1

    def test_multi_step_for_financial_analysis_high(self):
        ctx = _make_context(TaskType.FINANCIAL_ANALYSIS, ComplexityLevel.HIGH)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.MULTI_STEP

    def test_parallel_for_comparison_multi_entity(self):
        ctx = _make_context(
            TaskType.COMPARISON,
            ComplexityLevel.MEDIUM,
            entities=["Apple", "Tesla"],
        )
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.PARALLEL
        assert result.parallelism >= 2

    def test_tool_calling_for_ocr(self):
        ctx = _make_context(TaskType.OCR)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.TOOL_CALLING
        assert result.use_tools is True

    def test_tool_calling_for_image_analysis(self):
        ctx = _make_context(TaskType.IMAGE_ANALYSIS)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.TOOL_CALLING

    def test_tool_calling_for_code_generation(self):
        ctx = _make_context(TaskType.CODE_GENERATION)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.TOOL_CALLING

    # =========================
    # Fallback
    # =========================

    def test_fallback_when_no_strategy_matches(self):
        ctx = _make_context(TaskType.UNKNOWN)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.DIRECT_LLM
        assert result.confidence < 1.0

    def test_custom_fallback_strategy(self):
        self.engine.set_fallback("rag")
        ctx = _make_context(TaskType.UNKNOWN)
        result = self.engine.execute(ctx)
        assert result.strategy == ExecutionStrategyType.RAG

    def test_set_fallback_raises_for_unregistered(self):
        with pytest.raises(KeyError, match="not registered"):
            self.engine.set_fallback("nonexistent")

    # =========================
    # Result fields
    # =========================

    def test_result_has_all_required_fields(self):
        ctx = _make_context(TaskType.CHAT, ComplexityLevel.LOW)
        result = self.engine.execute(ctx)
        assert isinstance(result.strategy, ExecutionStrategyType)
        assert isinstance(result.reason, str)
        assert result.estimated_steps >= 1
        assert result.parallelism >= 1
        assert isinstance(result.use_retrieval, bool)
        assert isinstance(result.use_tools, bool)
        assert 0.0 <= result.confidence <= 1.0

    # =========================
    # Priority ordering
    # =========================

    def test_priority_ordering(self):
        from agent.execution.strategies import (
            MultiStepStrategy,
            ParallelStrategy,
            RagStrategy,
        )
        r = RagStrategy()
        p = ParallelStrategy()
        m = MultiStepStrategy()
        assert r.priority > p.priority
        assert p.priority > m.priority

    # =========================
    # Regression
    # =========================

    def test_planner_imports_still_work(self):
        assert True

    def test_router_imports_still_work(self):
        assert True
