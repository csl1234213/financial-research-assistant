# ============================================================
# Execution Handlers — Concrete execution handler implementations
# ============================================================
# Each handler implements BaseExecutionHandler and is
# automatically registered in ExecutionHandlerRegistry.
# The Dispatcher uses the Registry to resolve handlers.
# ============================================================

from agent.execution.execution_handler_registry import ExecutionHandlerRegistry
from agent.execution.strategy_enums import ExecutionStrategyType

from .direct_llm_handler import DirectLLMHandler
from .multi_step_handler import MultiStepHandler
from .parallel_handler import ParallelHandler
from .rag_handler import RagHandler
from .tool_calling_handler import ToolCallingHandler

# Auto-registration
ExecutionHandlerRegistry.register(ExecutionStrategyType.RAG, RagHandler)
ExecutionHandlerRegistry.register(ExecutionStrategyType.DIRECT_LLM, DirectLLMHandler)
ExecutionHandlerRegistry.register(ExecutionStrategyType.PARALLEL, ParallelHandler)
ExecutionHandlerRegistry.register(ExecutionStrategyType.MULTI_STEP, MultiStepHandler)
ExecutionHandlerRegistry.register(ExecutionStrategyType.TOOL_CALLING, ToolCallingHandler)

__all__ = [
    "RagHandler",
    "DirectLLMHandler",
    "ParallelHandler",
    "MultiStepHandler",
    "ToolCallingHandler",
]
