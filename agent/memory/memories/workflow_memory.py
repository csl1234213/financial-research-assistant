# ============================================================
# WorkflowMemory — 当前 Workflow 生命周期内的记忆
# ============================================================
# 生命周期：单次 Workflow 执行。
# 跨多个 ExecutionStep，Workflow 完成或失败后释放。
# ============================================================

from agent.memory.base_memory import BaseMemory
from agent.memory.memory_context import MemoryContext
from agent.memory.memory_enums import MemoryType
from agent.memory.memory_result import MemoryResult


class WorkflowMemory(BaseMemory):
    @property
    def memory_name(self) -> str:
        return MemoryType.WORKFLOW.value

    def supports(self, context: MemoryContext) -> bool:
        return True

    def store(self, context: MemoryContext) -> MemoryResult:
        return MemoryResult(
            records=[],
            retrieved_count=0,
            confidence=1.0,
            reason="WorkflowMemory skeleton — store not yet implemented",
        )

    def retrieve(self, context: MemoryContext) -> MemoryResult:
        return MemoryResult(
            records=[],
            retrieved_count=0,
            confidence=1.0,
            reason="WorkflowMemory skeleton — retrieve not yet implemented",
        )
