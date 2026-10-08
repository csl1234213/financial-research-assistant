# ============================================================
# Strategy Registry Tests
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


from agent.execution import (
    BaseExecutionStrategy,
    ExecutionContext,
    ExecutionResult,
    ExecutionStrategyType,
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


class _MockStrategy2(BaseExecutionStrategy):
    @property
    def strategy_name(self) -> str:
        return "mock2"

    def supports(self, context: ExecutionContext) -> bool:
        return True

    def build(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            strategy=ExecutionStrategyType.RAG,
            reason="mock2",
        )


class TestStrategyRegistry:

    def setup_method(self):
        StrategyRegistry.clear()

    def teardown_method(self):
        StrategyRegistry.clear()

    # =========================
    # Registration
    # =========================

    def test_register_single_strategy(self):
        StrategyRegistry.register("mock", _MockStrategy)
        assert StrategyRegistry.has_strategy("mock") is True
        assert StrategyRegistry.get("mock") is _MockStrategy

    def test_register_multiple_strategies(self):
        StrategyRegistry.register("mock", _MockStrategy)
        StrategyRegistry.register("mock2", _MockStrategy2)
        assert StrategyRegistry.has_strategy("mock") is True
        assert StrategyRegistry.has_strategy("mock2") is True

    def test_has_strategy_returns_false_for_unregistered(self):
        assert StrategyRegistry.has_strategy("nonexistent") is False

    # =========================
    # List strategies
    # =========================

    def test_list_strategies_empty(self):
        assert StrategyRegistry.list_strategies() == []

    def test_list_strategies_returns_names(self):
        StrategyRegistry.register("mock", _MockStrategy)
        StrategyRegistry.register("mock2", _MockStrategy2)
        names = StrategyRegistry.list_strategies()
        assert "mock" in names
        assert "mock2" in names
        assert len(names) == 2

    # =========================
    # List instances
    # =========================

    def test_list_instances_empty(self):
        assert StrategyRegistry.list_instances() == []

    def test_list_instances_returns_strategy_objects(self):
        StrategyRegistry.register("mock", _MockStrategy)
        StrategyRegistry.register("mock2", _MockStrategy2)
        instances = StrategyRegistry.list_instances()
        assert len(instances) == 2
        assert all(isinstance(s, BaseExecutionStrategy) for s in instances)
        names = {s.strategy_name for s in instances}
        assert names == {"mock", "mock2"}

    # =========================
    # Clear
    # =========================

    def test_clear_removes_all(self):
        StrategyRegistry.register("mock", _MockStrategy)
        StrategyRegistry.clear()
        assert StrategyRegistry.list_strategies() == []
        assert StrategyRegistry.list_instances() == []

    # =========================
    # Auto-registration
    # =========================

    def test_auto_registration_on_import(self):
        import importlib

        import agent.execution.strategies
        from agent.execution import StrategyRegistry
        importlib.reload(agent.execution.strategies)
        names = StrategyRegistry.list_strategies()
        assert "rag" in names
        assert "direct_llm" in names
        assert "parallel" in names
        assert "multi_step" in names
        assert "tool_calling" in names
        assert len(names) == 5
