# ============================================================
# BaseExecutionStrategy — Abstract interface for all execution strategies
# ============================================================
# Every concrete execution strategy (RAG, DirectLLM, Parallel,
# MultiStep, ToolCalling, etc.) must implement this interface.
#
# Mirrors llm.providers.BaseProvider in structure:
#   BaseExecutionStrategy ↔ BaseProvider
# ============================================================

from abc import ABC, abstractmethod

from .execution_context import ExecutionContext
from .execution_result import ExecutionResult


class BaseExecutionStrategy(ABC):
    @property
    @abstractmethod
    def strategy_name(self) -> str: ...

    @property
    def priority(self) -> int:
        return 100

    @abstractmethod
    def supports(
        self,
        context: ExecutionContext,
    ) -> bool: ...

    @abstractmethod
    def build(
        self,
        context: ExecutionContext,
    ) -> ExecutionResult: ...
