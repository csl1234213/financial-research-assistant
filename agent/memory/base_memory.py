# ============================================================
# BaseMemory — Abstract interface for all memory implementations
# ============================================================
# 每一个具体 Memory（SessionMemory、WorkflowMemory、
# LongTermMemory 等）都必须实现这个接口。
#
# 设计原则：
#   - Memory 不负责决定「要不要记」— 由 Engine 决定
#   - Memory 只负责 store / retrieve / supports
#   - 不包含 Vector DB / Redis / Runtime 依赖
#
# Mirrors:
#   BaseExecutionStrategy ↔ BaseMemory
#   BaseWorkflow          ↔ BaseMemory
#   BaseProvider          ↔ BaseMemory
# ============================================================

from abc import ABC, abstractmethod

from .memory_context import MemoryContext
from .memory_result import MemoryResult


class BaseMemory(ABC):
    @property
    @abstractmethod
    def memory_name(self) -> str: ...

    @abstractmethod
    def supports(
        self,
        context: MemoryContext,
    ) -> bool: ...

    @abstractmethod
    def store(
        self,
        context: MemoryContext,
    ) -> MemoryResult: ...

    @abstractmethod
    def retrieve(
        self,
        context: MemoryContext,
    ) -> MemoryResult: ...
