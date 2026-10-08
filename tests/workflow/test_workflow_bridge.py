# ============================================================
# test_workflow_bridge.py — Workflow → Execution Bridge Tests
# ============================================================


from agent.execution.execution_context import ExecutionContext
from agent.execution.strategy_enums import ExecutionStrategyType
from agent.planning import (
    ComplexityLevel,
    ComplexityModel,
    ComplexityResult,
    TaskModel,
    TaskResult,
    TaskType,
)
from agent.workflow.workflow_bridge import WorkflowBridge
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult
from llm.router import RoutingContext

# ============================================================
# Helpers
# ============================================================

def _make_context() -> WorkflowContext:
    task_result = TaskResult(
        task=TaskModel(task_type=TaskType.DOCUMENT_QA),
        reason="test",
    )
    complexity_result = ComplexityResult(
        complexity=ComplexityModel(level=ComplexityLevel.LOW),
        reason="test",
    )
    from agent.execution.execution_result import ExecutionResult
    exec_result = ExecutionResult(
        strategy=ExecutionStrategyType.RAG,
        reason="test",
    )
    return WorkflowContext(
        task=task_result,
        complexity=complexity_result,
        routing=RoutingContext(task=TaskType.DOCUMENT_QA),
        execution=exec_result,
    )


def _make_workflow_result(**kwargs) -> WorkflowResult:
    defaults = {
        "workflow": WorkflowType.RAG,
        "steps": [
            WorkflowStep(
                step_id="retrieve",
                name="Retrieve",
                description="retrieve docs",
                required=True,
            ),
        ],
        "estimated_time_ms": 2000,
        "requires_tools": False,
        "requires_memory": False,
        "requires_human": False,
        "confidence": 0.95,
        "reason": "test",
        "execution_strategy": ExecutionStrategyType.RAG,
        "requires_retrieval": True,
        "requires_parallel": False,
        "estimated_execution_steps": 3,
    }
    defaults.update(kwargs)
    return WorkflowResult(**defaults)


# ============================================================
# Test Class
# ============================================================

class TestWorkflowBridge:

    # ============================================================
    # Bridge.creation
    # ============================================================

    def test_bridge_creates_execution_context(self):
        ctx = _make_context()
        wr = _make_workflow_result()
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert isinstance(exec_ctx, ExecutionContext)

    # ============================================================
    # Bridge.preserves_upstream
    # ============================================================

    def test_bridge_preserves_task(self):
        ctx = _make_context()
        wr = _make_workflow_result()
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.task is ctx.task

    def test_bridge_preserves_complexity(self):
        ctx = _make_context()
        wr = _make_workflow_result()
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.complexity is ctx.complexity

    def test_bridge_preserves_routing(self):
        ctx = _make_context()
        wr = _make_workflow_result()
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.routing is ctx.routing

    # ============================================================
    # Bridge.workflow
    # ============================================================

    def test_bridge_sets_workflow_on_context(self):
        ctx = _make_context()
        wr = _make_workflow_result()
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.workflow is wr

    def test_bridge_workflow_result_has_execution_intent(self):
        ctx = _make_context()
        wr = _make_workflow_result()
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.workflow.execution_strategy == ExecutionStrategyType.RAG
        assert exec_ctx.workflow.requires_retrieval is True
        assert exec_ctx.workflow.requires_parallel is False
        assert exec_ctx.workflow.estimated_execution_steps == 3

    # ============================================================
    # Bridge.workflow_type_variations
    # ============================================================

    def test_bridge_with_direct_chat_workflow(self):
        ctx = _make_context()
        wr = _make_workflow_result(
            workflow=WorkflowType.DIRECT_CHAT,
            execution_strategy=ExecutionStrategyType.DIRECT_LLM,
            requires_retrieval=False,
            estimated_execution_steps=1,
        )
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.workflow.execution_strategy == ExecutionStrategyType.DIRECT_LLM

    def test_bridge_with_multi_step_workflow(self):
        ctx = _make_context()
        wr = _make_workflow_result(
            workflow=WorkflowType.MULTI_STEP,
            execution_strategy=ExecutionStrategyType.MULTI_STEP,
            requires_retrieval=True,
            estimated_execution_steps=5,
        )
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.workflow.execution_strategy == ExecutionStrategyType.MULTI_STEP

    def test_bridge_with_parallel_workflow(self):
        ctx = _make_context()
        wr = _make_workflow_result(
            workflow=WorkflowType.PARALLEL,
            execution_strategy=ExecutionStrategyType.PARALLEL,
            requires_retrieval=True,
            requires_parallel=True,
            estimated_execution_steps=4,
        )
        exec_ctx = WorkflowBridge.to_execution_context(ctx, wr)
        assert exec_ctx.workflow.execution_strategy == ExecutionStrategyType.PARALLEL
        assert exec_ctx.workflow.requires_parallel is True
