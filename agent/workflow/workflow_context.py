# ============================================================
# Workflow Context
# ============================================================
# Unified input for the Workflow Layer.
# Aggregates all upstream information — task, complexity,
# execution, and routing — into a single context object.
#
# Workflow Engine 永远只接收一个 Context。
# ============================================================

from dataclasses import dataclass

from agent.execution import ExecutionResult
from agent.planning import ComplexityResult, TaskResult
from llm.router import RoutingContext


@dataclass(slots=True)
class WorkflowContext:
    task: TaskResult

    complexity: ComplexityResult

    execution: ExecutionResult

    routing: RoutingContext
