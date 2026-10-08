# ============================================================
# test_tool_benchmark.py
# Tool Calling Framework Benchmark & Regression
# ============================================================
# 验证：
#   1. Tool Metadata Parsing Accuracy
#   2. Tool Invocation Success Rate per Workflow
#   3. Tool Failure Handling
#   4. Performance
#   5. Workflow Compatibility Matrix
# ============================================================

import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.execution.execution_context import ExecutionContext
from agent.execution.execution_engine import ExecutionEngine as StrategyExecutionEngine
from agent.execution.execution_result import ExecutionResult
from agent.execution.strategy_enums import ExecutionStrategyType
from agent.planning import (
    ComplexityLevel,
    ComplexityResult,
    TaskResult,
    TaskType,
)
from agent.planning.complexity_models import ComplexityModel
from agent.planning.task_models import TaskModel
from agent.tools import (
    ToolBridge,
    ToolEngine,
    ToolResult,
    ToolStatus,
)
from agent.tools.tool_exceptions import ToolNotFound, ToolNotSupported
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult
from llm.router import RoutingContext

# ============================================================
# Helpers
# ============================================================

def _make_exec_context(workflow=None):
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


def _make_workflow_result(workflow_type, steps, strategy=None):
    strategy_map = {
        WorkflowType.RAG: ExecutionStrategyType.RAG,
        WorkflowType.MULTI_STEP: ExecutionStrategyType.MULTI_STEP,
        WorkflowType.PARALLEL: ExecutionStrategyType.PARALLEL,
        WorkflowType.DIRECT_CHAT: ExecutionStrategyType.DIRECT_LLM,
    }
    return WorkflowResult(
        workflow=workflow_type,
        steps=steps,
        execution_strategy=strategy or strategy_map.get(workflow_type, ExecutionStrategyType.DIRECT_LLM),
    )


def _make_tool_result(status=ToolStatus.SUCCESS, output="ok"):
    return ToolResult(status=status, output=output)


# ============================================================
# 1. Tool Metadata Parsing Accuracy
# ============================================================

class TestToolMetadataParsingAccuracy:

    @pytest.mark.parametrize("metadata,expected_name,expected_params", [
        (
            {"tool": {"name": "retrieval", "parameters": {"top_k": 5}}},
            "retrieval",
            {"top_k": 5},
        ),
        (
            {"tool": {"name": "retrieval", "parameters": {"top_k": 10, "threshold": 0.7}}},
            "retrieval",
            {"top_k": 10, "threshold": 0.7},
        ),
        (
            {"tool": {"name": "python", "parameters": {"mode": "analysis"}}},
            "python",
            {"mode": "analysis"},
        ),
        (
            {"tool": "retrieval"},
            "retrieval",
            {},
        ),
        (
            {"strategy": "rag"},
            None,
            {},
        ),
    ])
    def test_tool_metadata_parsing(self, metadata, expected_name, expected_params):
        step = WorkflowStep(
            step_id="test",
            name="Test",
            description="Test step",
            metadata=metadata,
        )

        has_tool = ToolBridge.has_tool(step)
        tool_name = ToolBridge.get_tool_name(step)
        tool_params = ToolBridge.get_tool_parameters(step)

        if expected_name is None:
            assert has_tool is False
        else:
            assert has_tool is True
        assert tool_name == expected_name
        assert tool_params == expected_params

    def test_all_workflow_skeleton_metadata_parsed(self):
        from agent.workflow.workflows.comparison_workflow import ComparisonWorkflow
        from agent.workflow.workflows.direct_chat_workflow import DirectChatWorkflow
        from agent.workflow.workflows.rag_workflow import RAGWorkflow
        from agent.workflow.workflows.research_workflow import ResearchWorkflow

        workflow_ctx = WorkflowContext(
            task=TaskResult(task=TaskModel(task_type=TaskType.DOCUMENT_QA), reason="Test"),
            complexity=ComplexityResult(
                complexity=ComplexityModel(level=ComplexityLevel.LOW, score=0.3),
                reason="Low",
            ),
            execution=ExecutionResult(
                strategy=ExecutionStrategyType.RAG,
                reason="Test",
            ),
            routing=RoutingContext(task=TaskType.DOCUMENT_QA),
        )

        expected_tool_steps = {
            RAGWorkflow: 1,
            ResearchWorkflow: 2,
            ComparisonWorkflow: 2,
            DirectChatWorkflow: 0,
        }

        total_expected = sum(expected_tool_steps.values())
        parsed = 0

        for wf_cls, expected_tool_count in expected_tool_steps.items():
            wf = wf_cls()
            result = wf.build(workflow_ctx)
            for step in result.steps:
                if ToolBridge.has_tool(step):
                    name = ToolBridge.get_tool_name(step)
                    if name is not None:
                        parsed += 1

        accuracy = parsed / total_expected if total_expected > 0 else 1.0
        assert accuracy == 1.0, f"Tool metadata parsing accuracy: {accuracy:.1%} (parsed={parsed}, expected={total_expected})"


# ============================================================
# 2. Tool Invocation Accuracy
# ============================================================

class TestToolInvocationAccuracy:

    def test_rag_workflow_tool_gated(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve documents",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
                    },
                ),
                WorkflowStep(
                    step_id="reason", name="Reason", description="Reason",
                    metadata={"strategy": "rag"},
                ),
                WorkflowStep(
                    step_id="answer", name="Answer", description="Answer",
                    metadata={"strategy": "rag"},
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        result = ToolResult(status=ToolStatus.SUCCESS, output="retrieved")
        with patch.object(ToolEngine, 'execute', return_value=result):
            engine = StrategyExecutionEngine()
            exec_result = engine.execute(exec_ctx)

            assert len(exec_result.tool_results) == 1
            assert exec_result.tool_results[0].status == ToolStatus.SUCCESS

    def test_research_workflow_tool_invocation(self):
        workflow = _make_workflow_result(
            WorkflowType.MULTI_STEP,
            [
                WorkflowStep(
                    step_id="plan", name="Plan", description="Plan",
                    metadata={"strategy": "multi_step"},
                ),
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 10}},
                    },
                ),
                WorkflowStep(
                    step_id="analyze", name="Analyze", description="Analyze",
                    metadata={
                        "tool": {"name": "python", "parameters": {"mode": "analysis"}},
                    },
                ),
                WorkflowStep(
                    step_id="synthesize", name="Synthesize", description="Synthesize",
                    metadata={"strategy": "multi_step"},
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        r1 = ToolResult(status=ToolStatus.SUCCESS, output="retrieved")
        r2 = ToolResult(status=ToolStatus.SUCCESS, output="analyzed")
        with patch.object(ToolEngine, 'execute', side_effect=[r1, r2]):
            engine = StrategyExecutionEngine()
            exec_result = engine.execute(exec_ctx)

            assert len(exec_result.tool_results) == 2
            assert all(r.status == ToolStatus.SUCCESS for r in exec_result.tool_results)

    def test_comparison_workflow_tool_invocation(self):
        workflow = _make_workflow_result(
            WorkflowType.PARALLEL,
            [
                WorkflowStep(
                    step_id="retrieve_a", name="Retrieve A", description="Retrieve A",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"entity": "A"}},
                    },
                ),
                WorkflowStep(
                    step_id="retrieve_b", name="Retrieve B", description="Retrieve B",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"entity": "B"}},
                    },
                ),
                WorkflowStep(
                    step_id="compare", name="Compare", description="Compare",
                    metadata={"strategy": "parallel"},
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        r1 = ToolResult(status=ToolStatus.SUCCESS, output="A results")
        r2 = ToolResult(status=ToolStatus.SUCCESS, output="B results")
        with patch.object(ToolEngine, 'execute', side_effect=[r1, r2]):
            engine = StrategyExecutionEngine()
            exec_result = engine.execute(exec_ctx)

            assert len(exec_result.tool_results) == 2
            assert all(r.status == ToolStatus.SUCCESS for r in exec_result.tool_results)

    def test_direct_chat_workflow_no_tool(self):
        workflow = _make_workflow_result(
            WorkflowType.DIRECT_CHAT,
            [
                WorkflowStep(
                    step_id="chat", name="Chat", description="Chat",
                    metadata={"strategy": "direct_llm"},
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        engine = StrategyExecutionEngine()
        engine.set_fallback("direct_llm")
        exec_result = engine.execute(exec_ctx)

        assert len(exec_result.tool_results) == 0

    def test_tool_invocation_accuracy(self):
        success_count = 0
        total = 0

        test_cases = [
            (
                _make_workflow_result(
                    WorkflowType.RAG,
                    [
                        WorkflowStep(
                            step_id="retrieve", name="Retrieve", description="R",
                            metadata={"tool": {"name": "retrieval", "parameters": {"top_k": 5}}},
                        ),
                    ],
                ),
                1,
            ),
            (
                _make_workflow_result(
                    WorkflowType.MULTI_STEP,
                    [
                        WorkflowStep(
                            step_id="retrieve", name="Retrieve", description="R",
                            metadata={"tool": {"name": "retrieval", "parameters": {"top_k": 10}}},
                        ),
                        WorkflowStep(
                            step_id="analyze", name="Analyze", description="A",
                            metadata={"tool": {"name": "python", "parameters": {"mode": "analysis"}}},
                        ),
                    ],
                ),
                2,
            ),
            (
                _make_workflow_result(
                    WorkflowType.PARALLEL,
                    [
                        WorkflowStep(
                            step_id="retrieve_a", name="Retrieve A", description="A",
                            metadata={"tool": {"name": "retrieval", "parameters": {"entity": "A"}}},
                        ),
                        WorkflowStep(
                            step_id="retrieve_b", name="Retrieve B", description="B",
                            metadata={"tool": {"name": "retrieval", "parameters": {"entity": "B"}}},
                        ),
                    ],
                ),
                2,
            ),
            (
                _make_workflow_result(
                    WorkflowType.DIRECT_CHAT,
                    [
                        WorkflowStep(
                            step_id="chat", name="Chat", description="C",
                            metadata={"strategy": "direct_llm"},
                        ),
                    ],
                ),
                0,
            ),
        ]

        for workflow, expected_count in test_cases:
            exec_ctx = _make_exec_context(workflow=workflow)
            r = ToolResult(status=ToolStatus.SUCCESS, output="ok")
            total += 1

            with patch.object(ToolEngine, 'execute', return_value=r):
                engine = StrategyExecutionEngine()
                engine.set_fallback("direct_llm")
                exec_result = engine.execute(exec_ctx)

                if len(exec_result.tool_results) == expected_count:
                    success_count += 1

        accuracy = success_count / total if total > 0 else 0
        assert accuracy >= 0.99, f"Tool invocation accuracy: {accuracy:.1%}"


# ============================================================
# 3. Failure Handling
# ============================================================

class TestToolFailureHandling:

    def test_unknown_tool_not_found_no_crash(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "unknown_tool", "parameters": {}},
                    },
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        engine = StrategyExecutionEngine()
        engine.set_fallback("rag")
        result = engine.execute(exec_ctx)

        assert isinstance(result, ExecutionResult)
        assert len(result.tool_results) == 0

    def test_tool_execute_exception_no_crash(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
                    },
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        with patch.object(ToolEngine, 'execute', side_effect=RuntimeError("Tool crashed")):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert isinstance(result, ExecutionResult)
            assert len(result.tool_results) == 0

    def test_tool_not_supported_no_crash(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
                    },
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        with patch.object(ToolEngine, 'execute', side_effect=ToolNotSupported("Not supported")):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert isinstance(result, ExecutionResult)
            assert len(result.tool_results) == 0

    def test_tool_result_failure_preserved(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
                    },
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        failed_result = ToolResult(
            status=ToolStatus.FAILED,
            error="Connection timeout",
            metadata={"retry_count": 3},
        )
        with patch.object(ToolEngine, 'execute', return_value=failed_result):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert len(result.tool_results) == 1
            assert result.tool_results[0].status == ToolStatus.FAILED
            assert result.tool_results[0].error == "Connection timeout"

    def test_multiple_tools_one_fails_no_crash(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
                    },
                ),
                WorkflowStep(
                    step_id="analyze", name="Analyze", description="Analyze",
                    metadata={
                        "tool": {"name": "python", "parameters": {"mode": "analysis"}},
                    },
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        r1 = ToolResult(status=ToolStatus.SUCCESS, output="retrieved")
        with patch.object(ToolEngine, 'execute', side_effect=[r1, ToolNotFound("python")]):
            engine = StrategyExecutionEngine()
            result = engine.execute(exec_ctx)

            assert len(result.tool_results) == 1
            assert result.tool_results[0].status == ToolStatus.SUCCESS

    def test_tool_bridge_has_tool_edge_cases(self):
        step_no_key = WorkflowStep(
            step_id="s1", name="S1", description="d",
            metadata={},
        )
        assert ToolBridge.has_tool(step_no_key) is False

        step_empty = WorkflowStep(
            step_id="s2", name="S2", description="d",
            metadata={"tool": None},
        )
        assert ToolBridge.has_tool(step_empty) is True

        step_empty_dict = WorkflowStep(
            step_id="s3", name="S3", description="d",
            metadata={"tool": {}},
        )
        assert ToolBridge.has_tool(step_empty_dict) is True
        assert ToolBridge.get_tool_name(step_empty_dict) is None


# ============================================================
# 4. Performance
# ============================================================

class TestToolPerformance:

    def test_tool_bridge_latency(self):
        step = WorkflowStep(
            step_id="retrieve", name="Retrieve", description="Retrieve",
            metadata={
                "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
            },
        )

        start = time.perf_counter()
        for _ in range(1000):
            _ = ToolBridge.has_tool(step)
            _ = ToolBridge.get_tool_name(step)
            _ = ToolBridge.get_tool_parameters(step)
            _ = ToolBridge.to_tool_context(step)
        elapsed = (time.perf_counter() - start) / 1000 * 1000  # avg ms

        assert elapsed < 1.0, f"ToolBridge avg latency: {elapsed:.3f}ms"

    def test_tool_metadata_parse_latency(self):
        step = WorkflowStep(
            step_id="retrieve", name="Retrieve", description="Retrieve",
            metadata={
                "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
            },
        )

        start = time.perf_counter()
        for _ in range(1000):
            _ = ToolBridge.has_tool(step)
            _ = ToolBridge.get_tool_name(step)
            _ = ToolBridge.get_tool_parameters(step)
        elapsed = (time.perf_counter() - start) / 1000 * 1000

        assert elapsed < 5.0, f"Tool metadata parse avg latency: {elapsed:.3f}ms"

    def test_end_to_end_tool_invoke_latency(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
                    },
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        r = ToolResult(status=ToolStatus.SUCCESS, output="ok")
        with patch.object(ToolEngine, 'execute', return_value=r):
            engine = StrategyExecutionEngine()

            start = time.perf_counter()
            for _ in range(100):
                engine.execute(exec_ctx)
            elapsed = (time.perf_counter() - start) / 100 * 1000

            assert elapsed < 10.0, f"End-to-end tool invoke avg latency: {elapsed:.3f}ms"


# ============================================================
# 5. Stability (same input → same result)
# ============================================================

class TestToolStability:

    def test_tool_bridge_deterministic(self):
        step = WorkflowStep(
            step_id="retrieve", name="Retrieve", description="Retrieve",
            metadata={
                "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
            },
        )

        results = []
        for _ in range(10):
            has = ToolBridge.has_tool(step)
            name = ToolBridge.get_tool_name(step)
            params = ToolBridge.get_tool_parameters(step)
            results.append((has, name, params))

        first = results[0]
        for r in results[1:]:
            assert r == first, "ToolBridge is not deterministic"

    def test_tool_invocation_consistent_count(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={
                        "tool": {"name": "retrieval", "parameters": {"top_k": 5}},
                    },
                ),
                WorkflowStep(
                    step_id="reason", name="Reason", description="Reason",
                    metadata={"strategy": "rag"},
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        counts = []
        for _ in range(5):
            r = ToolResult(status=ToolStatus.SUCCESS, output="ok")
            with patch.object(ToolEngine, 'execute', return_value=r):
                engine = StrategyExecutionEngine()
                result = engine.execute(exec_ctx)
                counts.append(len(result.tool_results))

        assert all(c == 1 for c in counts), f"Tool invocation count varies: {counts}"


# ============================================================
# 6. No-Tool Regression (old runtime unaffected)
# ============================================================

class TestNoToolRegression:

    def test_old_execution_flow_without_tool_still_works(self):
        task = TaskModel(task_type=TaskType.CHAT)
        task_result = TaskResult(task=task, reason="Chat")
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

    def test_workflow_without_tool_steps_unchanged(self):
        workflow = _make_workflow_result(
            WorkflowType.RAG,
            [
                WorkflowStep(
                    step_id="retrieve", name="Retrieve", description="Retrieve",
                    metadata={"strategy": "rag"},
                ),
                WorkflowStep(
                    step_id="answer", name="Answer", description="Answer",
                    metadata={"strategy": "rag"},
                ),
            ],
        )
        exec_ctx = _make_exec_context(workflow=workflow)

        engine = StrategyExecutionEngine()
        result = engine.execute(exec_ctx)

        assert result.strategy.value == "rag"
        assert len(result.tool_results) == 0
