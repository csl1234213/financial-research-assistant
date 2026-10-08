# ============================================================
# RAGWorkflow — Skeleton
# ============================================================
# 典型 RAG 流程：Retrieve → Reason → Answer
# 三步串行，依赖检索结果。
# ============================================================

from agent.execution.strategy_enums import ExecutionStrategyType
from agent.workflow.base_workflow import BaseWorkflow
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult


class RAGWorkflow(BaseWorkflow):
    @property
    def workflow_name(self) -> str:
        return "rag"

    def supports(self, context: WorkflowContext) -> bool:
        return True

    def build(self, context: WorkflowContext) -> WorkflowResult:
        return WorkflowResult(
            workflow=WorkflowType.RAG,
            steps=[
                WorkflowStep(
                    step_id="retrieve",
                    name="Retrieve",
                    description="Retrieve relevant documents from knowledge base",
                    required=True,
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
                    description="Reason over retrieved evidence",
                    required=True,
                    depends_on=["retrieve"],
                    metadata={"strategy": "rag"},
                ),
                WorkflowStep(
                    step_id="answer",
                    name="Answer",
                    description="Generate final answer with citations",
                    required=True,
                    depends_on=["reason"],
                    metadata={"strategy": "rag"},
                ),
            ],
            estimated_time_ms=2000,
            requires_tools=False,
            requires_memory=False,
            requires_human=False,
            confidence=0.95,
            reason="Standard RAG: Retrieve → Reason → Answer",
            execution_strategy=ExecutionStrategyType.RAG,
            requires_retrieval=True,
            requires_parallel=False,
            estimated_execution_steps=3,
        )
