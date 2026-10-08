# ============================================================
# test_workflow_runtime.py — Workflow Runtime Integration Tests
# ============================================================

from unittest.mock import MagicMock, patch

from agent.agent_runtime import AgentRuntime
from agent.execution.execution_engine import ExecutionEngine as StrategyExecutionEngine
from agent.execution.execution_result import ExecutionResult
from agent.execution.strategy_enums import ExecutionStrategyType
from agent.planning import (
    ComplexityLevel,
    ComplexityModel,
    ComplexityResult,
    TaskModel,
    TaskResult,
    TaskType,
)
from agent.runtime_result import RuntimeResult
from agent.runtime_state import RuntimeState
from agent.workflow.workflow_engine import WorkflowEngine
from agent.workflow.workflow_enums import WorkflowStatus, WorkflowType
from agent.workflow.workflow_executor import WorkflowExecutor
from agent.workflow.workflow_result import WorkflowResult
from llm.router import RoutingContext

# ============================================================
# Helpers
# ============================================================

def _make_task_result() -> TaskResult:
    return TaskResult(
        task=TaskModel(task_type=TaskType.DOCUMENT_QA),
        reason="test",
    )


def _make_complexity_result() -> ComplexityResult:
    return ComplexityResult(
        complexity=ComplexityModel(level=ComplexityLevel.LOW),
        reason="test",
    )


def _make_routing_context() -> RoutingContext:
    return RoutingContext(task=TaskType.DOCUMENT_QA)


def _make_execution_result(
    strategy: ExecutionStrategyType = ExecutionStrategyType.RAG,
) -> ExecutionResult:
    return ExecutionResult(
        strategy=strategy,
        reason="test",
        estimated_steps=3,
    )


# ============================================================
# Test Class
# ============================================================

class TestWorkflowRuntime:

    # ============================================================
    # Runtime creates workflow
    # ============================================================

    @patch.object(AgentRuntime, "run", autospec=True)
    def test_runtime_creates_workflow(self, mock_run):
        mock_run.return_value = RuntimeResult(workflow={"type": "rag", "status": "DONE"})
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.workflow_engine = WorkflowEngine()
        runtime.workflow_executor = WorkflowExecutor()
        assert runtime.workflow_engine is not None
        assert runtime.workflow_executor is not None

    def test_runtime_has_workflow_defaults(self):
        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
        )
        assert isinstance(runtime.workflow_engine, WorkflowEngine)
        assert isinstance(runtime.workflow_executor, WorkflowExecutor)

    # ============================================================
    # WorkflowEngine is called
    # ============================================================

    def test_workflow_engine_build_is_called(self):
        workflow_engine = MagicMock(spec=WorkflowEngine)
        workflow_result = WorkflowResult(
            workflow=WorkflowType.RAG,
            execution_strategy=ExecutionStrategyType.RAG,
        )
        workflow_engine.build.return_value = workflow_result

        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_result = _make_execution_result(ExecutionStrategyType.RAG)
        strategy_engine.execute.return_value = strategy_result

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=workflow_engine,
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        runtime.run("test question")

        workflow_engine.build.assert_called_once()

    # ============================================================
    # WorkflowExecutor is called
    # ============================================================

    def test_workflow_executor_execute_is_called(self):
        workflow_engine = MagicMock(spec=WorkflowEngine)
        workflow_result = WorkflowResult(
            workflow=WorkflowType.RAG,
            execution_strategy=ExecutionStrategyType.RAG,
        )
        workflow_engine.build.return_value = workflow_result

        workflow_executor = MagicMock(spec=WorkflowExecutor)
        workflow_executor.execute.return_value = workflow_result

        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_result = _make_execution_result(ExecutionStrategyType.RAG)
        strategy_engine.execute.return_value = strategy_result

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=workflow_engine,
            workflow_executor=workflow_executor,
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        runtime.run("test question")

        workflow_executor.execute.assert_called_once()

    # ============================================================
    # ExecutionEngine is called by workflow
    # ============================================================

    def test_strategy_engine_called_by_workflow_executor(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_result = _make_execution_result(ExecutionStrategyType.RAG)
        strategy_engine.execute.return_value = strategy_result

        workflow_engine = WorkflowEngine()
        workflow_executor = WorkflowExecutor()

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=workflow_engine,
            workflow_executor=workflow_executor,
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        runtime.run("test question")

        assert strategy_engine.execute.call_count >= 2

    # ============================================================
    # DirectChat full pipeline
    # ============================================================

    def test_direct_chat_full_pipeline(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_engine.execute.return_value = _make_execution_result(
            ExecutionStrategyType.DIRECT_LLM,
        )

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=WorkflowEngine(),
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        result = runtime.run("test question")

        assert result.workflow is not None
        assert result.workflow["type"] == WorkflowType.DIRECT_CHAT.value
        assert result.workflow["status"] == WorkflowStatus.DONE.value
        assert result.workflow["completed_steps"] == 1
        assert result.workflow["total_steps"] == 1

    # ============================================================
    # RAG full pipeline
    # ============================================================

    def test_rag_full_pipeline(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_engine.execute.return_value = _make_execution_result(
            ExecutionStrategyType.RAG,
        )

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=WorkflowEngine(),
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        result = runtime.run("test question")

        assert result.workflow is not None
        assert result.workflow["type"] == WorkflowType.RAG.value
        assert result.workflow["status"] == WorkflowStatus.DONE.value
        assert result.workflow["completed_steps"] == 3
        assert result.workflow["total_steps"] == 3

    # ============================================================
    # Research (multi_step) full pipeline
    # ============================================================

    def test_research_full_pipeline(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_engine.execute.return_value = _make_execution_result(
            ExecutionStrategyType.MULTI_STEP,
        )

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=WorkflowEngine(),
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        result = runtime.run("test question")

        assert result.workflow is not None
        assert result.workflow["type"] == WorkflowType.MULTI_STEP.value
        assert result.workflow["status"] == WorkflowStatus.DONE.value
        assert result.workflow["completed_steps"] == 5
        assert result.workflow["total_steps"] == 5

    # ============================================================
    # Comparison (parallel) full pipeline
    # ============================================================

    def test_comparison_full_pipeline(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_engine.execute.return_value = _make_execution_result(
            ExecutionStrategyType.PARALLEL,
        )

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=WorkflowEngine(),
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        result = runtime.run("test question")

        assert result.workflow is not None
        assert result.workflow["type"] == WorkflowType.PARALLEL.value
        assert result.workflow["status"] == WorkflowStatus.DONE.value
        assert result.workflow["completed_steps"] == 4
        assert result.workflow["total_steps"] == 4

    # ============================================================
    # Workflow status is correct
    # ============================================================

    def test_workflow_status_done(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_engine.execute.return_value = _make_execution_result(
            ExecutionStrategyType.RAG,
        )

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=WorkflowEngine(),
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        result = runtime.run("test question")

        assert result.workflow["status"] == WorkflowStatus.DONE.value

    # ============================================================
    # RuntimeResult includes workflow
    # ============================================================

    def test_runtime_result_includes_workflow(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_engine.execute.return_value = _make_execution_result(
            ExecutionStrategyType.RAG,
        )

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=WorkflowEngine(),
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        result = runtime.run("test question")

        assert isinstance(result, RuntimeResult)
        assert result.workflow is not None
        assert "type" in result.workflow
        assert "status" in result.workflow
        assert "completed_steps" in result.workflow

    # ============================================================
    # Workflow info has all expected keys
    # ============================================================

    def test_workflow_info_keys(self):
        strategy_engine = MagicMock(spec=StrategyExecutionEngine)
        strategy_engine.execute.return_value = _make_execution_result(
            ExecutionStrategyType.RAG,
        )

        runtime = AgentRuntime(
            planner=MagicMock(),
            executor=MagicMock(),
            reasoner=MagicMock(),
            retriever=MagicMock(),
            intent_analyzer=MagicMock(),
            strategy_engine=strategy_engine,
            workflow_engine=WorkflowEngine(),
            workflow_executor=WorkflowExecutor(),
        )

        task_result = _make_task_result()
        complexity_result = _make_complexity_result()
        routing_context = _make_routing_context()

        runtime.planner.plan.return_value = (MagicMock(), task_result, complexity_result)
        runtime.planner.build_routing_context.return_value = routing_context

        result = runtime.run("test question")

        expected_keys = {
            "type", "status", "completed_steps", "total_steps",
            "estimated_time_ms", "confidence", "reason",
        }
        assert set(result.workflow.keys()) == expected_keys

    # ============================================================
    # RuntimeState
    # ============================================================

    def test_runtime_state_creation(self):
        state = RuntimeState()
        assert state.workflow is None
        assert state.execution == []
        assert state.routing == []
        assert state.outputs == []

    def test_runtime_state_with_workflow(self):
        wr = WorkflowResult(
            workflow=WorkflowType.RAG,
            execution_strategy=ExecutionStrategyType.RAG,
        )
        state = RuntimeState(workflow=wr)
        assert state.workflow is wr
        assert state.workflow.workflow == WorkflowType.RAG
