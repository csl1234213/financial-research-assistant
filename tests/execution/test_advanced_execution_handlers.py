from __future__ import annotations

import threading

import pytest

from agent.execution.execution_handler import ExecutionHandlerContext
from agent.execution.financial_metrics_handler import (
    FinancialMetricsStepHandler,
    authorize_financial_metrics_tool,
)
from agent.execution.handlers.multi_step_handler import MultiStepHandler
from agent.execution.handlers.parallel_handler import ParallelHandler
from agent.execution.handlers.tool_calling_handler import ToolCallingHandler
from agent.execution_engine import ExecutionEngine
from agent.execution_plan import ExecutionPlan, PlanStep, StepStatus, StepType
from agent.reasoning_models import Evidence
from agent.tools import ToolEngine


def _plan(*steps: PlanStep) -> ExecutionPlan:
    return ExecutionPlan(
        intent="test",
        original_query="test query",
        tasks=list(steps),
    )


@pytest.mark.unit
def test_multi_step_executes_dependencies_and_exposes_prior_results():
    engine = ExecutionEngine()
    observed_results: list[dict[int, object]] = []

    def retrieve(step, shared):
        evidence = Evidence(
            content="Tesla revenue increased.",
            source="Tesla_Q2_2025.pdf",
            company="Tesla",
            confidence=0.93,
        )
        shared["_all_evidence"].append(evidence)
        return [evidence]

    def synthesize(step, shared):
        observed_results.append(dict(shared["_step_results"]))
        return {"evidence_count": len(shared["_step_results"][1])}

    engine.register_handler(StepType.RETRIEVE, retrieve)
    engine.register_handler(StepType.SYNTHESIS, synthesize)
    plan = _plan(
        PlanStep(1, StepType.RETRIEVE, "retrieve"),
        PlanStep(2, StepType.SYNTHESIS, "synthesize", depends_on=[1]),
    )

    output = MultiStepHandler().execute(
        ExecutionHandlerContext(plan=plan, executor=engine),
    )

    assert [step.status for step in plan.tasks] == [
        StepStatus.COMPLETED,
        StepStatus.COMPLETED,
    ]
    assert list(observed_results[0]) == [1]
    assert output.execution_results[1].output == {"evidence_count": 1}
    assert output.evidences[0].source == "Tesla_Q2_2025.pdf"


@pytest.mark.unit
def test_parallel_handler_runs_retrievals_concurrently_and_merges_in_plan_order():
    engine = ExecutionEngine()
    barrier = threading.Barrier(2)
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def retrieve(step, shared):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            barrier.wait(timeout=2)
            evidence = Evidence(
                content=f"{step.company} revenue evidence",
                source=f"{step.company}.pdf",
                company=step.company or "",
                confidence=0.9,
            )
            shared["_all_evidence"].append(evidence)
            return [evidence]
        finally:
            with state_lock:
                active -= 1

    def compare(step, shared):
        assert list(shared["_step_results"]) == [1, 2]
        return {"compared": ["Apple", "Tesla"]}

    def synthesize(step, shared):
        assert list(shared["_step_results"]) == [1, 2, 3]
        return {"synthesized": True}

    engine.register_handler(StepType.RETRIEVE, retrieve)
    engine.register_handler(StepType.COMPARE, compare)
    engine.register_handler(StepType.SYNTHESIS, synthesize)
    plan = _plan(
        PlanStep(1, StepType.RETRIEVE, "retrieve Apple", company="Apple"),
        PlanStep(2, StepType.RETRIEVE, "retrieve Tesla", company="Tesla"),
        PlanStep(3, StepType.COMPARE, "compare", depends_on=[1, 2]),
        PlanStep(4, StepType.SYNTHESIS, "synthesize", depends_on=[3]),
    )

    output = ParallelHandler().execute(
        ExecutionHandlerContext(
            plan=plan,
            executor=engine,
            parallelism=2,
        ),
    )

    assert max_active == 2
    assert [evidence.company for evidence in output.evidences] == ["Apple", "Tesla"]
    assert [citation["source"] for citation in output.citations] == [
        "Apple.pdf",
        "Tesla.pdf",
    ]
    assert [result.step_id for result in output.execution_results] == [1, 2, 3, 4]
    assert all(result.success for result in output.execution_results)


@pytest.mark.unit
def test_parallel_handler_does_not_run_dependents_after_retrieval_failure():
    engine = ExecutionEngine()
    barrier = threading.Barrier(2)

    def retrieve(step, shared):
        barrier.wait(timeout=2)
        evidence = Evidence(content=f"{step.company} evidence", source=f"{step.company}.pdf")
        shared["_all_evidence"].append(evidence)
        if step.company == "Apple":
            raise RuntimeError("Apple retrieval unavailable")
        return [evidence]

    engine.register_handler(StepType.RETRIEVE, retrieve)
    engine.register_handler(StepType.COMPARE, lambda step, shared: {"unexpected": True})
    plan = _plan(
        PlanStep(1, StepType.RETRIEVE, "retrieve Apple", company="Apple"),
        PlanStep(2, StepType.RETRIEVE, "retrieve Tesla", company="Tesla"),
        PlanStep(3, StepType.COMPARE, "compare", depends_on=[1, 2]),
    )

    output = ParallelHandler().execute(
        ExecutionHandlerContext(
            plan=plan,
            executor=engine,
            parallelism=2,
        ),
    )

    assert plan.tasks[0].status is StepStatus.FAILED
    assert plan.tasks[1].status is StepStatus.COMPLETED
    assert plan.tasks[2].status is StepStatus.SKIPPED
    assert output.execution_results[2].error == "Dependencies not met"
    assert [evidence.source for evidence in output.evidences] == ["Tesla.pdf"]


class _CountingToolEngine(ToolEngine):
    def __init__(self):
        super().__init__(
            authorization_hook=authorize_financial_metrics_tool,
        )
        self.execution_count = 0
        self.authorized_execution_count = 0

    def execute(self, context, tool):
        self.execution_count += 1
        return super().execute(context, tool)

    def before_execute(self, context):
        self.authorized_execution_count += 1


@pytest.mark.unit
def test_tool_calling_executes_financial_metric_once_without_retrieval():
    engine = ExecutionEngine()
    tool_engine = _CountingToolEngine()
    engine.register_handler(
        StepType.TOOL_CALL,
        FinancialMetricsStepHandler(tool_engine),
    )
    plan = _plan(
        PlanStep(
            1,
            StepType.TOOL_CALL,
            "calculate growth",
            tool_name="financial_metrics",
            parameters={
                "operation": "growth_rate",
                "previous": 100,
                "current": 125,
                "precision": 2,
            },
        ),
    )

    output = ToolCallingHandler().execute(
        ExecutionHandlerContext(
            plan=plan,
            executor=engine,
            shared_context={"tenant_id": 42},
        ),
    )

    assert tool_engine.execution_count == 1
    assert tool_engine.authorized_execution_count == 1
    assert plan.tasks[0].status is StepStatus.COMPLETED
    assert output.execution_results[0].success is True
    assert output.execution_results[0].output["value"] == 25.0
    assert output.tool_calls[0]["tool_name"] == "financial_metrics"
    assert output.tool_calls[0]["status"] == "success"
    assert "growth_rate: 25.0 percent" in output.context
    assert output.evidences == []
    assert output.citations == []


@pytest.mark.unit
@pytest.mark.parametrize("tool_name", ["python", "sql", "http", "retrieval"])
def test_composition_handler_authorization_denies_unsafe_tools(
    tool_name,
):
    tool_engine = _CountingToolEngine()
    handler = FinancialMetricsStepHandler(tool_engine)
    step = PlanStep(
        1,
        StepType.TOOL_CALL,
        "attempt unauthorized tool",
        tool_name=tool_name,
        parameters={
            "operation": "growth_rate",
            "previous": 100,
            "current": 125,
        },
    )
    shared: dict[str, object] = {"tenant_id": 42}

    with pytest.raises(RuntimeError, match="not authorized"):
        handler(step, shared)

    assert tool_engine.execution_count == 1
    assert tool_engine.authorized_execution_count == 0
    assert shared["_tool_trace"][0]["status"] == "skipped"


@pytest.mark.unit
def test_tool_calling_financial_failure_is_closed_and_traced():
    engine = ExecutionEngine()
    tool_engine = _CountingToolEngine()
    engine.register_handler(
        StepType.TOOL_CALL,
        FinancialMetricsStepHandler(tool_engine),
    )
    plan = _plan(
        PlanStep(
            1,
            StepType.TOOL_CALL,
            "calculate growth",
            tool_name="financial_metrics",
            parameters={
                "operation": "growth_rate",
                "previous": 0,
                "current": 125,
            },
        ),
    )

    output = ToolCallingHandler().execute(
        ExecutionHandlerContext(plan=plan, executor=engine),
    )

    assert plan.tasks[0].status is StepStatus.FAILED
    assert tool_engine.execution_count == 1
    assert output.execution_results[0].success is False
    assert "non-zero" in output.execution_results[0].error
    assert output.tool_calls[0]["status"] == "failed"
    assert output.context == ""
    assert output.evidences == []
    assert output.citations == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "tool_name",
    ["python", "sql", "http", "retrieval", "custom", None],
)
def test_tool_calling_rejects_every_non_financial_tool_without_invocation(
    tool_name,
):
    engine = ExecutionEngine()
    invoked = False

    def forbidden_handler(step, shared):
        nonlocal invoked
        invoked = True
        return "must not run"

    engine.register_handler(StepType.TOOL_CALL, forbidden_handler)
    plan = _plan(
        PlanStep(
            1,
            StepType.TOOL_CALL,
            "unsafe tool",
            tool_name=tool_name,
        ),
    )

    output = ToolCallingHandler().execute(
        ExecutionHandlerContext(plan=plan, executor=engine),
    )

    assert invoked is False
    assert plan.tasks[0].status is StepStatus.FAILED
    assert output.execution_results[0].success is False
    assert "not enabled" in output.execution_results[0].error


@pytest.mark.unit
def test_tool_calling_does_not_disguise_retrieval_as_a_tool_call():
    engine = ExecutionEngine()
    invoked = False

    def retrieval(step, shared):
        nonlocal invoked
        invoked = True

    engine.register_handler(StepType.RETRIEVE, retrieval)
    plan = _plan(PlanStep(1, StepType.RETRIEVE, "generic planner fallback"))

    output = ToolCallingHandler().execute(
        ExecutionHandlerContext(plan=plan, executor=engine),
    )

    assert invoked is False
    assert plan.tasks[0].status is StepStatus.SKIPPED
    assert output.evidences == []
    assert "explicit tool_call" in output.execution_results[0].error
