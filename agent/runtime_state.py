# ============================================================
# RuntimeState — Unified Runtime State
# ============================================================
# 统一运行时状态，贯穿整个 Agent 执行生命周期。
#
# WorkflowExecutor 每完成一步，Runtime 就更新一次 RuntimeState。
# 后续 Memory / Retry / Human Review / Multi-Agent 都基于
# 同一个 RuntimeState 构建，不需要重新设计 Runtime 数据结构。
# ============================================================

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from agent.execution.execution_result import ExecutionResult
    from agent.tools.tool_result import ToolResult
    from agent.workflow.workflow_result import WorkflowResult


@dataclass
class RuntimeState:
    workflow: Optional["WorkflowResult"] = None

    execution: List["ExecutionResult"] = field(default_factory=list)

    routing: List[Any] = field(default_factory=list)

    outputs: List[Any] = field(default_factory=list)

    tool_results: List["ToolResult"] = field(default_factory=list)

    retry_count: int = 0

    timeout_count: int = 0

    circuit_state: Optional[str] = None

    failure_count: int = 0

    health_status: Optional[str] = None

    rate_limit_remaining: int = 0

    fallback_used: bool = False
