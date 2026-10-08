# ============================================================
# Workflow Result
# ============================================================
# Unified output of the Workflow Layer.
# 描述一个完整 Workflow 的结构 — 类型、步骤列表、
# 预估耗时、所需能力、置信度。
#
# 不包含 Provider（模型选择是 Routing 的职责）。
# 不包含 ExecutionResult（Workflow 不依赖 Execution）。
# 包含 Execution Intent（执行意图），供 ExecutionEngine 消费。
#
# After Tool Invocation:
#   ToolResults are collected during execution and stored here
#   for UI inspection and downstream memory.
# ============================================================

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from agent.tools.tool_result import ToolResult
from agent.execution.strategy_enums import ExecutionStrategyType

from .workflow_enums import WorkflowStatus, WorkflowType
from .workflow_models import WorkflowStep


@dataclass
class WorkflowResult:
    workflow: WorkflowType

    steps: List[WorkflowStep] = field(default_factory=list)

    estimated_time_ms: int = 0

    requires_tools: bool = False

    requires_memory: bool = False

    requires_human: bool = False

    confidence: float = 1.0

    reason: str = ""

    next_workflow: Optional[WorkflowType] = None

    tool_results: List["ToolResult"] = field(default_factory=list)

    # ============================================================
    # Execution Intent — consumed by ExecutionEngine via Bridge
    # ============================================================

    execution_strategy: ExecutionStrategyType = ExecutionStrategyType.DIRECT_LLM

    requires_retrieval: bool = False

    requires_parallel: bool = False

    estimated_execution_steps: int = 1

    # ============================================================
    # Runtime State — mutated by WorkflowExecutor during execution
    # ============================================================

    status: WorkflowStatus = WorkflowStatus.PENDING

    current_step: Optional[WorkflowStep] = None

    completed_steps: List[WorkflowStep] = field(default_factory=list)
