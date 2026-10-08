# ============================================================
# WorkflowBridge — Thin bridge from Workflow to Execution
# ============================================================
# WorkflowEngine 不直接调用 ExecutionEngine。
# ExecutionEngine 不 import Workflow。
#
# 通过 WorkflowBridge 完成：
#   WorkflowResult → ExecutionContext
#
# 这样：
#   - Workflow Layer 不依赖 Execution Layer 的实现细节
#   - ExecutionContext 成为 Runtime 的统一输入
#   - 后续 Memory / Tool Calling / Multi-Agent 都可以通过
#     Bridge 增加信息，而不修改 Engine 之间的依赖关系
# ============================================================

from agent.execution.execution_context import ExecutionContext

from .workflow_context import WorkflowContext
from .workflow_result import WorkflowResult


class WorkflowBridge:
    @staticmethod
    def to_execution_context(
        context: WorkflowContext,
        workflow_result: WorkflowResult,
    ) -> ExecutionContext:
        return ExecutionContext(
            task=context.task,
            complexity=context.complexity,
            routing=context.routing,
            workflow=workflow_result,
        )
