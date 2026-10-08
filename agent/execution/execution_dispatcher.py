# ============================================================
# ExecutionDispatcher — Dispatches ExecutionResult to the correct handler
# ============================================================
# The ExecutionDispatcher is the single entry point for runtime
# execution dispatch. It receives an ExecutionResult (strategy)
# and an ExecutionHandlerContext (dependencies), looks up the
# correct handler from ExecutionHandlerRegistry, and returns
# an ExecutionOutput.
#
# The Dispatcher does NOT use if/elif on strategy type.
# It delegates entirely to the Registry + Handler pattern.
#
# Mirrors:
#   ExecutionDispatcher ↔ ExecutionEngine
#   ExecutionDispatcher ↔ ModelRouter
# ============================================================

import logging
from typing import Optional

from agent.execution.strategy_enums import ExecutionStrategyType

from .execution_handler import (
    BaseExecutionHandler,
    ExecutionHandlerContext,
    ExecutionOutput,
)
from .execution_handler_registry import ExecutionHandlerRegistry
from .execution_result import ExecutionResult

logger = logging.getLogger(__name__)


class ExecutionDispatcher:
    def __init__(self) -> None:
        self._fallback_strategy_type: Optional[ExecutionStrategyType] = None

    # ============================================================
    # Fallback configuration
    # ============================================================

    def set_fallback(self, strategy_type: ExecutionStrategyType) -> None:
        if not ExecutionHandlerRegistry.has_handler(strategy_type):
            raise KeyError(
                f"Fallback handler for '{strategy_type.value}' not registered. "
                f"Available: {[s.value for s in ExecutionHandlerRegistry.list_handlers()]}"
            )
        self._fallback_strategy_type = strategy_type

    # ============================================================
    # Dispatch
    # ============================================================

    def dispatch(
        self,
        strategy_result: ExecutionResult,
        handler_ctx: ExecutionHandlerContext,
    ) -> ExecutionOutput:
        strategy_type = strategy_result.strategy

        if ExecutionHandlerRegistry.has_handler(strategy_type):
            handler_class = ExecutionHandlerRegistry.get(strategy_type)
            handler: BaseExecutionHandler = handler_class()
            logger.info(
                "Execution Dispatch: %s → %s",
                strategy_type.value,
                handler.__class__.__name__,
            )
            return handler.execute(handler_ctx)

        return self._fallback_dispatch(strategy_result, handler_ctx)

    # ============================================================
    # Internal helpers
    # ============================================================

    def _fallback_dispatch(
        self,
        strategy_result: ExecutionResult,
        handler_ctx: ExecutionHandlerContext,
    ) -> ExecutionOutput:
        if self._fallback_strategy_type is not None:
            handler_class = ExecutionHandlerRegistry.get(self._fallback_strategy_type)
            handler: BaseExecutionHandler = handler_class()
            logger.warning(
                "No handler for '%s' — falling back to '%s'",
                strategy_result.strategy.value,
                self._fallback_strategy_type.value,
            )
            return handler.execute(handler_ctx)

        logger.warning(
            "No handler for '%s' and no fallback configured — returning empty output",
            strategy_result.strategy.value,
        )
        return ExecutionOutput()
