# ============================================================
# DirectLLMStrategy — Direct single-call LLM execution
# ============================================================
# Best for simple, low-complexity tasks that do not require
# retrieval, multi-step reasoning, or tool use.
# ============================================================

from ...planning import ComplexityLevel, TaskType
from ..execution_context import ExecutionContext
from ..execution_result import ExecutionResult
from ..execution_strategy import BaseExecutionStrategy
from ..strategy_enums import ExecutionStrategyType


class DirectLLMStrategy(BaseExecutionStrategy):
    @property
    def strategy_name(self) -> str:
        return "direct_llm"

    @property
    def priority(self) -> int:
        return 10

    def supports(self, context: ExecutionContext) -> bool:
        task_type = context.task.task.task_type
        complexity = context.complexity.complexity.level
        return task_type in (TaskType.CHAT, TaskType.SUMMARIZATION) and complexity in (
            ComplexityLevel.LOW,
            ComplexityLevel.MEDIUM,
        )

    def build(self, context: ExecutionContext) -> ExecutionResult:
        task_type = context.task.task.task_type.value
        return ExecutionResult(
            strategy=ExecutionStrategyType.DIRECT_LLM,
            reason=f"Simple {task_type} task — direct LLM sufficient",
            estimated_steps=1,
            parallelism=1,
            use_retrieval=False,
            use_tools=False,
            confidence=0.95,
        )
