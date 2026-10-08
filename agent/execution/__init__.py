# ============================================================
# Execution Module — Execution Strategy Layer
# ============================================================
# Unified data models for execution strategy selection.
# The Execution Strategy Layer sits between Complexity
# and Routing, determining HOW a task should be executed
# before it reaches the Execution Engine.
#
# Architecture mirrors llm.providers / llm.factory:
#   BaseExecutionStrategy ↔ BaseProvider
#   StrategyRegistry      ↔ ProviderRegistry
#   StrategyFactory       ↔ ProviderFactory
# ============================================================

from .execution_context import ExecutionContext
from .execution_dispatcher import ExecutionDispatcher
from .execution_engine import ExecutionEngine, StrategyExecutionEngine
from .execution_handler import (
    BaseExecutionHandler,
    ExecutionHandlerContext,
    ExecutionOutput,
)
from .execution_handler_registry import ExecutionHandlerRegistry
from .execution_result import ExecutionResult
from .execution_strategy import BaseExecutionStrategy
from .step_execution_engine import StepExecutionEngine
from .strategy_enums import ExecutionStrategyType
from .strategy_factory import StrategyFactory
from .strategy_registry import StrategyRegistry

__all__ = [
    "ExecutionStrategyType",
    "ExecutionContext",
    "ExecutionResult",
    "BaseExecutionStrategy",
    "StrategyRegistry",
    "StrategyFactory",
    "ExecutionEngine",
    "StrategyExecutionEngine",
    "StepExecutionEngine",
    "BaseExecutionHandler",
    "ExecutionHandlerContext",
    "ExecutionOutput",
    "ExecutionHandlerRegistry",
    "ExecutionDispatcher",
]
