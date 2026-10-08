from threading import Lock

from agent.execution_plan import ExecutionPlan, PlanStep, StepType
from agent.planning import (
    ComplexityAnalyzer,
    ComplexityResult,
    PlanningContext,
    TaskAnalyzer,
    TaskResult,
    TaskType,
)
from agent.planning.financial_metric_parser import (
    FinancialMetricInvocation,
    parse_financial_metric_query,
)
from llm.router import RoutingContext, RoutingPriority
from retrieval.periods import query_filters


class QueryPlanner:
    """
    V4 Query Planner

    Consumes TaskResult from TaskAnalyzer and produces
    ExecutionPlan with full planner + complexity metadata.

    Pipeline:
      PlanningContext
          ↓
      TaskAnalyzer → TaskResult
          ↓
      ComplexityAnalyzer → ComplexityResult
          ↓
      ExecutionPlan
    """

    def __init__(self):
        self._step_counter = 1
        self._plan_lock = Lock()
        self.task_analyzer = TaskAnalyzer()
        self.complexity_analyzer = ComplexityAnalyzer()

    def _next_id(self):
        sid = self._step_counter
        self._step_counter += 1
        return sid

    def _reset_counter(self):
        self._step_counter = 1

    # =========================
    # Main Entry
    # =========================

    def plan(
        self,
        context: PlanningContext,
    ) -> tuple[ExecutionPlan, TaskResult, ComplexityResult]:
        # The production runtime owns one planner shared by concurrent FastAPI
        # requests. The rule engine is fast, and serializing this small
        # stateful section prevents request plans from corrupting step IDs.
        with self._plan_lock:
            return self._plan_serialized(context)

    def _plan_serialized(
        self,
        context: PlanningContext,
    ) -> tuple[ExecutionPlan, TaskResult, ComplexityResult]:
        self._reset_counter()

        task_result = self.task_analyzer.analyze(context)
        complexity_result = self.complexity_analyzer.analyze(task_result)
        task_type = task_result.task.task_type
        retrieval_filters = query_filters(context.question)

        companies = [e for e in task_result.extracted_entities if not e.isdigit()]
        metric_invocation = parse_financial_metric_query(context.question)

        if metric_invocation is not None:
            plan = self._build_financial_metric_plan(
                context.question,
                metric_invocation,
            )
        elif task_type == TaskType.COMPARISON:
            plan = self._build_compare_plan(context.question, companies, retrieval_filters)
        elif task_type == TaskType.DOCUMENT_QA:
            plan = self._build_single_plan(context.question, companies, retrieval_filters)
        elif task_type in (TaskType.RESEARCH, TaskType.FINANCIAL_ANALYSIS):
            plan = self._build_global_plan(context.question, retrieval_filters)
        else:
            plan = self._build_generic_plan(context.question)

        plan.task_type = task_result.task.task_type
        plan.complexity = complexity_result.complexity.level
        plan.complexity_score = complexity_result.complexity.score
        plan.estimated_tokens = complexity_result.complexity.estimated_tokens
        plan.estimated_latency_ms = complexity_result.complexity.estimated_latency_ms
        plan.estimated_cost = complexity_result.complexity.estimated_cost
        plan.planner_reason = task_result.reason
        plan.complexity_reason = complexity_result.reason

        return plan, task_result, complexity_result

    # =========================
    # Governed Financial Tool
    # =========================

    def _build_financial_metric_plan(
        self,
        query: str,
        invocation: FinancialMetricInvocation,
    ) -> ExecutionPlan:
        plan = ExecutionPlan(
            intent="financial_calculation",
            original_query=query,
            metadata={
                "tool_policy": "financial_metrics_only",
                "deterministic": True,
            },
        )
        plan.tasks.append(
            PlanStep(
                step_id=self._next_id(),
                step_type=StepType.TOOL_CALL,
                description=f"Calculate {invocation.operation}",
                query=query,
                parameters=dict(invocation.parameters),
                tool_name=invocation.tool_name,
            )
        )
        return plan

    # =========================
    # Routing Context
    # =========================

    def build_routing_context(
        self,
        task_result: TaskResult,
        complexity_result: ComplexityResult | None = None,
    ) -> RoutingContext:
        task_type = task_result.task.task_type

        ctx = RoutingContext(
            task=task_type,
            priority=self._priority_for(task_type),
            estimated_tokens=task_result.estimated_tokens,
        )

        if complexity_result is not None:
            ctx.complexity_score = complexity_result.complexity.score

        return ctx

    def _priority_for(self, task_type: TaskType) -> RoutingPriority:
        if task_type in (TaskType.RESEARCH, TaskType.FINANCIAL_ANALYSIS):
            return RoutingPriority.QUALITY
        if task_type == TaskType.COMPARISON:
            return RoutingPriority.BALANCED
        return RoutingPriority.BALANCED

    # =========================
    # 1. Compare Plan
    # =========================

    def _build_compare_plan(self, query, companies, retrieval_filters=None) -> ExecutionPlan:
        plan = ExecutionPlan(intent="comparison", original_query=query)

        retrieve_ids = []

        for c in companies:
            step = PlanStep(
                step_id=self._next_id(),
                step_type=StepType.RETRIEVE,
                description=f"Retrieve {c} financial report",
                company=c,
                query=query,
                parameters={
                    "metrics": ["revenue", "margin", "risk"],
                    "filters": dict(retrieval_filters or {}),
                },
            )
            plan.tasks.append(step)
            retrieve_ids.append(step.step_id)

        compare_step = PlanStep(
            step_id=self._next_id(),
            step_type=StepType.COMPARE,
            description=f"Compare {', '.join(companies)}",
            query=query,
            parameters={"companies": companies},
            depends_on=retrieve_ids if retrieve_ids else [],
        )
        plan.tasks.append(compare_step)

        synthesis_step = PlanStep(
            step_id=self._next_id(),
            step_type=StepType.SYNTHESIS,
            description="Synthesize comparison results",
            query=query,
            depends_on=[compare_step.step_id],
        )
        plan.tasks.append(synthesis_step)

        return plan

    # =========================
    # 2. Single Company Plan
    # =========================

    def _build_single_plan(self, query, companies, retrieval_filters=None) -> ExecutionPlan:
        company = companies[0] if companies else None

        plan = ExecutionPlan(
            intent="single_company",
            original_query=query,
        )

        retrieve_step = PlanStep(
            step_id=self._next_id(),
            step_type=StepType.RETRIEVE,
            description=f"Retrieve {company} documents" if company else "Retrieve relevant documents",
            company=company,
            query=query,
            parameters={"filters": dict(retrieval_filters or {})},
        )
        plan.tasks.append(retrieve_step)

        analysis_step = PlanStep(
            step_id=self._next_id(),
            step_type=StepType.REASONING,
            description="Analyze retrieved data",
            query=query,
            depends_on=[retrieve_step.step_id],
        )
        plan.tasks.append(analysis_step)

        return plan

    # =========================
    # 3. Global Research Plan
    # =========================

    def _build_global_plan(self, query, retrieval_filters=None) -> ExecutionPlan:
        plan = ExecutionPlan(
            intent="global_research",
            original_query=query,
        )

        retrieve_step = PlanStep(
            step_id=self._next_id(),
            step_type=StepType.RETRIEVE,
            description="Retrieve industry-wide documents",
            query=query,
            parameters={"top_k": 6, "filters": dict(retrieval_filters or {})},
        )
        plan.tasks.append(retrieve_step)

        synthesis_step = PlanStep(
            step_id=self._next_id(),
            step_type=StepType.SYNTHESIS,
            description="Synthesize research findings",
            query=query,
            depends_on=[retrieve_step.step_id],
        )
        plan.tasks.append(synthesis_step)

        return plan

    # =========================
    # 4. Generic Plan
    # =========================

    def _build_generic_plan(self, query) -> ExecutionPlan:
        plan = ExecutionPlan(
            intent="generic",
            original_query=query,
        )

        retrieve_step = PlanStep(
            step_id=self._next_id(),
            step_type=StepType.RETRIEVE,
            description="Retrieve relevant documents",
            query=query,
        )
        plan.tasks.append(retrieve_step)

        return plan
