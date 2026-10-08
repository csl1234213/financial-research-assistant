# ============================================================
# LongTermMemory — 跨 Session 持久化记忆
# ============================================================
# 生命周期：持久化，跨 Session 保留。
# 用于存储用户偏好、常用查询模式、历史决策等。
# 未来接入 Redis / SQLite / Chroma 等持久化存储。
# ============================================================

from agent.memory.base_memory import BaseMemory
from agent.memory.memory_context import MemoryContext
from agent.memory.memory_enums import MemoryType
from agent.memory.memory_result import MemoryResult


class LongTermMemory(BaseMemory):
    @property
    def memory_name(self) -> str:
        return MemoryType.LONG_TERM.value

    def supports(self, context: MemoryContext) -> bool:
        return True

    def store(self, context: MemoryContext) -> MemoryResult:
        return MemoryResult(
            records=[],
            retrieved_count=0,
            confidence=1.0,
            reason="LongTermMemory skeleton — store not yet implemented",
        )

    def retrieve(self, context: MemoryContext) -> MemoryResult:
        return MemoryResult(
            records=[],
            retrieved_count=0,
            confidence=1.0,
            reason="LongTermMemory skeleton — retrieve not yet implemented",
        )
