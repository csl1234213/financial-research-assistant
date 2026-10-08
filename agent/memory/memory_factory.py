# ============================================================
# Memory Factory — Creates memory instances by name or type
# ============================================================
# The Factory only knows how to create, not which memories exist.
# That knowledge lives in the Registry.
#
# Usage:
#   memory = MemoryFactory.create("session")
#   memory = MemoryFactory.create(MemoryType.SESSION)
#   result = memory.store(context)
#
# Mirrors:
#   MemoryFactory ↔ WorkflowFactory
#   MemoryFactory ↔ StrategyFactory
# ============================================================

from typing import Optional, Union

from .base_memory import BaseMemory
from .memory_enums import MemoryType
from .memory_registry import MemoryRegistry


class MemoryFactory:
    _default_memory: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, name: Union[str, MemoryType]) -> BaseMemory:
        if isinstance(name, MemoryType):
            name = name.value
        memory_class = MemoryRegistry.get(name)
        return memory_class()

    # ============================================================
    # Default memory
    # ============================================================

    @classmethod
    def set_default(cls, name: Union[str, MemoryType]) -> None:
        if isinstance(name, MemoryType):
            name = name.value
        if not MemoryRegistry.has_memory(name):
            raise KeyError(f"Cannot set default. Memory '{name}' not registered.")
        cls._default_memory = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_memory

    @classmethod
    def create_default(cls) -> BaseMemory:
        if cls._default_memory is None:
            raise RuntimeError("No default memory set. Call MemoryFactory.set_default(...) first.")
        return cls.create(cls._default_memory)
