# ============================================================
# Strategy Factory — Creates strategy instances by name
# ============================================================
# The Factory only knows how to create, not which strategies exist.
# That knowledge lives in the Registry.
#
# Usage:
#   strategy = StrategyFactory.create("rag")
#   result = strategy.build(context)
#
# Mirrors llm.factory.ProviderFactory in structure:
#   StrategyFactory ↔ ProviderFactory
# ============================================================

from typing import Optional

from .execution_strategy import BaseExecutionStrategy
from .strategy_registry import StrategyRegistry


class StrategyFactory:
    _default_strategy: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, name: str) -> BaseExecutionStrategy:
        if not StrategyRegistry.has_strategy(name):
            raise KeyError(f"Strategy '{name}' not registered. Available: {StrategyRegistry.list_strategies()}")
        strategy_class = StrategyRegistry.get(name)
        return strategy_class()

    # ============================================================
    # Default strategy
    # ============================================================

    @classmethod
    def set_default(cls, name: str) -> None:
        if not StrategyRegistry.has_strategy(name):
            raise KeyError(f"Cannot set default. Strategy '{name}' not registered.")
        cls._default_strategy = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_strategy

    @classmethod
    def create_default(cls) -> BaseExecutionStrategy:
        if cls._default_strategy is None:
            raise KeyError("No default strategy set. Call StrategyFactory.set_default(name) first.")
        return cls.create(cls._default_strategy)

    # ============================================================
    # Discovery
    # ============================================================

    @classmethod
    def list_strategies(cls) -> list[str]:
        return StrategyRegistry.list_strategies()
