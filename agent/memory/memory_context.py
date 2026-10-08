# ============================================================
# Memory Context
# ============================================================
# Unified input for the Memory Layer.
# Aggregates all upstream information — task, workflow,
# execution, and runtime_state — into a single context object.
#
# Memory Engine 永远只接收一个 Context。
#
# MemoryContext 通过 MemoryBridge 从 RuntimeState 构建，
# 不直接依赖 Runtime 的具体实现细节。
# ============================================================

from dataclasses import dataclass, field
from typing import List, Optional

from agent.execution.execution_result import ExecutionResult
from agent.planning import TaskResult
from agent.runtime_state import RuntimeState
from agent.workflow.workflow_result import WorkflowResult


@dataclass(slots=True)
class MemoryContext:
    task: Optional[TaskResult] = None

    runtime_state: RuntimeState = field(default_factory=RuntimeState)

    workflow: Optional[WorkflowResult] = None

    execution: List[ExecutionResult] = field(default_factory=list)
