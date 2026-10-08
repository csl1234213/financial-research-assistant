import pytest

from agent.execution import StrategyRegistry


@pytest.fixture(autouse=True)
def _ensure_strategies_registered():
    from agent.execution.strategies import (
        DirectLLMStrategy,
        MultiStepStrategy,
        ParallelStrategy,
        RagStrategy,
        ToolCallingStrategy,
    )
    StrategyRegistry.register("rag", RagStrategy)
    StrategyRegistry.register("direct_llm", DirectLLMStrategy)
    StrategyRegistry.register("parallel", ParallelStrategy)
    StrategyRegistry.register("multi_step", MultiStepStrategy)
    StrategyRegistry.register("tool_calling", ToolCallingStrategy)
