# ============================================================
# Trace Context
# ============================================================
# Unified input for the Tracing Layer.
# 聚合所有上游信息 — runtime_state, workflow, execution,
# memory, tool — 到一个 Context 对象中。
#
# Tracer 永远只接收一个 TraceContext。
# 不依赖 Runtime 具体实现细节。
# ============================================================

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from agent.execution.execution_result import ExecutionResult
    from agent.memory.memory_result import MemoryResult
    from agent.runtime_state import RuntimeState
    from agent.tools.tool_result import ToolResult
    from agent.workflow.workflow_result import WorkflowResult


@dataclass(slots=True)
class TraceContext:
    runtime_state: Optional["RuntimeState"] = None

    workflow: Optional["WorkflowResult"] = None

    execution: List["ExecutionResult"] = field(default_factory=list)

    memory: Optional["MemoryResult"] = None

    tool: Optional["ToolResult"] = None

    metadata: Dict[str, Any] = field(default_factory=dict)
