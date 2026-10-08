# ============================================================
# ExecutionEngine — Execution Layer Orchestrator
# ============================================================
# The ExecutionEngine is the single entry point for the
# Execution Strategy Layer. It receives an ExecutionContext,
# selects the best matching strategy, and returns an
# ExecutionResult.
#
# When context.workflow is available (set by WorkflowBridge),
# the Engine uses the workflow's execution_strategy directly,
# bypassing the supports() loop.
#
# The Engine does NOT make business decisions.
# It does NOT know about:
#   - Which strategy to use (workflow intent or strategy decides)
#   - Task types or complexity levels
#   - Provider selection
#   - RAG vs Direct vs Parallel
#
# It ONLY orchestrates:
#   Context → Strategy Selection → Build → Result
#
# Mirrors llm.router.ModelRouter in role:
#   ExecutionEngine ↔ ModelRouter
# ============================================================

from typing import Optional

from .execution_context import ExecutionContext
from .execution_result import ExecutionResult
from .execution_strategy import BaseExecutionStrategy
from .strategy_registry import StrategyRegistry


class ExecutionEngine:
    """
    Strategy Execution Engine

    Responsible for selecting execution strategy:
    - RAG
    - Direct LLM
    - Parallel execution
    - Multi-step workflow
    - Tool calling

    Different from:
    agent.execution.step_execution_engine.StepExecutionEngine
    which dispatches individual steps to registered handlers.

    This engine delegates actual step execution to the Step Execution Engine.
    """

    def __init__(self) -> None:
        from .strategies import register_builtin_strategies

        register_builtin_strategies()
        self._fallback_strategy_name: Optional[str] = None

    # ============================================================
    # Fallback configuration
    # ============================================================

    def set_fallback(self, strategy_name: str) -> None:
        if not StrategyRegistry.has_strategy(strategy_name):
            raise KeyError(
                f"Fallback strategy '{strategy_name}' not registered. Available: {StrategyRegistry.list_strategies()}"
            )
        self._fallback_strategy_name = strategy_name

    # ============================================================
    # Execute
    # ============================================================

    def execute(
        self,
        context: ExecutionContext,
    ) -> ExecutionResult:
        if context.tool_context is not None:
            return self._execute_from_tool(context)

        if context.workflow is not None:
            return self._execute_from_workflow(context)

        strategies = self._get_sorted_strategies()

        for strategy in strategies:
            if strategy.supports(context):
                return strategy.build(context)

        return self._fallback_execute(context)

    # ============================================================
    # Internal helpers
    # ============================================================

    def _execute_from_workflow(self, context: ExecutionContext) -> ExecutionResult:
        strategy_name = context.workflow.execution_strategy.value
        if StrategyRegistry.has_strategy(strategy_name):
            strategy_class = StrategyRegistry.get(strategy_name)
            strategy = strategy_class()
            result = strategy.build(context)
            result = self._execute_workflow_tools(context, result)
            return result
        return self._fallback_execute(context)

    def _execute_workflow_tools(
        self,
        context: ExecutionContext,
        result: ExecutionResult,
    ) -> ExecutionResult:
        from agent.tools.tool_bridge import ToolBridge
        from agent.tools.tool_engine import ToolEngine
        from agent.tools.tool_exceptions import ToolNotFound, ToolNotSupported

        workflow = context.workflow
        if workflow is None:
            return result

        tool_engine = ToolEngine()

        for step in workflow.steps:
            if not ToolBridge.has_tool(step):
                continue

            tool_name = ToolBridge.get_tool_name(step)
            if tool_name is None:
                continue

            tool_context = ToolBridge.to_tool_context(
                step,
                runtime_state=(context.tool_context.runtime_state if context.tool_context is not None else None),
                workflow=workflow,
                execution=result,
            )

            try:
                tool_result = tool_engine.execute(tool_context, tool_name)
                result.tool_results.append(tool_result)
            except (ToolNotFound, ToolNotSupported):
                continue
            except Exception:
                continue

        return result

    def _execute_from_tool(self, context: ExecutionContext) -> ExecutionResult:
        result = self._execute_tool(context)
        return ExecutionResult(
            strategy=result.metadata.get("execution_strategy", "tool_calling"),
            reason=f"Tool execution: {result.status.value}",
            estimated_steps=1,
            parallelism=1,
            use_retrieval=False,
            use_tools=True,
            confidence=0.95,
            tool_results=[result],
        )

    def _execute_tool(self, context: ExecutionContext):
        from agent.tools.tool_engine import ToolEngine
        from agent.tools.tool_enums import ToolType

        tool_engine = ToolEngine()
        tool = context.tool_context.parameters.get("tool", ToolType.CUSTOM)
        return tool_engine.execute(context.tool_context, tool)

    def _get_sorted_strategies(self) -> list[BaseExecutionStrategy]:
        strategies = StrategyRegistry.list_instances()
        strategies.sort(key=lambda s: s.priority, reverse=True)
        return strategies

    def _fallback_execute(self, context: ExecutionContext) -> ExecutionResult:
        if self._fallback_strategy_name is not None:
            strategy_class = StrategyRegistry.get(self._fallback_strategy_name)
            strategy = strategy_class()
            return strategy.build(context)

        from .strategy_enums import ExecutionStrategyType

        return ExecutionResult(
            strategy=ExecutionStrategyType.DIRECT_LLM,
            reason="No strategy matched; using direct LLM fallback",
            estimated_steps=1,
            parallelism=1,
            use_retrieval=False,
            use_tools=False,
            confidence=0.5,
        )


# Backward-compatible name for callers that imported this module before the
# strategy and step engines were given explicit architectural names.
StrategyExecutionEngine = ExecutionEngine

__all__ = ["ExecutionEngine", "StrategyExecutionEngine"]
