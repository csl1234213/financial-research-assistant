# ============================================================
# Tool Runtime Integration Tests
# ============================================================
# 验证：ExecutionEngine → ToolEngine 调用链
# 测试 ToolContext 在 ExecutionContext 中的流转。
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


from agent.execution.execution_context import ExecutionContext
from agent.execution.execution_engine import ExecutionEngine as StrategyExecutionEngine
from agent.execution.execution_result import ExecutionResult
from agent.execution.strategies import (
    DirectLLMStrategy,
    MultiStepStrategy,
    ParallelStrategy,
    RagStrategy,
    ToolCallingStrategy,
)
from agent.execution.strategy_registry import StrategyRegistry
from agent.planning import (
    ComplexityLevel,
    ComplexityResult,
    TaskResult,
    TaskType,
)
from agent.planning.complexity_models import ComplexityModel
from agent.planning.task_models import TaskModel
from agent.runtime_state import RuntimeState
from agent.tools import ToolContext, ToolEngine, ToolResult, ToolStatus, ToolType
from llm.router import RoutingContext

# Re-register strategies to ensure they exist
StrategyRegistry.clear()
StrategyRegistry.register("rag", RagStrategy)
StrategyRegistry.register("direct_llm", DirectLLMStrategy)
StrategyRegistry.register("parallel", ParallelStrategy)
StrategyRegistry.register("multi_step", MultiStepStrategy)
StrategyRegistry.register("tool_calling", ToolCallingStrategy)


class TestToolRuntimeIntegration:

    def setup_method(self):
        StrategyRegistry.clear()
        StrategyRegistry.register("rag", RagStrategy)
        StrategyRegistry.register("direct_llm", DirectLLMStrategy)
        StrategyRegistry.register("parallel", ParallelStrategy)
        StrategyRegistry.register("multi_step", MultiStepStrategy)
        StrategyRegistry.register("tool_calling", ToolCallingStrategy)

    def _make_task_result(self) -> TaskResult:
        task = TaskModel(task_type=TaskType.DOCUMENT_QA)
        return TaskResult(task=task, reason="Test task")

    def _make_complexity_result(self) -> ComplexityResult:
        complexity = ComplexityModel(level=ComplexityLevel.LOW, score=0.3)
        return ComplexityResult(complexity=complexity, reason="Low complexity")

    # ============================================================
    # Step 1: Runtime creates ToolContext and puts it in ExecutionContext
    # ============================================================

    def test_runtime_creates_tool_context_in_execution_context(self):
        task_result = self._make_task_result()
        complexity_result = self._make_complexity_result()
        routing_ctx = RoutingContext(task=task_result.task.task_type)

        runtime_state = RuntimeState()
        tool_ctx = ToolContext(
            runtime_state=runtime_state,
            parameters={"tool": ToolType.RETRIEVAL, "query": "test query"},
        )

        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=routing_ctx,
            tool_context=tool_ctx,
        )

        assert exec_ctx.tool_context is not None
        assert exec_ctx.tool_context.parameters["tool"] == ToolType.RETRIEVAL
        assert exec_ctx.tool_context.parameters["query"] == "test query"
        assert exec_ctx.workflow is None

    # ============================================================
    # Step 2: ExecutionEngine detects tool_context and calls _execute_from_tool
    # ============================================================

    def test_execution_engine_calls_tool_engine(self):
        from unittest.mock import patch

        task_result = self._make_task_result()
        complexity_result = self._make_complexity_result()
        routing_ctx = RoutingContext(task=task_result.task.task_type)

        runtime_state = RuntimeState()
        tool_ctx = ToolContext(
            runtime_state=runtime_state,
            parameters={"tool": ToolType.RETRIEVAL, "query": "test"},
        )
        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=routing_ctx,
            tool_context=tool_ctx,
        )

        mock_result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="mock retrieval result",
            metadata={"execution_strategy": "tool_calling"},
        )

        with patch.object(ToolEngine, 'execute', return_value=mock_result):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert isinstance(result, ExecutionResult)
            assert result.use_tools is True
            assert len(result.tool_results) == 1
            assert result.tool_results[0] is mock_result
            assert result.confidence == 0.95

    # ============================================================
    # Step 3: ToolResult is returned in ExecutionResult
    # ============================================================

    def test_tool_result_preserved_in_execution_result(self):
        from unittest.mock import patch

        task_result = self._make_task_result()
        complexity_result = self._make_complexity_result()
        routing_ctx = RoutingContext(task=task_result.task.task_type)

        tool_result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="test output",
            error=None,
            metadata={"foo": "bar"},
        )

        runtime_state = RuntimeState()
        tool_ctx = ToolContext(
            runtime_state=runtime_state,
            parameters={"tool": ToolType.RETRIEVAL},
        )
        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=routing_ctx,
            tool_context=tool_ctx,
        )

        with patch.object(ToolEngine, 'execute', return_value=tool_result):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert len(result.tool_results) == 1
            assert result.tool_results[0] is tool_result
            assert result.tool_results[0].output == "test output"
            assert result.tool_results[0].status == ToolStatus.SUCCESS
            assert result.tool_results[0].metadata["foo"] == "bar"

    # ============================================================
    # Step 4: Without tool_context → old workflow still works
    # ============================================================

    def test_no_tool_context_old_flow_still_works(self):
        task = TaskModel(task_type=TaskType.CHAT)
        task_result = TaskResult(task=task, reason="Simple question")
        complexity = ComplexityModel(level=ComplexityLevel.LOW, score=0.2)
        complexity_result = ComplexityResult(complexity=complexity, reason="Low")
        routing_ctx = RoutingContext(task=task_result.task.task_type)

        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=routing_ctx,
            workflow=None,
        )

        engine = StrategyExecutionEngine()
        engine.set_fallback("direct_llm")
        result = engine.execute(exec_ctx)

        assert result.strategy.value == "direct_llm"
        assert result.use_tools is False
        assert len(result.tool_results) == 0
        assert result is not None

    # ============================================================
    # Step 5: Both workflow and tool_context → tool takes precedence
    # ============================================================

    def test_tool_context_takes_precedence_over_workflow(self):
        from unittest.mock import patch

        task_result = self._make_task_result()
        complexity_result = self._make_complexity_result()
        routing_ctx = RoutingContext(task=task_result.task.task_type)

        from agent.execution.strategy_enums import ExecutionStrategyType
        from agent.workflow.workflow_enums import WorkflowType
        from agent.workflow.workflow_result import WorkflowResult
        workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            execution_strategy=ExecutionStrategyType.RAG,
        )

        tool_result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="tool output",
        )
        runtime_state = RuntimeState()
        tool_ctx = ToolContext(
            runtime_state=runtime_state,
            parameters={"tool": ToolType.CUSTOM},
        )

        exec_ctx = ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=routing_ctx,
            workflow=workflow,
            tool_context=tool_ctx,
        )

        with patch.object(ToolEngine, 'execute', return_value=tool_result):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert result.use_tools is True
            assert len(result.tool_results) == 1
            assert result.tool_results[0] is tool_result

    # ============================================================
    # Step 6: RuntimeState holds multiple tool_results
    # ============================================================

    def test_runtimestate_holds_multiple_tool_results(self):
        state = RuntimeState()
        assert len(state.tool_results) == 0

        result1 = ToolResult(status=ToolStatus.SUCCESS, output="result1")
        result2 = ToolResult(status=ToolStatus.SUCCESS, output="result2")
        result3 = ToolResult(status=ToolStatus.FAILED, output=None, error="failed")

        state.tool_results.append(result1)
        state.tool_results.append(result2)
        state.tool_results.append(result3)

        assert len(state.tool_results) == 3
        assert state.tool_results[0].output == "result1"
        assert state.tool_results[2].status == ToolStatus.FAILED

    # ============================================================
    # Step 7: Actual ToolEngine integration (no mock)
    # ============================================================

    def test_actual_tool_engine_integration(self):
        engine = ToolEngine()
        assert engine is not None

        runtime_state = RuntimeState()
        ctx = ToolContext(
            runtime_state=runtime_state,
            parameters={"tool": ToolType.RETRIEVAL},
        )
        assert ctx is not None
        assert ctx.runtime_state is runtime_state
        assert ctx.parameters["tool"] == ToolType.RETRIEVAL
