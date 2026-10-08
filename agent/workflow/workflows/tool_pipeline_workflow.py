"""Declarative workflow for a single governed Agent tool call."""

from agent.execution.strategy_enums import ExecutionStrategyType
from agent.workflow.base_workflow import BaseWorkflow
from agent.workflow.workflow_context import WorkflowContext
from agent.workflow.workflow_enums import WorkflowType
from agent.workflow.workflow_models import WorkflowStep
from agent.workflow.workflow_result import WorkflowResult


class ToolPipelineWorkflow(BaseWorkflow):
    """Describe tool orchestration without executing the tool.

    The runtime dispatcher is the sole execution owner.  Keeping tool metadata
    off the workflow step prevents the workflow progress runner from invoking
    a second, ungoverned ToolEngine.
    """

    @property
    def workflow_name(self) -> str:
        return "tool_pipeline"

    def supports(self, context: WorkflowContext) -> bool:
        return (
            context.execution.strategy
            is ExecutionStrategyType.TOOL_CALLING
        )

    def build(self, context: WorkflowContext) -> WorkflowResult:
        return WorkflowResult(
            workflow=WorkflowType.TOOL_PIPELINE,
            steps=[
                WorkflowStep(
                    step_id="governed_tool_call",
                    name="Governed Financial Metric",
                    description=(
                        "Execute the planner-approved financial metric"
                    ),
                    required=True,
                    metadata={"strategy": "tool_calling"},
                )
            ],
            estimated_time_ms=10,
            requires_tools=True,
            requires_memory=False,
            requires_human=False,
            confidence=1.0,
            reason="Planner-approved deterministic financial calculation",
            execution_strategy=ExecutionStrategyType.TOOL_CALLING,
            requires_retrieval=False,
            requires_parallel=False,
            estimated_execution_steps=1,
        )
