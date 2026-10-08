# ============================================================
# MemoryEngine — Memory Layer Orchestrator
# ============================================================
# The MemoryEngine is the single entry point for the
# Memory Layer. It receives a MemoryContext, creates the
# appropriate Memory instance via Factory, and delegates
# store / retrieve to that instance.
#
# The Engine does NOT make business decisions.
# It does NOT know about:
#   - Which memory to use (determined by caller or context)
#   - Redis / SQLite / Chroma / Vector DB
#   - Memory Compression / Ranking / Eviction
#   - Provider / Runtime / Tool
#
# It ONLY orchestrates:
#   Context → Factory → Memory.store() / Memory.retrieve() → Result
#
# Mirrors:
#   agent.workflow.WorkflowEngine    → MemoryEngine
#   agent.execution.ExecutionEngine  → MemoryEngine
#   llm.router.ModelRouter           → MemoryEngine
# ============================================================

from typing import Optional, Union

from .base_memory import BaseMemory
from .memory_context import MemoryContext
from .memory_enums import MemoryType
from .memory_factory import MemoryFactory
from .memory_result import MemoryResult


class MemoryEngine:
    def __init__(self) -> None:
        self._default_memory_type: MemoryType = MemoryType.SESSION

    # ============================================================
    # Default memory type
    # ============================================================

    def set_default_memory_type(self, memory_type: Union[str, MemoryType]) -> None:
        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)
        self._default_memory_type = memory_type

    # ============================================================
    # Store
    # ============================================================

    def store(
        self,
        context: MemoryContext,
        memory_type: Optional[Union[str, MemoryType]] = None,
    ) -> MemoryResult:
        memory = self._resolve_memory(memory_type)
        return memory.store(context)

    # ============================================================
    # Retrieve
    # ============================================================

    def retrieve(
        self,
        context: MemoryContext,
        memory_type: Optional[Union[str, MemoryType]] = None,
    ) -> MemoryResult:
        memory = self._resolve_memory(memory_type)
        return memory.retrieve(context)

    # ============================================================
    # Internal helpers
    # ============================================================

    def _resolve_memory(self, memory_type: Optional[Union[str, MemoryType]]) -> BaseMemory:
        if memory_type is None:
            memory_type = self._default_memory_type
        return MemoryFactory.create(memory_type)
