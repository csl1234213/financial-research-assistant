# ============================================================
# Metric Context
# ============================================================
# Unified input for the Metrics Layer.
# 聚合所有上游信息 — runtime_state, workflow, execution,
# tool, provider, memory — 到一个 Context 对象中。
#
# Metric 永远只接收一个 MetricContext。
# 不依赖 Runtime 具体实现细节。
#
# Mirrors:
#   MetricContext ↔ TraceContext ↔ ToolContext ↔ MemoryContext
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
class MetricContext:
    runtime_state: Optional["RuntimeState"] = None

    workflow: Optional["WorkflowResult"] = None

    execution: List["ExecutionResult"] = field(default_factory=list)

    tool: Optional["ToolResult"] = None

    provider: Optional[Dict[str, Any]] = None

    memory: Optional["MemoryResult"] = None

    metadata: Dict[str, Any] = field(default_factory=dict)
