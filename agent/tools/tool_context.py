# ============================================================
# Tool Context
# ============================================================
# Unified input for the Tool Layer.
# Aggregates all upstream information — runtime_state,
# workflow, execution, memory — into a single context object.
#
# ToolEngine 永远只接收一个 Context。
#
# 保持与 MemoryContext / WorkflowContext 统一的
# 单一 Context 入口风格。
# ============================================================

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from agent.execution.execution_result import ExecutionResult as StrategyResult
    from agent.memory.memory_result import MemoryResult
    from agent.runtime_state import RuntimeState
    from agent.workflow.workflow_result import WorkflowResult


@dataclass(slots=True)
class ToolContext:
    runtime_state: Optional["RuntimeState"] = None
    workflow: Optional["WorkflowResult"] = None
    execution: Optional["StrategyResult"] = None
    memory: Optional["MemoryResult"] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    # The application composition layer sets this value from authenticated
    # request scope.  Tools must not derive tenant scope from user-controlled
    # ``parameters``.
    tenant_id: Optional[int] = None
