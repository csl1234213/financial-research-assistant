# ============================================================
# V5 Phase 4 Sprint 1 Step 3 — WorkflowEngine Tests
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import patch

import pytest

from agent.execution import ExecutionResult, ExecutionStrategyType
from agent.planning import (
    ComplexityLevel,
    ComplexityResult,
    TaskResult,
    TaskType,
)
from agent.planning.complexity_models import ComplexityModel
from agent.planning.task_models import TaskModel
from agent.workflow import (
    WorkflowContext,
    WorkflowEngine,
    WorkflowFactory,
    WorkflowRegistry,
    WorkflowResult,
    WorkflowType,
)
from llm.router import RoutingContext

# ============================================================
# Fixtures
# ============================================================

def _make_context(
    strategy: ExecutionStrategyType = ExecutionStrategyType.RAG,
    task_type: TaskType = TaskType.DOCUMENT_QA,
) -> WorkflowContext:
    return WorkflowContext(
        task=TaskResult(
            task=TaskModel(task_type=task_type),
            reason="test",
        ),
        complexity=ComplexityResult(
            complexity=ComplexityModel(level=ComplexityLevel.LOW),
            reason="test",
        ),
        execution=ExecutionResult(
            strategy=strategy,
            reason="test",
        ),
        routing=RoutingContext(task=task_type),
    )


# ============================================================
# Test Class
# ============================================================

class TestWorkflowEngine:

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.engine = WorkflowEngine()
        yield

    # ============================================================
    # 1. Engine 创建成功
    # ============================================================

    def test_engine_creates_successfully(self):
        assert isinstance(self.engine, WorkflowEngine)

    # ============================================================
    # 2. DirectChatWorkflow build
    # ============================================================

    def test_direct_chat_workflow(self):
        ctx = _make_context(strategy=ExecutionStrategyType.DIRECT_LLM)
        result = self.engine.build(ctx)

        assert isinstance(result, WorkflowResult)
        assert result.workflow == WorkflowType.DIRECT_CHAT
        assert len(result.steps) == 1
        assert result.steps[0].step_id == "chat"
        assert result.confidence > 0

    # ============================================================
    # 3. RAGWorkflow build
    # ============================================================

    def test_rag_workflow(self):
        ctx = _make_context(strategy=ExecutionStrategyType.RAG)
        result = self.engine.build(ctx)

        assert isinstance(result, WorkflowResult)
        assert result.workflow == WorkflowType.RAG
        assert len(result.steps) == 3
        assert result.steps[0].step_id == "retrieve"
        assert result.steps[1].step_id == "reason"
        assert result.steps[2].step_id == "answer"
        assert result.confidence > 0

    # ============================================================
    # 4. ResearchWorkflow build (via MULTI_STEP)
    # ============================================================

    def test_research_workflow(self):
        ctx = _make_context(strategy=ExecutionStrategyType.MULTI_STEP)
        result = self.engine.build(ctx)

        assert isinstance(result, WorkflowResult)
        assert result.workflow == WorkflowType.MULTI_STEP
        assert len(result.steps) == 5
        assert result.steps[0].step_id == "plan"
        assert result.steps[4].step_id == "verify"

    # ============================================================
    # 5. ComparisonWorkflow build (via PARALLEL)
    # ============================================================

    def test_comparison_workflow(self):
        ctx = _make_context(strategy=ExecutionStrategyType.PARALLEL)
        result = self.engine.build(ctx)

        assert isinstance(result, WorkflowResult)
        assert result.workflow == WorkflowType.PARALLEL
        assert len(result.steps) == 4
        assert result.steps[0].step_id == "retrieve_a"
        assert result.steps[1].step_id == "retrieve_b"

    # ============================================================
    # 6. TOOL_CALLING → TOOL_PIPELINE
    # ============================================================

    def test_tool_calling_maps_to_single_execution_tool_pipeline(self):
        ctx = _make_context(strategy=ExecutionStrategyType.TOOL_CALLING)
        result = self.engine.build(ctx)

        assert result.workflow == WorkflowType.TOOL_PIPELINE
        assert len(result.steps) == 1
        assert result.steps[0].metadata == {
            "strategy": "tool_calling",
        }
        assert result.requires_retrieval is False

    # ============================================================
    # 7. Unknown strategy → fallback to DIRECT_CHAT
    # ============================================================

    def test_unknown_strategy_falls_back(self):
        ctx = _make_context(strategy=ExecutionStrategyType.HYBRID)
        result = self.engine.build(ctx)

        assert result.workflow == WorkflowType.MULTI_STEP

    # ============================================================
    # 8. WorkflowResult 正确返回（包含 next_workflow）
    # ============================================================

    def test_workflow_result_fields(self):
        ctx = _make_context(strategy=ExecutionStrategyType.RAG)
        result = self.engine.build(ctx)

        assert result.workflow is not None
        assert isinstance(result.steps, list)
        assert len(result.steps) > 0
        assert result.estimated_time_ms > 0
        assert result.confidence > 0
        assert result.reason != ""
        assert result.next_workflow is None
        assert not result.requires_tools

    # ============================================================
    # 9. Engine 不直接创建 Workflow（通过 Factory）
    # ============================================================

    def test_engine_uses_factory_not_direct_instantiation(self):
        ctx = _make_context(strategy=ExecutionStrategyType.RAG)

        with patch.object(
            WorkflowFactory, "create", wraps=WorkflowFactory.create
        ) as mock_create:
            result = self.engine.build(ctx)
            assert result is not None
            mock_create.assert_called_once_with(WorkflowType.RAG)

    # ============================================================
    # 10. Factory 调用 Registry
    # ============================================================

    def test_factory_calls_registry(self):
        ctx = _make_context(strategy=ExecutionStrategyType.RAG)

        with patch.object(
            WorkflowRegistry, "get", wraps=WorkflowRegistry.get
        ) as mock_get:
            result = self.engine.build(ctx)
            assert result is not None
            mock_get.assert_called()

    # ============================================================
    # 11. Engine 不包含 Provider 调用
    # ============================================================

    def test_engine_has_no_provider_dependency(self):
        import inspect

        source = inspect.getsource(WorkflowEngine)
        assert "Provider" not in source
        assert "provider" not in source
        assert "from llm" not in source
        assert "import llm" not in source

    # ============================================================
    # 12. WorkflowStep 依赖关系正确
    # ============================================================

    def test_rag_workflow_step_dependencies(self):
        ctx = _make_context(strategy=ExecutionStrategyType.RAG)
        result = self.engine.build(ctx)

        retrieve = result.steps[0]
        reason = result.steps[1]
        answer = result.steps[2]

        assert retrieve.depends_on == []
        assert reason.depends_on == ["retrieve"]
        assert answer.depends_on == ["reason"]

    def test_research_workflow_step_dependencies(self):
        ctx = _make_context(strategy=ExecutionStrategyType.MULTI_STEP)
        result = self.engine.build(ctx)

        plan = result.steps[0]
        retrieve = result.steps[1]
        analyze = result.steps[2]
        synthesize = result.steps[3]
        verify = result.steps[4]

        assert plan.depends_on == []
        assert retrieve.depends_on == ["plan"]
        assert analyze.depends_on == ["retrieve"]
        assert synthesize.depends_on == ["analyze"]
        assert verify.depends_on == ["synthesize"]

    def test_comparison_workflow_step_dependencies(self):
        ctx = _make_context(strategy=ExecutionStrategyType.PARALLEL)
        result = self.engine.build(ctx)

        retrieve_a = result.steps[0]
        retrieve_b = result.steps[1]
        compare = result.steps[2]
        synthesize = result.steps[3]

        assert retrieve_a.depends_on == []
        assert retrieve_b.depends_on == []
        assert compare.depends_on == ["retrieve_a", "retrieve_b"]
        assert synthesize.depends_on == ["compare"]

    # ============================================================
    # 13. 每个 strategy 都能正确映射
    # ============================================================

    @pytest.mark.parametrize("strategy,expected_workflow", [
        (ExecutionStrategyType.DIRECT_LLM, WorkflowType.DIRECT_CHAT),
        (ExecutionStrategyType.RAG, WorkflowType.RAG),
        (ExecutionStrategyType.MULTI_STEP, WorkflowType.MULTI_STEP),
        (ExecutionStrategyType.PARALLEL, WorkflowType.PARALLEL),
        (ExecutionStrategyType.TOOL_CALLING, WorkflowType.TOOL_PIPELINE),
        (ExecutionStrategyType.MULTI_DOCUMENT, WorkflowType.RAG),
        (ExecutionStrategyType.HYBRID, WorkflowType.MULTI_STEP),
        (ExecutionStrategyType.AGENT_WORKFLOW, WorkflowType.MULTI_STEP),
    ])
    def test_strategy_to_workflow_mapping(self, strategy, expected_workflow):
        ctx = _make_context(strategy=strategy)
        result = self.engine.build(ctx)
        assert result.workflow == expected_workflow, (
            f"{strategy} → {result.workflow}, expected {expected_workflow}"
        )
