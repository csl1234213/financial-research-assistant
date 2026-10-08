# ============================================================
# Memory Registry — Central registration for all memory implementations
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new memories without modifying Factory
# 2. Plugin architecture: Memories can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
#
# Mirrors:
#   MemoryRegistry ↔ WorkflowRegistry
#   MemoryRegistry ↔ StrategyRegistry
#   MemoryRegistry ↔ ProviderRegistry
# ============================================================

from typing import Dict, List, Type

from .base_memory import BaseMemory
from .memory_exceptions import MemoryNotFound, MemoryRegistrationError


class MemoryRegistry:
    _registry: Dict[str, Type[BaseMemory]] = {}

    @classmethod
    def register(cls, name: str, memory_class: Type[BaseMemory]) -> None:
        if not issubclass(memory_class, BaseMemory):
            raise MemoryRegistrationError(f"'{memory_class.__name__}' must be a subclass of BaseMemory")
        cls._registry[name] = memory_class

    @classmethod
    def get(cls, name: str) -> Type[BaseMemory]:
        if not cls.has_memory(name):
            raise MemoryNotFound(f"Memory '{name}' not registered. Available: {cls.list_memories()}")
        return cls._registry[name]

    @classmethod
    def list_memories(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def has_memory(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
