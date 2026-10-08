# ============================================================
# Memories — Auto-registration
# ============================================================
# Importing this package automatically registers all built-in
# memory classes into the MemoryRegistry.
#
# Mirrors:
#   agent.memory.memories.__init__  ↔ agent.workflow.workflows.__init__
#   agent.memory.memories.__init__  ↔ agent.execution.strategies.__init__
# ============================================================

from agent.memory.memory_registry import MemoryRegistry

from .long_term_memory import LongTermMemory
from .session_memory import SessionMemory
from .short_term_memory import ShortTermMemory
from .workflow_memory import WorkflowMemory

MemoryRegistry.register("short_term", ShortTermMemory)
MemoryRegistry.register("session", SessionMemory)
MemoryRegistry.register("workflow", WorkflowMemory)
MemoryRegistry.register("long_term", LongTermMemory)

__all__ = [
    "LongTermMemory",
    "SessionMemory",
    "ShortTermMemory",
    "WorkflowMemory",
]
