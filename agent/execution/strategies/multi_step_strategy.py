# ============================================================
# MultiStepStrategy — Sequential multi-step execution
# ============================================================
# Best for complex comparison, research, and financial
# analysis tasks that require multiple reasoning steps.
# ============================================================

from ...planning import ComplexityLevel, TaskType
from ..execution_context import ExecutionContext
from ..execution_result import ExecutionResult
from ..execution_strategy import BaseExecutionStrategy
from ..strategy_enums import ExecutionStrategyType


class MultiStepStrategy(BaseExecutionStrategy):
    @property
    def strategy_name(self) -> str:
        return "multi_step"

    @property
    def priority(self) -> int:
        return 80

    def supports(self, context: ExecutionContext) -> bool:
        task_type = context.task.task.task_type
        complexity = context.complexity.complexity.level
        return (
            task_type
            in (
                TaskType.COMPARISON,
                TaskType.RESEARCH,
                TaskType.FINANCIAL_ANALYSIS,
            )
            and complexity == ComplexityLevel.HIGH
        )

    def build(self, context: ExecutionContext) -> ExecutionResult:
        task_type = context.task.task.task_type.value
        return ExecutionResult(
            strategy=ExecutionStrategyType.MULTI_STEP,
            reason=f"High-complexity {task_type} — multi-step reasoning required",
            estimated_steps=4,
            parallelism=1,
            use_retrieval=True,
            use_tools=False,
            confidence=0.8,
        )
