# ============================================================
# WorkflowExecutor — Workflow Step Execution Engine
# ============================================================
# WorkflowExecutor 是 Workflow Layer 的执行器。
# 它负责将 WorkflowResult 中的 WorkflowStep[] 逐个驱动
# ExecutionEngine，追踪进度，并更新 WorkflowResult 状态。
#
# 职责：
#   ① 接收 WorkflowResult + ExecutionRunner + ExecutionContext
#   ② 循环 WorkflowStep[]
#   ③ 对每个 Step 调用 runner.execute(context)
#   ④ 更新 completed_steps / current_step / status
#
# 不负责：
#   - 业务判断（Workflow 负责）
#   - 策略选择（ExecutionEngine 负责）
#   - Provider / Tool / Memory / DAG
#
# ExecutionRunner 是 Protocol，WorkflowExecutor 不依赖
# 具体的 ExecutionEngine 实现，只依赖 execute(context) 能力。
# ============================================================

from typing import Protocol, runtime_checkable

from agent.execution.execution_context import ExecutionContext
from agent.execution.execution_result import ExecutionResult

from .workflow_enums import WorkflowStatus
from .workflow_result import WorkflowResult

# ============================================================
# ExecutionRunner Protocol
# ============================================================


@runtime_checkable
class ExecutionRunner(Protocol):
    def execute(self, context: ExecutionContext) -> ExecutionResult: ...


# ============================================================
# WorkflowExecutor
# ============================================================


class WorkflowExecutor:
    def execute(
        self,
        workflow: WorkflowResult,
        runner: ExecutionRunner,
        context: ExecutionContext,
    ) -> WorkflowResult:
        workflow.status = WorkflowStatus.RUNNING

        try:
            for step in workflow.steps:
                workflow.current_step = step
                runner.execute(context)
                workflow.completed_steps.append(step)
        except Exception:
            workflow.status = WorkflowStatus.FAILED
            raise

        workflow.current_step = None
        workflow.status = WorkflowStatus.DONE
        return workflow
