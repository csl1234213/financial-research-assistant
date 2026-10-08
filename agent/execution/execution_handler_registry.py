# ============================================================
# Execution Handler Registry — Central registration for all execution handlers
# ============================================================
# Why registry instead of hardcoding in Dispatcher?
#
# 1. Open/Closed Principle: Add new handlers without modifying Dispatcher
# 2. Plugin architecture: Handlers can be registered dynamically
# 3. Separation of concerns: Registry knows who, Dispatcher knows how to dispatch
#
# Mirrors:
#   ExecutionHandlerRegistry ↔ StrategyRegistry
#   ExecutionHandlerRegistry ↔ ProviderRegistry
# ============================================================

from typing import Dict, List, Type

from agent.execution.strategy_enums import ExecutionStrategyType

from .execution_handler import BaseExecutionHandler


class ExecutionHandlerRegistry:
    _registry: Dict[ExecutionStrategyType, Type[BaseExecutionHandler]] = {}

    @classmethod
    def register(
        cls,
        strategy_type: ExecutionStrategyType,
        handler_class: Type[BaseExecutionHandler],
    ) -> None:
        cls._registry[strategy_type] = handler_class

    @classmethod
    def get(cls, strategy_type: ExecutionStrategyType) -> Type[BaseExecutionHandler]:
        return cls._registry[strategy_type]

    @classmethod
    def list_handlers(cls) -> List[ExecutionStrategyType]:
        return list(cls._registry.keys())

    @classmethod
    def has_handler(cls, strategy_type: ExecutionStrategyType) -> bool:
        return strategy_type in cls._registry

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
