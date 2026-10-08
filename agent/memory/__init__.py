# ============================================================
# Memory Layer
# ============================================================
# Memory Layer 是 Agent 的第四个核心 Layer。
# 它记录 Planning / Workflow / Execution 的生命周期信息，
# 为后续 Memory Compression / Long-Term Memory / Multi-Agent
# 提供统一的数据基础。
#
# 当前 Sprint 3：MemoryEngine 骨架编排。
# ============================================================

from .base_memory import BaseMemory

# Auto-register all built-in memory implementations
from .memories import (  # noqa: F401 — auto-registration
    LongTermMemory,
    SessionMemory,
    ShortTermMemory,
    WorkflowMemory,
)
from .memory_bridge import MemoryBridge
from .memory_context import MemoryContext
from .memory_engine import MemoryEngine
from .memory_enums import MemoryImportance, MemoryType
from .memory_exceptions import MemoryError, MemoryNotFound, MemoryRegistrationError
from .memory_factory import MemoryFactory
from .memory_models import MemoryRecord
from .memory_registry import MemoryRegistry
from .memory_result import MemoryResult

__all__ = [
    "BaseMemory",
    "MemoryBridge",
    "MemoryContext",
    "MemoryEngine",
    "MemoryError",
    "MemoryFactory",
    "MemoryImportance",
    "MemoryNotFound",
    "MemoryRecord",
    "MemoryRegistrationError",
    "MemoryRegistry",
    "MemoryResult",
    "MemoryType",
]
