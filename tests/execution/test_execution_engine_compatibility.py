"""Compatibility contract for the two explicitly named execution layers."""

from agent.execution import (
    ExecutionEngine as PackageExecutionEngine,
)
from agent.execution import (
    StepExecutionEngine,
    StrategyExecutionEngine,
)
from agent.execution.execution_engine import ExecutionEngine as LegacyStrategyEngine
from agent.execution_engine import ExecutionEngine as LegacyStepEngine


def test_legacy_step_engine_import_is_exact_alias() -> None:
    assert LegacyStepEngine is StepExecutionEngine


def test_legacy_strategy_engine_import_is_exact_alias() -> None:
    assert LegacyStrategyEngine is StrategyExecutionEngine
    assert PackageExecutionEngine is StrategyExecutionEngine


def test_step_and_strategy_engines_have_distinct_responsibilities() -> None:
    assert StepExecutionEngine is not StrategyExecutionEngine
