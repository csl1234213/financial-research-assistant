# ============================================================
# Strategy Implementations — Skeleton modules
# ============================================================
# All concrete execution strategies live here.
# Each strategy implements the BaseExecutionStrategy interface
# and is automatically registered in StrategyRegistry.
# ============================================================

from ..strategy_registry import StrategyRegistry
from .direct_llm_strategy import DirectLLMStrategy
from .multi_step_strategy import MultiStepStrategy
from .parallel_strategy import ParallelStrategy
from .rag_strategy import RagStrategy
from .tool_calling_strategy import ToolCallingStrategy

_BUILTIN_STRATEGIES = {
    "rag": RagStrategy,
    "direct_llm": DirectLLMStrategy,
    "parallel": ParallelStrategy,
    "multi_step": MultiStepStrategy,
    "tool_calling": ToolCallingStrategy,
}


def register_builtin_strategies() -> None:
    """Idempotently register the execution strategies shipped with the app."""

    for name, strategy_class in _BUILTIN_STRATEGIES.items():
        if not StrategyRegistry.has_strategy(name):
            StrategyRegistry.register(name, strategy_class)


# Preserve import-time registration for existing callers while also exposing
# an explicit bootstrap for engines created after a registry reset.
register_builtin_strategies()

__all__ = [
    "RagStrategy",
    "DirectLLMStrategy",
    "ParallelStrategy",
    "MultiStepStrategy",
    "ToolCallingStrategy",
    "register_builtin_strategies",
]
