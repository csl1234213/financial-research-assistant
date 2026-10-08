# ============================================================
# Workflow Tool Invocation Tests
# ============================================================
# 验证：WorkflowStep → ToolBridge → ToolEngine → ToolResult
# 测试 Workflow 声明式 Tool 驱动执行。
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
from agent.execution.strategy_enums import ExecutionStrategyType
from agent.execution.strategy_registry import StrategyRegistry
from agent.planning import (
    ComplexityLevel,
    ComplexityResult,
    TaskResult,
    TaskType,
)
from agent.planning.complexity_models import ComplexityModel
from agent.planning.task_models import TaskModel
from agent.tools import ToolBridge, ToolContext, ToolEngine, ToolResult, ToolStatus
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult
from llm.router import RoutingContext

StrategyRegistry.clear()
StrategyRegistry.register("rag", RagStrategy)
StrategyRegistry.register("direct_llm", DirectLLMStrategy)
StrategyRegistry.register("parallel", ParallelStrategy)
StrategyRegistry.register("multi_step", MultiStepStrategy)
StrategyRegistry.register("tool_calling", ToolCallingStrategy)


class TestWorkflowToolInvocation:

    def setup_method(self):
        StrategyRegistry.clear()
        StrategyRegistry.register("rag", RagStrategy)
        StrategyRegistry.register("direct_llm", DirectLLMStrategy)
        StrategyRegistry.register("parallel", ParallelStrategy)
        StrategyRegistry.register("multi_step", MultiStepStrategy)
        StrategyRegistry.register("tool_calling", ToolCallingStrategy)

    def _make_exec_context(self, workflow=None):
        task = TaskModel(task_type=TaskType.DOCUMENT_QA)
        task_result = TaskResult(task=task, reason="Test")
        complexity = ComplexityModel(level=ComplexityLevel.LOW, score=0.3)
        complexity_result = ComplexityResult(complexity=complexity, reason="Low")
        routing_ctx = RoutingContext(task=task_result.task.task_type)
        return ExecutionContext(
            task=task_result,
            complexity=complexity_result,
            routing=routing_ctx,
            workflow=workflow,
        )

    def _make_workflow_context(self):
        task = TaskModel(task_type=TaskType.DOCUMENT_QA)
        task_result = TaskResult(task=task, reason="Test")
        complexity = ComplexityModel(level=ComplexityLevel.LOW, score=0.3)
        complexity_result = ComplexityResult(complexity=complexity, reason="Low")
        routing_ctx = RoutingContext(task=task_result.task.task_type)
        execution = ExecutionResult(
            strategy=ExecutionStrategyType.RAG,
            reason="Test",
        )
        return WorkflowContext(
            task=task_result,
            complexity=complexity_result,
            execution=execution,
            routing=routing_ctx,
        )

    # ============================================================
    # 1. WorkflowStep contains tool metadata (nested format)
    # ============================================================

    def test_workflow_step_has_tool_metadata_nested(self):
        step = WorkflowStep(
            step_id="retrieve",
            name="Retrieve",
            description="Retrieve documents",
            metadata={
                "tool": {
                    "name": "retrieval",
                    "parameters": {"top_k": 5},
                }
            },
        )
        assert ToolBridge.has_tool(step) is True
        assert ToolBridge.get_tool_name(step) == "retrieval"
        assert ToolBridge.get_tool_parameters(step) == {"top_k": 5}

    def test_workflow_step_has_tool_metadata_flat(self):
        step = WorkflowStep(
            step_id="search",
            name="Search",
            description="Search documents",
            metadata={"tool": "retrieval"},
        )
        assert ToolBridge.has_tool(step) is True
        assert ToolBridge.get_tool_name(step) == "retrieval"
        assert ToolBridge.get_tool_parameters(step) == {}

    def test_workflow_step_no_tool_metadata(self):
        step = WorkflowStep(
            step_id="reason",
            name="Reason",
            description="Reason over evidence",
            metadata={"strategy": "rag"},
        )
        assert ToolBridge.has_tool(step) is False
        assert ToolBridge.get_tool_name(step) is None

    # ============================================================
    # 2. ToolBridge converts WorkflowStep → ToolContext
    # ============================================================

    def test_tool_bridge_to_tool_context(self):
        step = WorkflowStep(
            step_id="retrieve",
            name="Retrieve",
            description="Retrieve documents",
            metadata={
                "tool": {
                    "name": "retrieval",
                    "parameters": {"top_k": 5, "threshold": 0.75},
                }
            },
        )
        ctx = ToolBridge.to_tool_context(step)
        assert isinstance(ctx, ToolContext)
        assert ctx.parameters["top_k"] == 5
        assert ctx.parameters["threshold"] == 0.75
        assert ctx.parameters["step_id"] == "retrieve"
        assert ctx.parameters["step_name"] == "Retrieve"

    # ============================================================
    # 3. ExecutionEngine calls ToolEngine for steps with tool
    # ============================================================

    def test_execution_engine_calls_tool_for_step(self):
        from unittest.mock import patch

        workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            steps=[
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve documents",
                    metadata={
                        "strategy": "rag",
                        "tool": {
                            "name": "retrieval",
                            "parameters": {"top_k": 5},
                        },
                    },
                ),
                WorkflowStep(
                    step_id="reason",
                    name="Reason",
                    description="Reason over evidence",
                    metadata={"strategy": "rag"},
                ),
            ],
            execution_strategy=ExecutionStrategyType.RAG,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        mock_result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="mock retrieval result",
        )

        with patch.object(ToolEngine, 'execute', return_value=mock_result):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert isinstance(result, ExecutionResult)
            assert len(result.tool_results) == 1
            assert result.tool_results[0] is mock_result

    # ============================================================
    # 4. ToolResult is preserved in ExecutionResult
    # ============================================================

    def test_tool_result_preserved(self):
        from unittest.mock import patch

        workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            steps=[
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve documents",
                    metadata={
                        "tool": {
                            "name": "retrieval",
                            "parameters": {"top_k": 10},
                        },
                    },
                ),
            ],
            execution_strategy=ExecutionStrategyType.RAG,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        tool_result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="Retrieved 10 documents",
            metadata={"doc_count": 10},
        )

        with patch.object(ToolEngine, 'execute', return_value=tool_result):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert len(result.tool_results) == 1
            assert result.tool_results[0].output == "Retrieved 10 documents"
            assert result.tool_results[0].metadata["doc_count"] == 10

    # ============================================================
    # 5. Workflow with no tool steps — backward compatible
    # ============================================================

    def test_no_tool_steps_works(self):
        workflow = WorkflowResult(
            workflow=WorkflowType.DIRECT_CHAT,
            steps=[
                WorkflowStep(
                    step_id="chat",
                    name="Direct Chat",
                    description="Simple chat",
                    metadata={"strategy": "direct_llm"},
                ),
            ],
            execution_strategy=ExecutionStrategyType.DIRECT_LLM,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        engine = StrategyExecutionEngine()
        engine.set_fallback("direct_llm")
        result = engine.execute(exec_ctx)

        assert isinstance(result, ExecutionResult)
        assert len(result.tool_results) == 0

    # ============================================================
    # 6. Multiple tool steps in one workflow
    # ============================================================

    def test_multiple_tool_steps(self):
        from unittest.mock import patch

        workflow = WorkflowResult(
            workflow=WorkflowType.PARALLEL,
            steps=[
                WorkflowStep(
                    step_id="retrieve_a",
                    name="Retrieve A",
                    description="Retrieve A",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"entity": "A"}},
                    },
                ),
                WorkflowStep(
                    step_id="retrieve_b",
                    name="Retrieve B",
                    description="Retrieve B",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"entity": "B"}},
                    },
                ),
                WorkflowStep(
                    step_id="compare",
                    name="Compare",
                    description="Compare",
                    metadata={"strategy": "parallel"},
                ),
            ],
            execution_strategy=ExecutionStrategyType.PARALLEL,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        result_a = ToolResult(status=ToolStatus.SUCCESS, output="results A")
        result_b = ToolResult(status=ToolStatus.SUCCESS, output="results B")

        with patch.object(ToolEngine, 'execute', side_effect=[result_a, result_b]):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert len(result.tool_results) == 2
            assert result.tool_results[0] is result_a
            assert result.tool_results[1] is result_b

    # ============================================================
    # 7. Tool parameters are passed through correctly
    # ============================================================

    def test_tool_parameters_passed_through(self):
        from unittest.mock import patch

        workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            steps=[
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve",
                    metadata={
                        "tool": {
                            "name": "retrieval",
                            "parameters": {"top_k": 15, "threshold": 0.8},
                        },
                    },
                ),
            ],
            execution_strategy=ExecutionStrategyType.RAG,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        with patch.object(ToolEngine, 'execute', return_value=ToolResult(
            status=ToolStatus.SUCCESS, output="ok"
        )) as mock_execute:
            engine = StrategyExecutionEngine()
            engine.execute(exec_ctx)

            mock_execute.assert_called_once()
            args, kwargs = mock_execute.call_args
            context_arg = args[0]
            assert isinstance(context_arg, ToolContext)
            assert context_arg.parameters["top_k"] == 15
            assert context_arg.parameters["threshold"] == 0.8
            assert context_arg.parameters["step_id"] == "retrieve"
            assert context_arg.parameters["step_name"] == "Retrieve"

    # ============================================================
    # 8. Empty workflow steps — no crash
    # ============================================================

    def test_empty_workflow_steps(self):
        workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            steps=[],
            execution_strategy=ExecutionStrategyType.RAG,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        engine = StrategyExecutionEngine()
        engine.set_fallback("rag")
        result = engine.execute(exec_ctx)

        assert isinstance(result, ExecutionResult)
        assert len(result.tool_results) == 0

    # ============================================================
    # 9. WorkflowResult holds tool_results
    # ============================================================

    def test_workflow_result_holds_tool_results(self):
        wr = WorkflowResult(
            workflow=WorkflowType.RAG,
            steps=[],
            execution_strategy=ExecutionStrategyType.RAG,
        )
        assert len(wr.tool_results) == 0

        wr.tool_results.append(
            ToolResult(status=ToolStatus.SUCCESS, output="doc1")
        )
        wr.tool_results.append(
            ToolResult(status=ToolStatus.SUCCESS, output="doc2")
        )
        assert len(wr.tool_results) == 2
        assert wr.tool_results[0].output == "doc1"
        assert wr.tool_results[1].output == "doc2"

    # ============================================================
    # 10. Old workflow (no tool in metadata) still produces results
    # ============================================================

    def test_old_workflow_still_works(self):
        workflow = WorkflowResult(
            workflow=WorkflowType.RAG,
            steps=[
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve",
                    metadata={"strategy": "rag"},
                ),
                WorkflowStep(
                    step_id="answer",
                    name="Answer",
                    description="Answer",
                    metadata={"strategy": "rag"},
                ),
            ],
            execution_strategy=ExecutionStrategyType.RAG,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        engine = StrategyExecutionEngine()
        result = engine.execute(exec_ctx)

        assert isinstance(result, ExecutionResult)
        assert result.strategy.value == "rag"
        assert len(result.tool_results) == 0

    # ============================================================
    # 11. Research workflow with tool metadata
    # ============================================================

    def test_research_workflow_with_tool_metadata(self):
        from unittest.mock import patch

        workflow = WorkflowResult(
            workflow=WorkflowType.MULTI_STEP,
            steps=[
                WorkflowStep(
                    step_id="plan",
                    name="Plan",
                    description="Plan research",
                    metadata={"strategy": "multi_step"},
                ),
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve documents",
                    metadata={
                        "tool": {
                            "name": "retrieval",
                            "parameters": {"top_k": 10, "threshold": 0.7},
                        },
                    },
                ),
                WorkflowStep(
                    step_id="analyze",
                    name="Analyze",
                    description="Analyze evidence",
                    metadata={
                        "tool": {
                            "name": "python",
                            "parameters": {"mode": "analysis"},
                        },
                    },
                ),
                WorkflowStep(
                    step_id="synthesize",
                    name="Synthesize",
                    description="Synthesize findings",
                    metadata={"strategy": "multi_step"},
                ),
            ],
            execution_strategy=ExecutionStrategyType.MULTI_STEP,
        )
        exec_ctx = self._make_exec_context(workflow=workflow)

        result_retrieval = ToolResult(status=ToolStatus.SUCCESS, output="retrieved")
        result_analysis = ToolResult(status=ToolStatus.SUCCESS, output="analyzed")

        with patch.object(ToolEngine, 'execute', side_effect=[result_retrieval, result_analysis]):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert len(result.tool_results) == 2
            assert result.tool_results[0] is result_retrieval
            assert result.tool_results[1] is result_analysis

    # ============================================================
    # 12. Verifies RAG Workflow skeleton has tool metadata
    # ============================================================

    def test_rag_workflow_skeleton_has_tool(self):
        from agent.workflow.workflows.rag_workflow import RAGWorkflow

        wf = RAGWorkflow()
        result = wf.build(self._make_workflow_context())
        assert result.workflow == WorkflowType.RAG

        retrieve_step = result.steps[0]
        assert ToolBridge.has_tool(retrieve_step) is True
        assert ToolBridge.get_tool_name(retrieve_step) == "retrieval"
        assert ToolBridge.get_tool_parameters(retrieve_step) == {"top_k": 5}

    # ============================================================
    # 13. Verifies Research Workflow skeleton has tool metadata
    # ============================================================

    def test_research_workflow_skeleton_has_tool(self):
        from agent.workflow.workflows.research_workflow import ResearchWorkflow

        wf = ResearchWorkflow()
        result = wf.build(self._make_workflow_context())
        assert result.workflow == WorkflowType.MULTI_STEP

        retrieve_step = result.steps[1]
        assert ToolBridge.has_tool(retrieve_step) is True
        assert ToolBridge.get_tool_name(retrieve_step) == "retrieval"
        assert ToolBridge.get_tool_parameters(retrieve_step) == {"top_k": 10, "threshold": 0.7}

        analyze_step = result.steps[2]
        assert ToolBridge.has_tool(analyze_step) is True
        assert ToolBridge.get_tool_name(analyze_step) == "python"
        assert ToolBridge.get_tool_parameters(analyze_step) == {"mode": "analysis"}

    # ============================================================
    # 14. Verifies Comparison Workflow skeleton has tool metadata
    # ============================================================

    def test_comparison_workflow_skeleton_has_tool(self):
        from agent.workflow.workflows.comparison_workflow import ComparisonWorkflow

        wf = ComparisonWorkflow()
        result = wf.build(self._make_workflow_context())
        assert result.workflow == WorkflowType.PARALLEL

        retrieve_a = result.steps[0]
        assert ToolBridge.has_tool(retrieve_a) is True
        assert ToolBridge.get_tool_name(retrieve_a) == "retrieval"
        assert ToolBridge.get_tool_parameters(retrieve_a) == {"top_k": 5, "entity": "A"}

        retrieve_b = result.steps[1]
        assert ToolBridge.has_tool(retrieve_b) is True
        assert ToolBridge.get_tool_name(retrieve_b) == "retrieval"
        assert ToolBridge.get_tool_parameters(retrieve_b) == {"top_k": 5, "entity": "B"}

    # ============================================================
    # 15. DirectChat Workflow has no tool metadata
    # ============================================================

    def test_direct_chat_workflow_no_tool(self):
        from agent.workflow.workflows.direct_chat_workflow import DirectChatWorkflow

        wf = DirectChatWorkflow()
        result = wf.build(self._make_workflow_context())
        assert result.workflow == WorkflowType.DIRECT_CHAT

        chat_step = result.steps[0]
        assert ToolBridge.has_tool(chat_step) is False
