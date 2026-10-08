# ============================================================
# RagStrategy — Retrieval-Augmented Generation execution
# ============================================================
# Best for document QA, research, and financial analysis
# tasks that require retrieval from a knowledge base.
# ============================================================

from ...planning import ComplexityLevel, TaskType
from ..execution_context import ExecutionContext
from ..execution_result import ExecutionResult
from ..execution_strategy import BaseExecutionStrategy
from ..strategy_enums import ExecutionStrategyType


class RagStrategy(BaseExecutionStrategy):
    @property
    def strategy_name(self) -> str:
        return "rag"

    @property
    def priority(self) -> int:
        return 90

    def supports(self, context: ExecutionContext) -> bool:
        task_type = context.task.task.task_type
        complexity = context.complexity.complexity.level
        return task_type in (
            TaskType.DOCUMENT_QA,
            TaskType.RESEARCH,
            TaskType.FINANCIAL_ANALYSIS,
        ) and complexity in (ComplexityLevel.LOW, ComplexityLevel.MEDIUM)

    def build(self, context: ExecutionContext) -> ExecutionResult:
        task_type = context.task.task.task_type.value
        return ExecutionResult(
            strategy=ExecutionStrategyType.RAG,
            reason=f"{task_type} task — RAG with retrieval",
            estimated_steps=3,
            parallelism=1,
            use_retrieval=True,
            use_tools=False,
            confidence=0.9,
        )
