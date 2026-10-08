# ============================================================
# ParallelStrategy — Parallel sub-task execution
# ============================================================
# Best for comparison and multi-entity tasks that can
# benefit from parallel retrieval and processing.
# ============================================================

from ...planning import ComplexityLevel, TaskType
from ..execution_context import ExecutionContext
from ..execution_result import ExecutionResult
from ..execution_strategy import BaseExecutionStrategy
from ..strategy_enums import ExecutionStrategyType


class ParallelStrategy(BaseExecutionStrategy):
    @property
    def strategy_name(self) -> str:
        return "parallel"

    @property
    def priority(self) -> int:
        return 85

    def supports(self, context: ExecutionContext) -> bool:
        task_type = context.task.task.task_type
        complexity = context.complexity.complexity.level
        companies = context.task.extracted_entities
        return (
            task_type == TaskType.COMPARISON
            and complexity in (ComplexityLevel.MEDIUM, ComplexityLevel.HIGH)
            and len(companies) >= 2
        )

    def build(self, context: ExecutionContext) -> ExecutionResult:
        company_count = len(context.task.extracted_entities)
        return ExecutionResult(
            strategy=ExecutionStrategyType.PARALLEL,
            reason=f"Multi-entity comparison ({company_count} entities) — parallel execution",
            estimated_steps=2,
            parallelism=min(company_count, 4),
            use_retrieval=True,
            use_tools=False,
            confidence=0.85,
        )
