# ============================================================
# ComparisonWorkflow — Skeleton
# ============================================================
# 对比分析流程：Retrieve A + Retrieve B → Compare → Synthesize
# 前两步可并行，最后两步串行。
# ============================================================

from agent.execution.strategy_enums import ExecutionStrategyType
from agent.workflow.base_workflow import BaseWorkflow
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult


class ComparisonWorkflow(BaseWorkflow):
    @property
    def workflow_name(self) -> str:
        return "parallel"

    def supports(self, context: WorkflowContext) -> bool:
        return True

    def build(self, context: WorkflowContext) -> WorkflowResult:
        return WorkflowResult(
            workflow=WorkflowType.PARALLEL,
            steps=[
                WorkflowStep(
                    step_id="retrieve_a",
                    name="Retrieve Entity A",
                    description="Retrieve documents for first entity",
                    required=True,
                    metadata={
                        "strategy": "parallel",
                        "tool": {
                            "name": "retrieval",
                            "parameters": {"top_k": 5, "entity": "A"},
                        },
                    },
                ),
                WorkflowStep(
                    step_id="retrieve_b",
                    name="Retrieve Entity B",
                    description="Retrieve documents for second entity",
                    required=True,
                    metadata={
                        "strategy": "parallel",
                        "tool": {
                            "name": "retrieval",
                            "parameters": {"top_k": 5, "entity": "B"},
                        },
                    },
                ),
                WorkflowStep(
                    step_id="compare",
                    name="Compare",
                    description="Compare and contrast findings across entities",
                    required=True,
                    depends_on=["retrieve_a", "retrieve_b"],
                    metadata={"strategy": "parallel"},
                ),
                WorkflowStep(
                    step_id="synthesize",
                    name="Synthesize",
                    description="Synthesize comparison into structured output",
                    required=True,
                    depends_on=["compare"],
                    metadata={"strategy": "parallel"},
                ),
            ],
            estimated_time_ms=3000,
            requires_tools=False,
            requires_memory=False,
            requires_human=False,
            confidence=0.90,
            reason="Parallel comparison: Retrieve A ‖ Retrieve B → Compare → Synthesize",
            execution_strategy=ExecutionStrategyType.PARALLEL,
            requires_retrieval=True,
            requires_parallel=True,
            estimated_execution_steps=4,
        )
