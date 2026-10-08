import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.execution_plan import ExecutionPlan, StepType
from agent.planning import (
    ComplexityResult,
    PlanningContext,
    TaskResult,
    TaskType,
)
from agent.planning.entity_extractor import (
    extract_companies,
    prior_user_context_for_followup,
)
from agent.query_planner import QueryPlanner


class TestQueryPlanner:
    @pytest.fixture
    def planner(self):
        return QueryPlanner()

    def test_compare_companies_plan(self, planner):
        context = PlanningContext(
            question="Compare Apple and Tesla revenue",
            companies=["Apple", "Tesla"],
        )
        plan, task_result, complexity_result = planner.plan(context)
        assert isinstance(plan, ExecutionPlan)
        assert isinstance(task_result, TaskResult)
        assert isinstance(complexity_result, ComplexityResult)
        assert plan.intent == "comparison"
        assert plan.original_query == "Compare Apple and Tesla revenue"
        assert plan.task_type == TaskType.COMPARISON

        step_types = [t.step_type for t in plan.tasks]
        assert StepType.RETRIEVE in step_types
        assert StepType.COMPARE in step_types
        assert StepType.SYNTHESIS in step_types

        retrieve_steps = [t for t in plan.tasks if t.step_type == StepType.RETRIEVE]
        assert len(retrieve_steps) == 2
        companies = {t.company for t in retrieve_steps}
        assert companies == {"Apple", "Tesla"}

        compare_step = [t for t in plan.tasks if t.step_type == StepType.COMPARE][0]
        assert len(compare_step.depends_on) == 2

        synthesis_step = [t for t in plan.tasks if t.step_type == StepType.SYNTHESIS][0]
        assert compare_step.step_id in synthesis_step.depends_on

    def test_chinese_comparison_followup_builds_retrieval_steps_for_both_companies(self, planner):
        question = "现在把它跟特斯拉比较一下。"
        setup = "分析一下苹果这份财报。"
        followup = prior_user_context_for_followup(
            question,
            [{"role": "user", "content": setup}],
        )
        assert followup is not None
        prior_question, inherited_companies = followup
        resolved_question = (
            f"{question}\nRelevant prior user request for reference resolution: {prior_question}"
        )
        current_companies = extract_companies(question)
        planned_companies = [*current_companies]
        planned_companies.extend(
            company for company in inherited_companies if company not in planned_companies
        )

        plan, _, _ = planner.plan(
            PlanningContext(question=resolved_question, companies=planned_companies),
        )

        retrieve_steps = [step for step in plan.tasks if step.step_type is StepType.RETRIEVE]
        assert {step.company for step in retrieve_steps} == {"Apple", "Tesla"}

    def test_single_company_plan(self, planner):
        context = PlanningContext(
            question="Apple revenue 10-K report",
            companies=["Apple"],
        )
        plan, task_result, complexity_result = planner.plan(context)
        assert isinstance(plan, ExecutionPlan)
        assert plan.intent == "single_company"
        assert plan.task_type == TaskType.DOCUMENT_QA

        step_types = [t.step_type for t in plan.tasks]
        assert StepType.RETRIEVE in step_types
        assert StepType.REASONING in step_types

        retrieve_step = [t for t in plan.tasks if t.step_type == StepType.RETRIEVE][0]
        assert retrieve_step.company == "Apple"

    def test_single_company_no_company(self, planner):
        context = PlanningContext(
            question="Revenue analysis",
            companies=[],
        )
        plan, task_result, complexity_result = planner.plan(context)
        assert isinstance(plan, ExecutionPlan)
        retrieve_step = [t for t in plan.tasks if t.step_type == StepType.RETRIEVE][0]
        assert retrieve_step.company is None

    def test_global_research_plan(self, planner):
        context = PlanningContext(
            question="Research market trends analysis",
            companies=[],
        )
        plan, task_result, complexity_result = planner.plan(context)
        assert isinstance(plan, ExecutionPlan)
        assert plan.intent == "global_research"
        assert plan.task_type == TaskType.RESEARCH

        step_types = [t.step_type for t in plan.tasks]
        assert StepType.RETRIEVE in step_types
        assert StepType.SYNTHESIS in step_types

    def test_generic_fallback_plan(self, planner):
        context = PlanningContext(
            question="Hello",
            companies=[],
        )
        plan, task_result, complexity_result = planner.plan(context)
        assert isinstance(plan, ExecutionPlan)
        assert plan.intent == "generic"
        assert plan.task_type == TaskType.CHAT

        step_types = [t.step_type for t in plan.tasks]
        assert StepType.RETRIEVE in step_types

    def test_explicit_growth_query_builds_typed_financial_tool_step(
        self,
        planner,
    ):
        context = PlanningContext(
            question="Calculate revenue growth from 100 to 125",
            companies=[],
        )

        plan, _, _ = planner.plan(context)

        assert plan.intent == "financial_calculation"
        assert plan.metadata == {
            "tool_policy": "financial_metrics_only",
            "deterministic": True,
        }
        assert len(plan.tasks) == 1
        step = plan.tasks[0]
        assert step.step_type is StepType.TOOL_CALL
        assert step.tool_name == "financial_metrics"
        assert step.parameters == {
            "operation": "growth_rate",
            "previous": 100,
            "current": 125,
        }

    @pytest.mark.parametrize(
        ("question", "operation", "expected_parameters"),
        [
            (
                "Calculate margin of 30 on 120",
                "margin",
                {"numerator": 30, "denominator": 120},
            ),
            (
                "Calculate ratio of 150 to 100",
                "ratio",
                {"numerator": 150, "denominator": 100},
            ),
            (
                "Calculate CAGR from 100 to 121 over 2 years",
                "cagr",
                {
                    "starting_value": 100,
                    "ending_value": 121,
                    "periods": 2,
                },
            ),
        ],
    )
    def test_supported_financial_queries_are_deterministically_typed(
        self,
        planner,
        question,
        operation,
        expected_parameters,
    ):
        plan, _, _ = planner.plan(
            PlanningContext(question=question, companies=[]),
        )

        step = plan.tasks[0]
        assert step.step_type is StepType.TOOL_CALL
        assert step.tool_name == "financial_metrics"
        assert step.parameters == {
            "operation": operation,
            **expected_parameters,
        }

    def test_ambiguous_financial_values_do_not_create_tool_call(
        self,
        planner,
    ):
        plan, _, _ = planner.plan(
            PlanningContext(
                question="growth from 100 to 125 in 2025",
                companies=[],
            ),
        )

        assert all(
            step.step_type is not StepType.TOOL_CALL
            for step in plan.tasks
        )

    def test_step_ids_are_sequential(self, planner):
        context = PlanningContext(
            question="Compare Apple and Tesla",
            companies=["Apple", "Tesla"],
        )
        plan, _, _ = planner.plan(context)
        ids = [t.step_id for t in plan.tasks]
        assert ids == sorted(ids)
        assert ids[0] == 1

    def test_step_counter_resets(self, planner):
        context1 = PlanningContext(
            question="Apple revenue",
            companies=["Apple"],
        )
        plan1, _, _ = planner.plan(context1)
        assert plan1.tasks[0].step_id == 1

        context2 = PlanningContext(
            question="Tesla revenue",
            companies=["Tesla"],
        )
        plan2, _, _ = planner.plan(context2)
        assert plan2.tasks[0].step_id == 1

    def test_planning_metadata_set(self, planner):
        context = PlanningContext(
            question="Compare Apple and Tesla",
            companies=["Apple", "Tesla"],
        )
        plan, _, _ = planner.plan(context)
        assert plan.task_type is not None
        assert plan.complexity is not None
        assert plan.estimated_tokens > 0
        assert plan.planner_reason != ""
        assert plan.planner_version == "rule-v1"

    def test_build_routing_context_from_task_result(self, planner):
        context = PlanningContext(
            question="Research AI chip market trends",
            companies=[],
        )
        _, task_result, complexity_result = planner.plan(context)
        routing_ctx = planner.build_routing_context(task_result, complexity_result)
        assert routing_ctx.task == TaskType.RESEARCH
        assert routing_ctx.estimated_tokens > 0
