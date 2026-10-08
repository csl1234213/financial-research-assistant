import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.execution_engine import ExecutionEngine
from agent.execution_plan import ExecutionPlan, PlanStep, StepStatus, StepType


@pytest.mark.unit
class TestExecutionEngineHandlerRegistration:
    def test_register_handler(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: {"docs": ["d1"]})
        assert StepType.RETRIEVE in engine._handlers

    def test_register_multiple_handlers(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: None)
        engine.register_handler(StepType.SYNTHESIS, lambda step, ctx: None)
        engine.register_handler(StepType.COMPARE, lambda step, ctx: None)
        assert len(engine._handlers) == 3


@pytest.mark.unit
class TestExecutionEngineExecute:
    def test_execute_single_step_completes(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: {"docs": ["apple_chunk"]})

        plan = ExecutionPlan(
            intent="single_company",
            original_query="What is Apple's revenue?",
            tasks=[
                PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="Retrieve Apple docs"),
            ],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.COMPLETED
        assert result.tasks[0].result.success is True
        assert result.tasks[0].result.output == {"docs": ["apple_chunk"]}

    def test_execute_multiple_steps_all_complete(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: {"docs": [step.company]})
        engine.register_handler(StepType.SYNTHESIS, lambda step, ctx: {"summary": "done"})

        plan = ExecutionPlan(
            intent="single_company",
            original_query="Analyze Apple",
            tasks=[
                PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="Retrieve", company="Apple"),
                PlanStep(step_id=2, step_type=StepType.SYNTHESIS, description="Synthesize"),
            ],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.COMPLETED
        assert result.tasks[1].status == StepStatus.COMPLETED

    def test_execute_passes_shared_context(self):
        captured_context = {}

        def capture_context(step, ctx):
            captured_context["received"] = ctx
            return {"ok": True}

        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, capture_context)

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="test")],
        )

        engine.execute(plan, shared_context={"company": "Apple", "mode": "research"})

        assert captured_context["received"]["company"] == "Apple"
        assert captured_context["received"]["mode"] == "research"

    def test_execute_no_handler_marks_failed(self):
        engine = ExecutionEngine()

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="test")],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[0].result.success is False
        assert "No handler registered" in result.tasks[0].result.error

    def test_execute_handler_throws_marks_failed(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: (_ for _ in ()).throw(Exception("boom")))

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="test")],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[0].result.success is False
        assert "boom" in result.tasks[0].result.error

    def test_execute_dependency_not_met_skips(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: {"docs": []})
        engine.register_handler(StepType.SYNTHESIS, lambda step, ctx: {"summary": "done"})

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[
                PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="retrieve"),
                PlanStep(step_id=2, step_type=StepType.SYNTHESIS, description="synthesize", depends_on=[99]),
            ],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.COMPLETED
        assert result.tasks[1].status == StepStatus.SKIPPED
        assert "Dependencies not met" in result.tasks[1].result.error

    def test_execute_dependency_met_completes(self):
        engine = ExecutionEngine()
        results_store = {}

        def retrieve(step, ctx):
            results_store["retrieved"] = True
            return {"docs": ["d1", "d2"]}

        def synthesize(step, ctx):
            results_store["synthesized"] = True
            return {"summary": "done"}

        engine.register_handler(StepType.RETRIEVE, retrieve)
        engine.register_handler(StepType.SYNTHESIS, synthesize)

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[
                PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="retrieve"),
                PlanStep(step_id=2, step_type=StepType.SYNTHESIS, description="synthesize", depends_on=[1]),
            ],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.COMPLETED
        assert result.tasks[1].status == StepStatus.COMPLETED
        assert results_store.get("retrieved") is True
        assert results_store.get("synthesized") is True

    def test_execute_empty_plan_returns_unchanged(self):
        engine = ExecutionEngine()

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[],
        )

        result = engine.execute(plan)

        assert result.tasks == []
        assert result.intent == "single_company"

    def test_execute_compare_intent(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.COMPARE, lambda step, ctx: {"comparison": "apple vs tesla"})

        plan = ExecutionPlan(
            intent="compare_companies",
            original_query="Compare Apple and Tesla",
            tasks=[
                PlanStep(step_id=1, step_type=StepType.COMPARE, description="Compare companies"),
            ],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.COMPLETED
        assert result.tasks[0].result.output == {"comparison": "apple vs tesla"}

    def test_execute_global_research_intent(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: {"docs": ["market_overview"]})
        engine.register_handler(StepType.SYNTHESIS, lambda step, ctx: {"summary": "global analysis"})

        plan = ExecutionPlan(
            intent="global_research",
            original_query="Market trends",
            tasks=[
                PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="Global retrieve"),
                PlanStep(step_id=2, step_type=StepType.SYNTHESIS, description="Global synthesis", depends_on=[1]),
            ],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.COMPLETED
        assert result.tasks[1].status == StepStatus.COMPLETED

    def test_execute_returns_same_plan_object(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: {"docs": []})

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="test")],
        )

        result = engine.execute(plan)

        assert result is plan

    def test_execute_shared_context_defaults_to_empty_dict(self):
        engine = ExecutionEngine()
        engine.register_handler(StepType.RETRIEVE, lambda step, ctx: {"docs": []})

        plan = ExecutionPlan(
            intent="single_company",
            original_query="test",
            tasks=[PlanStep(step_id=1, step_type=StepType.RETRIEVE, description="test")],
        )

        result = engine.execute(plan)

        assert result.tasks[0].status == StepStatus.COMPLETED
