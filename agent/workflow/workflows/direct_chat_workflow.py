# ============================================================
# DirectChatWorkflow — Skeleton
# ============================================================
# 最简单的 Workflow：单步 Direct LLM 对话
# 不需要检索、不需要工具、不需要多步推理。
# ============================================================

from agent.execution.strategy_enums import ExecutionStrategyType
from agent.workflow.base_workflow import BaseWorkflow
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult


class DirectChatWorkflow(BaseWorkflow):
    @property
    def workflow_name(self) -> str:
        return "direct_chat"

    def supports(self, context: WorkflowContext) -> bool:
        return True

    def build(self, context: WorkflowContext) -> WorkflowResult:
        return WorkflowResult(
            workflow=WorkflowType.DIRECT_CHAT,
            steps=[
                WorkflowStep(
                    step_id="chat",
                    name="Direct Chat",
                    description="Single-step LLM response",
                    required=True,
                    metadata={"strategy": "direct_llm"},
                ),
            ],
            estimated_time_ms=500,
            requires_tools=False,
            requires_memory=False,
            requires_human=False,
            confidence=1.0,
            reason="Direct chat — no retrieval or multi-step needed",
            execution_strategy=ExecutionStrategyType.DIRECT_LLM,
            requires_retrieval=False,
            requires_parallel=False,
            estimated_execution_steps=1,
        )
