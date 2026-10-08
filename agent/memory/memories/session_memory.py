# ============================================================
# SessionMemory — 当前聊天会话期间的记忆
# ============================================================
# 生命周期：单次 Chat Session。
# 可跨多轮对话，Session 结束即释放。
# ============================================================

from agent.memory.base_memory import BaseMemory
from agent.memory.memory_context import MemoryContext
from agent.memory.memory_enums import MemoryType
from agent.memory.memory_result import MemoryResult


class SessionMemory(BaseMemory):
    @property
    def memory_name(self) -> str:
        return MemoryType.SESSION.value

    def supports(self, context: MemoryContext) -> bool:
        return True

    def store(self, context: MemoryContext) -> MemoryResult:
        return MemoryResult(
            records=[],
            retrieved_count=0,
            confidence=1.0,
            reason="SessionMemory skeleton — store not yet implemented",
        )

    def retrieve(self, context: MemoryContext) -> MemoryResult:
        return MemoryResult(
            records=[],
            retrieved_count=0,
            confidence=1.0,
            reason="SessionMemory skeleton — retrieve not yet implemented",
        )
