import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock

import pytest

from agent.agent_runtime import AgentRuntime
from agent.execution_plan import ExecutionPlan, PlanStep, StepStatus, StepType
from agent.execution_result import ExecutionResult
from agent.planning import (
    ComplexityLevel,
    ComplexityModel,
    ComplexityResult,
    PlanningContext,
    TaskModel,
    TaskResult,
    TaskType,
)
from agent.planning.entity_extractor import prior_user_context_for_followup
from agent.reasoning_models import Evidence, ReasoningResult
from agent.runtime_result import RuntimeResult
from llm.router import RoutingContext, RoutingPriority


class FakeRetriever:
    def retrieve_evidence(self, context, store):
        return [
            Evidence(
                content="Revenue grew 10% year over year.",
                source="apple.pdf",
                company=context.company or "Unknown",
                confidence=0.95,
                metadata={"chunk_id": "apple_0"},
            ),
        ]


class FakeIntentAnalyzer:
    def analyze(self, query):
        return {
            "intent": "SINGLE_COMPANY",
            "companies": ["Apple"],
        }


class FakePlanner:
    def __init__(self):
        self.last_context = None

    def plan(
        self,
        context: PlanningContext,
    ) -> tuple[ExecutionPlan, TaskResult, ComplexityResult]:
        self.last_context = context
        task = TaskModel(
            task_type=TaskType.DOCUMENT_QA,
            complexity=ComplexityLevel.MEDIUM,
        )
        task_result = TaskResult(
            task=task,
            reason="Detected document qa keyword",
            extracted_entities=["Apple"],
            estimated_tokens=500,
        )
        complexity_result = ComplexityResult(
            complexity=ComplexityModel(
                level=ComplexityLevel.MEDIUM,
                score=0.45,
                estimated_tokens=500,
                estimated_latency_ms=1500,
                estimated_cost=0.008,
            ),
            reason="Document QA task",
            factors={
                "prompt_length": 0.5,
                "company_count": 0.3,
                "year_count": 0.0,
                "task_weight": 0.5,
                "comparison": 0.0,
            },
        )
        plan = ExecutionPlan(
            intent="single_company",
            original_query=context.question,
            task_type=TaskType.DOCUMENT_QA,
            complexity=ComplexityLevel.MEDIUM,
            complexity_score=0.45,
            estimated_tokens=500,
            estimated_latency_ms=1500,
            estimated_cost=0.008,
            planner_reason="Detected document qa keyword",
            complexity_reason="Document QA task",
            tasks=[
                PlanStep(
                    step_id=1,
                    step_type=StepType.RETRIEVE,
                    description="Retrieve Apple financial report",
                    company="Apple",
                    query=context.question,
                ),
                PlanStep(
                    step_id=2,
                    step_type=StepType.SYNTHESIS,
                    description="Synthesize findings",
                    depends_on=[1],
                ),
            ],
        )
        return plan, task_result, complexity_result

    def build_routing_context(
        self,
        task_result: TaskResult,
        complexity_result: ComplexityResult | None = None,
    ) -> RoutingContext:
        ctx = RoutingContext(
            task=task_result.task.task_type,
            estimated_tokens=task_result.estimated_tokens,
            priority=RoutingPriority.BALANCED,
        )
        if complexity_result is not None:
            ctx.complexity_score = complexity_result.complexity.score
        return ctx


class FakeReasoner:
    def analyze(self, results):
        return ReasoningResult(
            facts=["Revenue grew 10%."],
            risks=[],
            opportunities=["Strong growth."],
            conclusion="Collected 1 financial facts, 0 risk signals, and 1 opportunity signals.",
        )


class FakeExecutor:
    def __init__(self):
        self._handlers = {}

    def register_handler(self, step_type, handler):
        self._handlers[step_type] = handler

    def execute(self, plan, shared):
        for step in plan.tasks:
            handler = self._handlers.get(step.step_type)
            if handler:
                try:
                    output = handler(step, shared)
                    step.status = StepStatus.COMPLETED
                    step.result = ExecutionResult(
                        step_id=step.step_id,
                        success=True,
                        output=output,
                    )
                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.result = ExecutionResult(
                        step_id=step.step_id,
                        success=False,
                        error=str(e),
                    )
        return plan


class TestAgentRuntime:
    @pytest.fixture
    def runtime(self):
        retriever = FakeRetriever()
        planner = FakePlanner()
        executor = FakeExecutor()
        reasoner = FakeReasoner()
        intent_analyzer = FakeIntentAnalyzer()

        def retrieve_handler(step, shared):
            ctx = MagicMock()
            ctx.question = step.query
            ctx.company = step.company
            evidences = retriever.retrieve_evidence(ctx, None)
            shared.setdefault("_all_evidence", []).extend(evidences)
            return evidences

        executor.register_handler(StepType.RETRIEVE, retrieve_handler)
        executor.register_handler(StepType.SYNTHESIS, lambda s, c: None)

        return AgentRuntime(
            planner=planner,
            executor=executor,
            reasoner=reasoner,
            retriever=retriever,
            intent_analyzer=intent_analyzer,
        )

    def test_run_returns_runtime_result(self, runtime):
        result = runtime.run("What is Apple revenue?")
        assert isinstance(result, RuntimeResult)
        assert result.context is not None
        assert result.citations is not None
        assert result.evidence is not None
        assert result.plan is not None
        assert result.intent_result is not None
        assert result.reasoning_result is not None

    def test_followup_context_uses_prior_user_entity_not_assistant_mentions(self):
        context = prior_user_context_for_followup(
            "What did it say about margins?",
            [
                {"role": "user", "content": "Tell me about Tesla's Q2 2025 performance."},
                {"role": "assistant", "content": "Apple's report is another example; NVIDIA is different."},
            ],
        )

        assert context == (
            "Tell me about Tesla's Q2 2025 performance.",
            ["Tesla"],
        )

    def test_followup_context_adds_previous_company_for_explicit_comparison(self):
        context = prior_user_context_for_followup(
            "Now compare it with Tesla.",
            [{"role": "user", "content": "Analyze Apple's Q2 2026 report."}],
        )

        assert context == ("Analyze Apple's Q2 2026 report.", ["Apple"])

    def test_companyless_growth_driver_followup_inherits_previous_company(self):
        context = prior_user_context_for_followup(
            "What was the main growth driver?",
            [{"role": "user", "content": "Summarize NVIDIA's financial performance."}],
        )

        assert context == (
            "Summarize NVIDIA's financial performance.",
            ["NVIDIA"],
        )

    def test_companyless_financial_table_followup_inherits_company_in_same_thread(self):
        context = prior_user_context_for_followup(
            "2025年直销和批发代理模式的收入分别是多少？各自同比如何变化？",
            [{"role": "user", "content": "贵州茅台2025年度收入表现如何？"}],
        )

        assert context == (
            "贵州茅台2025年度收入表现如何？",
            ["贵州茅台"],
        )

    def test_companyless_financial_followup_does_not_cross_general_question_boundary(self):
        context = prior_user_context_for_followup(
            "2025年直销和批发代理模式的收入分别是多少？各自同比如何变化？",
            [
                {"role": "user", "content": "贵州茅台2025年度收入表现如何？"},
                {"role": "assistant", "content": "我可以概述年报。"},
                {"role": "user", "content": "什么是同比？"},
            ],
        )

        assert context is None

    def test_focus_only_growth_driver_followup_inherits_all_compared_companies(self):
        history = [{"role": "user", "content": "Compare Apple and NVIDIA."}]

        assert prior_user_context_for_followup(
            "Focus only on the business growth drivers.", history
        ) == ("Compare Apple and NVIDIA.", ["Apple", "NVIDIA"])
        assert prior_user_context_for_followup(
            "只重点比较它们的业务增长动力。", history
        ) == ("Compare Apple and NVIDIA.", ["Apple", "NVIDIA"])

    def test_new_topic_does_not_inherit_a_prior_company(self):
        assert prior_user_context_for_followup(
            "What is gross margin?",
            [{"role": "user", "content": "Tell me about Tesla's Q2 2025 performance."}],
        ) is None

    def test_followup_does_not_resurrect_company_across_standalone_topic_boundary(self):
        assert prior_user_context_for_followup(
            "What did it say about margins?",
            [
                {"role": "user", "content": "Tell me about Tesla's Q2 2025 performance."},
                {"role": "assistant", "content": "Tesla's Q2 revenue was $22.496 billion."},
                {"role": "user", "content": "What is gross margin?"},
            ],
        ) is None

    def test_chained_entityless_followups_keep_nearest_active_company(self):
        assert prior_user_context_for_followup(
            "And operating margin?",
            [
                {"role": "user", "content": "Tell me about Tesla's Q2 2025 performance."},
                {"role": "assistant", "content": "Tesla's Q2 revenue was $22.496 billion."},
                {"role": "user", "content": "What about margins?"},
                {"role": "assistant", "content": "Gross margin details."},
            ],
        ) == ("Tell me about Tesla's Q2 2025 performance.", ["Tesla"])

    def test_followup_retrieval_scope_inherits_company_and_period(self, runtime):
        result = runtime.run(
            "What did it say about margins?",
            conversation_history=[
                {"role": "user", "content": "Tell me about Tesla's Q2 2025 performance."},
                {"role": "assistant", "content": "Apple also reported strong services revenue."},
            ],
        )

        assert "Tesla" in result.resolved_question
        assert "Q2_2025" in result.resolved_question
        assert "Tesla's Q2 2025 performance" not in result.resolved_question
        assert runtime.planner.last_context.companies == ["Tesla"]
        assert "Q2_2025" in runtime.planner.last_context.question

    def test_financial_table_followup_inherits_scope_without_prior_dimensions(self, runtime):
        prior_question = "贵州茅台2025年度国内和国外主营业务收入分别是多少？"
        current_question = "2025年直销和批发代理模式的收入分别是多少？各自同比如何变化？"

        result = runtime.run(
            current_question,
            conversation_history=[{"role": "user", "content": prior_question}],
        )

        assert current_question in result.resolved_question
        assert "贵州茅台" in result.resolved_question
        assert "FY2025" in result.resolved_question
        assert "国内和国外" not in result.resolved_question
        assert "批发代理" in result.resolved_question

    def test_growth_driver_followup_is_planned_as_company_document_qa(self, runtime):
        from agent.query_planner import QueryPlanner

        runtime.planner = QueryPlanner()
        result = runtime.run(
            "What was the main growth driver?",
            conversation_history=[
                {"role": "user", "content": "Summarize NVIDIA's financial performance."},
                {"role": "assistant", "content": "NVIDIA reported strong quarterly results."},
            ],
        )

        retrieval_steps = [
            step for step in result.plan.tasks if step.step_type is StepType.RETRIEVE
        ]
        assert "NVIDIA" in result.resolved_question
        assert "Summarize NVIDIA's financial performance." not in result.resolved_question
        assert retrieval_steps
        assert all(step.company == "NVIDIA" for step in retrieval_steps)
        assert result.plan.task_type is TaskType.DOCUMENT_QA

    def test_comparison_followup_keeps_new_and_inherited_companies(self, runtime):
        runtime.run(
            "Now compare it with Tesla.",
            conversation_history=[{"role": "user", "content": "Analyze Apple's Q2 2026 report."}],
        )

        assert runtime.planner.last_context.companies == ["Tesla", "Apple"]

    def test_run_with_company(self, runtime):
        result = runtime.run("Revenue analysis", company="Apple")
        assert isinstance(result, RuntimeResult)

    def test_run_produces_evidence(self, runtime):
        result = runtime.run("What is Apple revenue?")
        assert len(result.evidence) >= 1
        assert result.evidence[0].source == "apple.pdf"

    def test_run_produces_citations(self, runtime):
        result = runtime.run("What is Apple revenue?")
        assert len(result.citations) >= 1
        assert result.citations[0]["source"] == "apple.pdf"

    def test_run_produces_context(self, runtime):
        result = runtime.run("What is Apple revenue?")
        assert "Evidence 1" in result.context
        assert "apple.pdf" in result.context

    def test_run_produces_plan(self, runtime):
        result = runtime.run("What is Apple revenue?")
        assert result.plan.intent == "single_company"
        assert len(result.plan.tasks) == 2

    def test_run_produces_intent_result(self, runtime):
        result = runtime.run("What is Apple revenue?")
        assert result.intent_result["intent"] == "SINGLE_COMPANY"
        assert "Apple" in result.intent_result["companies"]

    def test_run_produces_reasoning_result(self, runtime):
        result = runtime.run("What is Apple revenue?")
        assert "Revenue grew" in result.reasoning_result.facts[0]
        assert result.reasoning_result.conclusion != ""
