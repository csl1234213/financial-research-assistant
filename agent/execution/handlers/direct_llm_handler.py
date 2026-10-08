# ============================================================
# DirectLLMHandler — Execute direct LLM call (no retrieval)
# ============================================================
# Used when ExecutionResult.strategy == ExecutionStrategyType.DIRECT_LLM
# Skips retrieval entirely — returns empty context and citations.
# The LLM call itself is handled by the caller (core_engine).
# ============================================================

from agent.execution.execution_handler import (
    BaseExecutionHandler,
    ExecutionHandlerContext,
    ExecutionOutput,
)
from agent.execution.strategy_enums import ExecutionStrategyType


class DirectLLMHandler(BaseExecutionHandler):
    @property
    def strategy_type(self) -> ExecutionStrategyType:
        return ExecutionStrategyType.DIRECT_LLM

    def execute(
        self,
        ctx: ExecutionHandlerContext,
    ) -> ExecutionOutput:
        return ExecutionOutput(
            context="",
            citations=[],
            evidences=[],
            execution_results=[],
        )
