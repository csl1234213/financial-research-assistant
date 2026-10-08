# ============================================================
# Strategy Registry — Central registration for all execution strategies
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new strategies without modifying Factory
# 2. Plugin architecture: Strategies can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
#
# Mirrors llm.providers.ProviderRegistry in structure:
#   StrategyRegistry ↔ ProviderRegistry
# ============================================================

from typing import Dict, List, Type

from .execution_strategy import BaseExecutionStrategy


class StrategyRegistry:
    _registry: Dict[str, Type[BaseExecutionStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[BaseExecutionStrategy]) -> None:
        cls._registry[name] = strategy_class

    @classmethod
    def get(cls, name: str) -> Type[BaseExecutionStrategy]:
        return cls._registry[name]

    @classmethod
    def list_strategies(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def list_instances(cls) -> List[BaseExecutionStrategy]:
        return [cls._registry[name]() for name in cls._registry]

    @classmethod
    def has_strategy(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
