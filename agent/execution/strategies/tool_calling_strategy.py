# ============================================================
# ToolCallingStrategy — Tool-augmented execution
# ============================================================
# Production selection requires an explicit, allowlisted TOOL_CALL plan node.
# Legacy task-only callers remain supported for backwards compatibility, but
# the execution handler still fails closed unless the typed plan is present.
# ============================================================

from ...execution_plan import StepType
from ...planning import TaskType
from ..execution_context import ExecutionContext
from ..execution_result import ExecutionResult
from ..execution_strategy import BaseExecutionStrategy
from ..strategy_enums import ExecutionStrategyType


class ToolCallingStrategy(BaseExecutionStrategy):
    @property
    def strategy_name(self) -> str:
        return "tool_calling"

    @property
    def priority(self) -> int:
        # An explicit deterministic tool plan is more specific than a generic
        # RAG classification such as "revenue growth".
        return 100

    def supports(self, context: ExecutionContext) -> bool:
        if self._has_governed_financial_plan(context):
            return True

        # Strategy selection describes the capability a task requires. Actual
        # tool authorization remains fail-closed in ToolCallingHandler.
        task_type = context.task.task.task_type
        return task_type in (
            TaskType.OCR,
            TaskType.IMAGE_ANALYSIS,
            TaskType.CODE_GENERATION,
        )

    def build(self, context: ExecutionContext) -> ExecutionResult:
        if self._has_governed_financial_plan(context):
            step = context.plan.tasks[0]
            return ExecutionResult(
                strategy=ExecutionStrategyType.TOOL_CALLING,
                reason=(
                    "Explicit governed financial_metrics tool call: "
                    f"{step.parameters.get('operation', 'unknown')}"
                ),
                estimated_steps=1,
                parallelism=1,
                use_retrieval=False,
                use_tools=True,
                confidence=1.0,
            )

        task_type = context.task.task.task_type.value
        return ExecutionResult(
            strategy=ExecutionStrategyType.TOOL_CALLING,
            reason=f"{task_type} task — tool calling required",
            estimated_steps=3,
            parallelism=1,
            use_retrieval=False,
            use_tools=True,
            confidence=0.85,
        )

    @staticmethod
    def _has_governed_financial_plan(context: ExecutionContext) -> bool:
        return (
            context.plan is not None
            and len(context.plan.tasks) == 1
            and context.plan.tasks[0].step_type is StepType.TOOL_CALL
            and context.plan.tasks[0].tool_name == "financial_metrics"
        )
