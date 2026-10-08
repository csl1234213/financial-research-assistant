# ============================================================
# Strategy Factory Tests
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.execution import (
    BaseExecutionStrategy,
    ExecutionContext,
    ExecutionResult,
    ExecutionStrategyType,
    StrategyFactory,
    StrategyRegistry,
)


class _MockStrategy(BaseExecutionStrategy):
    @property
    def strategy_name(self) -> str:
        return "mock"

    def supports(self, context: ExecutionContext) -> bool:
        return True

    def build(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            strategy=ExecutionStrategyType.DIRECT_LLM,
            reason="mock",
        )


class TestStrategyFactory:

    def setup_method(self):
        StrategyRegistry.clear()
        StrategyRegistry.register("mock", _MockStrategy)
        StrategyFactory._default_strategy = None

    def teardown_method(self):
        StrategyRegistry.clear()
        StrategyFactory._default_strategy = None

    # =========================
    # Create
    # =========================

    def test_create_returns_strategy_instance(self):
        strategy = StrategyFactory.create("mock")
        assert isinstance(strategy, BaseExecutionStrategy)
        assert strategy.strategy_name == "mock"

    def test_create_raises_for_unregistered(self):
        with pytest.raises(KeyError, match="not registered"):
            StrategyFactory.create("nonexistent")

    # =========================
    # Default strategy
    # =========================

    def test_set_and_get_default(self):
        StrategyFactory.set_default("mock")
        assert StrategyFactory.get_default() == "mock"

    def test_set_default_raises_for_unregistered(self):
        with pytest.raises(KeyError, match="not registered"):
            StrategyFactory.set_default("nonexistent")

    def test_create_default_returns_instance(self):
        StrategyFactory.set_default("mock")
        strategy = StrategyFactory.create_default()
        assert isinstance(strategy, BaseExecutionStrategy)
        assert strategy.strategy_name == "mock"

    def test_create_default_raises_when_no_default(self):
        with pytest.raises(KeyError, match="No default strategy set"):
            StrategyFactory.create_default()

    # =========================
    # Discovery
    # =========================

    def test_list_strategies(self):
        names = StrategyFactory.list_strategies()
        assert "mock" in names
        assert len(names) == 1
