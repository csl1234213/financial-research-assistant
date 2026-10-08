# ============================================================
# Execution Context
# ============================================================
# Unified input for the Execution Strategy Layer.
# Aggregates all upstream information — task, complexity,
# routing, and optionally workflow — into a single context
# object that the Execution Engine consumes.
#
# ExecutionEngine 以后永远读取 context.workflow，
# 而不是 workflow_engine。
# ============================================================

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from agent.planning import ComplexityResult, TaskResult
from llm.router import RoutingContext

if TYPE_CHECKING:
    from agent.execution_plan import ExecutionPlan
    from agent.tools.tool_context import ToolContext
    from agent.workflow.workflow_result import WorkflowResult


@dataclass(slots=True)
class ExecutionContext:
    task: TaskResult

    complexity: ComplexityResult

    routing: RoutingContext

    # The planner output is optional for compatibility with callers that use
    # the strategy engine in isolation.  The production Agent runtime passes
    # it so tool selection can require an explicit, typed TOOL_CALL node.
    plan: Optional["ExecutionPlan"] = field(default=None)

    workflow: Optional["WorkflowResult"] = field(default=None)

    tool_context: Optional["ToolContext"] = field(default=None)
