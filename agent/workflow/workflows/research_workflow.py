# ============================================================
# ResearchWorkflow — Skeleton
# ============================================================
# 深度研究流程：Plan → Retrieve → Analyze → Synthesize → Verify
# 多步串行，需要检索和推理。
# ============================================================

from agent.execution.strategy_enums import ExecutionStrategyType
from agent.workflow.base_workflow import BaseWorkflow
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult


class ResearchWorkflow(BaseWorkflow):
    @property
    def workflow_name(self) -> str:
        return "multi_step"

    def supports(self, context: WorkflowContext) -> bool:
        return True

    def build(self, context: WorkflowContext) -> WorkflowResult:
        return WorkflowResult(
            workflow=WorkflowType.MULTI_STEP,
            steps=[
                WorkflowStep(
                    step_id="plan",
                    name="Plan",
                    description="Decompose research question into sub-questions",
                    required=True,
                    metadata={"strategy": "multi_step"},
                ),
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve documents for each sub-question",
                    required=True,
                    depends_on=["plan"],
                    metadata={
                        "strategy": "multi_step",
                        "tool": {
                            "name": "retrieval",
                            "parameters": {"top_k": 10, "threshold": 0.7},
                        },
                    },
                ),
                WorkflowStep(
                    step_id="analyze",
                    name="Analyze",
                    description="Analyze evidence across sub-questions",
                    required=True,
                    depends_on=["retrieve"],
                    metadata={
                        "strategy": "multi_step",
                        "tool": {
                            "name": "python",
                            "parameters": {"mode": "analysis"},
                        },
                    },
                ),
                WorkflowStep(
                    step_id="synthesize",
                    name="Synthesize",
                    description="Synthesize findings into coherent report",
                    required=True,
                    depends_on=["analyze"],
                    metadata={"strategy": "multi_step"},
                ),
                WorkflowStep(
                    step_id="verify",
                    name="Verify",
                    description="Verify claims against source documents",
                    required=False,
                    depends_on=["synthesize"],
                    metadata={"strategy": "multi_step"},
                ),
            ],
            estimated_time_ms=5000,
            requires_tools=False,
            requires_memory=True,
            requires_human=False,
            confidence=0.85,
            reason="Multi-step research: Plan → Retrieve → Analyze → Synthesize → Verify",
            execution_strategy=ExecutionStrategyType.MULTI_STEP,
            requires_retrieval=True,
            requires_parallel=False,
            estimated_execution_steps=5,
        )
