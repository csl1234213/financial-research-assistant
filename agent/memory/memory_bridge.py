# ============================================================
# MemoryBridge — Thin bridge from RuntimeState to MemoryContext
# ============================================================
# AgentRuntime 不直接构建 MemoryContext。
# MemoryEngine 不 import AgentRuntime。
#
# 通过 MemoryBridge 完成：
#   RuntimeState + TaskResult → MemoryContext
#
# 这样：
#   - Runtime 与 Memory 保持低耦合
#   - MemoryContext 可以随需求扩展，不影响 RuntimeState
#   - 增加 Summary / Compression / Long-Term Memory 时，
#     只需调整 Bridge，不需修改 Runtime 或 MemoryEngine
#
# Mirrors:
#   WorkflowBridge (Workflow → Execution)
#   MemoryBridge  (Runtime  → Memory)
# ============================================================

from typing import Optional

from agent.planning import TaskResult
from agent.runtime_state import RuntimeState

from .memory_context import MemoryContext


class MemoryBridge:
    @staticmethod
    def to_memory_context(
        task_result: Optional[TaskResult] = None,
        runtime_state: Optional[RuntimeState] = None,
        question: Optional[str] = None,
        company: Optional[str] = None,
    ) -> MemoryContext:
        return MemoryContext(
            task=task_result,
            runtime_state=runtime_state or RuntimeState(),
            workflow=runtime_state.workflow if runtime_state else None,
            execution=list(runtime_state.execution) if runtime_state else [],
        )
