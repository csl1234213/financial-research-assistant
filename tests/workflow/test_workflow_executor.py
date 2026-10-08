# ============================================================
# test_workflow_executor.py — WorkflowExecutor Tests
# ============================================================

from unittest.mock import MagicMock, call

import pytest

from agent.execution.execution_context import ExecutionContext
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
from agent.workflow.workflow_enums import WorkflowStatus, WorkflowType
from agent.workflow.workflow_executor import ExecutionRunner, WorkflowExecutor
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult
from llm.router import RoutingContext

# ============================================================
# Helpers
# ============================================================

def _make_context() -> ExecutionContext:
    task_result = TaskResult(
        task=TaskModel(task_type=TaskType.DOCUMENT_QA),
        reason="test",
    )
    complexity_result = ComplexityResult(
        complexity=ComplexityModel(level=ComplexityLevel.LOW),
        reason="test",
    )
    return ExecutionContext(
        task=task_result,
        complexity=complexity_result,
        routing=RoutingContext(task=TaskType.DOCUMENT_QA),
    )


def _make_mock_runner() -> MagicMock:
    runner = MagicMock(spec=ExecutionRunner)
    runner.execute.return_value = ExecutionResult(
        strategy=ExecutionStrategyType.DIRECT_LLM,
        reason="mock",
    )
    return runner


def _make_workflow(steps_count: int = 1, **kwargs) -> WorkflowResult:
    steps = [
        WorkflowStep(
            step_id=f"step_{i}",
            name=f"Step {i}",
            description=f"Description {i}",
            required=True,
            metadata={"strategy": "direct_llm"},
        )
        for i in range(steps_count)
    ]
    defaults = {
        "workflow": WorkflowType.DIRECT_CHAT,
        "steps": steps,
        "estimated_time_ms": 1000,
        "execution_strategy": ExecutionStrategyType.DIRECT_LLM,
        "estimated_execution_steps": steps_count,
    }
    defaults.update(kwargs)
    return WorkflowResult(**defaults)


# ============================================================
# Test Class
# ============================================================

class TestWorkflowExecutor:

    # ============================================================
    # Executor.creation
    # ============================================================

    def test_executor_creates(self):
        executor = WorkflowExecutor()
        assert executor is not None

    # ============================================================
    # DirectChat — 1 step
    # ============================================================

    def test_direct_chat_one_step(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=1)
        workflow.steps[0] = WorkflowStep(
            step_id="chat",
            name="Direct Chat",
            description="Single-step LLM",
            required=True,
            metadata={"strategy": "direct_llm"},
        )

        result = executor.execute(workflow, runner, ctx)

        assert result.status == WorkflowStatus.DONE
        assert len(result.completed_steps) == 1
        assert result.completed_steps[0].step_id == "chat"
        assert result.current_step is None
        runner.execute.assert_called_once_with(ctx)

    # ============================================================
    # RAG — 3 steps
    # ============================================================

    def test_rag_three_steps(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=3)
        workflow.steps = [
            WorkflowStep(step_id="retrieve", name="Retrieve", description="retrieve", metadata={"strategy": "rag"}),
            WorkflowStep(step_id="reason", name="Reason", description="reason", depends_on=["retrieve"], metadata={"strategy": "rag"}),
            WorkflowStep(step_id="answer", name="Answer", description="answer", depends_on=["reason"], metadata={"strategy": "rag"}),
        ]

        result = executor.execute(workflow, runner, ctx)

        assert result.status == WorkflowStatus.DONE
        assert len(result.completed_steps) == 3
        assert [s.step_id for s in result.completed_steps] == ["retrieve", "reason", "answer"]
        assert runner.execute.call_count == 3

    # ============================================================
    # Research — 5 steps
    # ============================================================

    def test_research_five_steps(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=5)
        workflow.steps = [
            WorkflowStep(step_id="plan", name="Plan", description="plan", metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="retrieve", name="Retrieve", description="retrieve", depends_on=["plan"], metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="analyze", name="Analyze", description="analyze", depends_on=["retrieve"], metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="synthesize", name="Synthesize", description="synthesize", depends_on=["analyze"], metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="verify", name="Verify", description="verify", depends_on=["synthesize"], metadata={"strategy": "multi_step"}),
        ]

        result = executor.execute(workflow, runner, ctx)

        assert result.status == WorkflowStatus.DONE
        assert len(result.completed_steps) == 5
        assert [s.step_id for s in result.completed_steps] == [
            "plan", "retrieve", "analyze", "synthesize", "verify",
        ]
        assert runner.execute.call_count == 5

    # ============================================================
    # Comparison — 4 steps
    # ============================================================

    def test_comparison_four_steps(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=4)
        workflow.steps = [
            WorkflowStep(step_id="retrieve_a", name="Retrieve A", description="retrieve_a", metadata={"strategy": "parallel"}),
            WorkflowStep(step_id="retrieve_b", name="Retrieve B", description="retrieve_b", metadata={"strategy": "parallel"}),
            WorkflowStep(step_id="compare", name="Compare", description="compare", depends_on=["retrieve_a", "retrieve_b"], metadata={"strategy": "parallel"}),
            WorkflowStep(step_id="synthesize", name="Synthesize", description="synthesize", depends_on=["compare"], metadata={"strategy": "parallel"}),
        ]

        result = executor.execute(workflow, runner, ctx)

        assert result.status == WorkflowStatus.DONE
        assert len(result.completed_steps) == 4
        assert [s.step_id for s in result.completed_steps] == [
            "retrieve_a", "retrieve_b", "compare", "synthesize",
        ]
        assert runner.execute.call_count == 4

    # ============================================================
    # Step order preserved
    # ============================================================

    def test_step_order_preserved(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=3)
        workflow.steps = [
            WorkflowStep(step_id="first", name="First", description="first", metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="second", name="Second", description="second", metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="third", name="Third", description="third", metadata={"strategy": "multi_step"}),
        ]

        result = executor.execute(workflow, runner, ctx)

        assert [s.step_id for s in result.completed_steps] == ["first", "second", "third"]

    # ============================================================
    # Metadata preserved
    # ============================================================

    def test_metadata_preserved_on_steps(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=2)
        workflow.steps = [
            WorkflowStep(step_id="s1", name="S1", description="s1", metadata={"strategy": "rag", "priority": "high"}),
            WorkflowStep(step_id="s2", name="S2", description="s2", metadata={"strategy": "rag"}),
        ]

        result = executor.execute(workflow, runner, ctx)

        assert result.completed_steps[0].metadata == {"strategy": "rag", "priority": "high"}
        assert result.completed_steps[1].metadata == {"strategy": "rag"}

    # ============================================================
    # ExecutionEngine call count
    # ============================================================

    def test_runner_called_once_per_step(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=3)

        executor.execute(workflow, runner, ctx)

        assert runner.execute.call_count == 3
        assert runner.execute.call_args_list == [call(ctx), call(ctx), call(ctx)]

    # ============================================================
    # Status transitions
    # ============================================================

    def test_status_transitions(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=1)

        assert workflow.status == WorkflowStatus.PENDING

        result = executor.execute(workflow, runner, ctx)

        assert result.status == WorkflowStatus.DONE

    def test_status_failed_on_exception(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        runner.execute.side_effect = RuntimeError("step failed")
        ctx = _make_context()
        workflow = _make_workflow(steps_count=2)

        with pytest.raises(RuntimeError, match="step failed"):
            executor.execute(workflow, runner, ctx)

        assert workflow.status == WorkflowStatus.FAILED

    # ============================================================
    # current_step tracking
    # ============================================================

    def test_current_step_during_execution(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=3)
        workflow.steps = [
            WorkflowStep(step_id="a", name="A", description="a", metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="b", name="B", description="b", metadata={"strategy": "multi_step"}),
            WorkflowStep(step_id="c", name="C", description="c", metadata={"strategy": "multi_step"}),
        ]

        captured_steps = []

        def capture(_):
            captured_steps.append(workflow.current_step.step_id)
            return ExecutionResult(strategy=ExecutionStrategyType.DIRECT_LLM, reason="mock")

        runner.execute.side_effect = capture

        result = executor.execute(workflow, runner, ctx)

        assert captured_steps == ["a", "b", "c"]
        assert result.current_step is None

    # ============================================================
    # ExecutionRunner Protocol
    # ============================================================

    def test_execution_engine_satisfies_protocol(self):
        from agent.execution.execution_engine import ExecutionEngine
        engine = ExecutionEngine()
        assert isinstance(engine, ExecutionRunner)

    # ============================================================
    # Executor returns same workflow object
    # ============================================================

    def test_executor_returns_same_object(self):
        executor = WorkflowExecutor()
        runner = _make_mock_runner()
        ctx = _make_context()
        workflow = _make_workflow(steps_count=1)

        result = executor.execute(workflow, runner, ctx)

        assert result is workflow
