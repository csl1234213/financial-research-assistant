# ============================================================
# BaseExecutionHandler — Abstract interface for all execution handlers
# ============================================================
# Every concrete execution handler (RAG, DirectLLM, Parallel,
# MultiStep, ToolCalling, etc.) must implement this interface.
#
# The handler receives an ExecutionHandlerContext containing
# all runtime dependencies and produces an ExecutionOutput
# with the execution results (context, citations, evidence).
#
# Mirrors:
#   BaseExecutionHandler ↔ BaseExecutionStrategy
#   BaseExecutionHandler ↔ BaseProvider
# ============================================================

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from agent.execution.step_execution_engine import StepExecutionEngine
from agent.execution.strategy_enums import ExecutionStrategyType
from agent.execution_plan import ExecutionPlan
from agent.execution_result import ExecutionResult
from agent.reasoning_models import Evidence


@dataclass
class ExecutionHandlerContext:
    plan: ExecutionPlan

    executor: StepExecutionEngine

    # Bounded strategy-level fan-out. Only the parallel handler consumes this
    # value, and only for independent retrieval steps.
    parallelism: int = 1

    # Request-scoped values (tenant, thread, trace, etc.) are passed through
    # this object instead of module globals so concurrent requests cannot
    # leak retrieval state into one another.
    shared_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionOutput:
    context: str = ""

    citations: List[Dict[str, Any]] = field(default_factory=list)

    evidences: List[Evidence] = field(default_factory=list)

    execution_results: List[ExecutionResult] = field(default_factory=list)

    # Structured, request-scoped trace of actual governed tool executions.
    # This is distinct from retrieval evidence and is safe to expose through
    # the runtime execution metadata.
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


class BaseExecutionHandler(ABC):
    @property
    @abstractmethod
    def strategy_type(self) -> ExecutionStrategyType: ...

    @abstractmethod
    def execute(
        self,
        ctx: ExecutionHandlerContext,
    ) -> ExecutionOutput: ...
