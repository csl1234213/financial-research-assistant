# ============================================================
# WorkflowEngine — Workflow Layer Orchestrator
# ============================================================
# The WorkflowEngine is the single entry point for the
# Workflow Layer. It receives a WorkflowContext, maps the
# Execution strategy to a WorkflowType, creates the
# workflow via Factory, and returns a WorkflowResult.
#
# The Engine does NOT make business decisions.
# It does NOT know about:
#   - Which workflow to use (declarative mapping, no if/else)
#   - Task types or complexity levels
#   - Provider / Runtime / Tool / Memory
#   - DAG scheduling or parallel execution
#
# It ONLY orchestrates:
#   Context → Strategy→Workflow Mapping → Factory → Build → Result
#
# Mirrors:
#   agent.execution.ExecutionEngine  → WorkflowEngine
#   llm.router.ModelRouter           → WorkflowEngine
# ============================================================

from typing import Dict

from agent.execution.strategy_enums import ExecutionStrategyType

from .workflow_context import WorkflowContext
from .workflow_enums import WorkflowType
from .workflow_factory import WorkflowFactory
from .workflow_result import WorkflowResult


class WorkflowEngine:
    _STRATEGY_TO_WORKFLOW: Dict[ExecutionStrategyType, WorkflowType] = {
        ExecutionStrategyType.DIRECT_LLM: WorkflowType.DIRECT_CHAT,
        ExecutionStrategyType.RAG: WorkflowType.RAG,
        ExecutionStrategyType.MULTI_STEP: WorkflowType.MULTI_STEP,
        ExecutionStrategyType.PARALLEL: WorkflowType.PARALLEL,
        ExecutionStrategyType.TOOL_CALLING: WorkflowType.TOOL_PIPELINE,
        ExecutionStrategyType.MULTI_DOCUMENT: WorkflowType.RAG,
        ExecutionStrategyType.HYBRID: WorkflowType.MULTI_STEP,
        ExecutionStrategyType.AGENT_WORKFLOW: WorkflowType.MULTI_STEP,
    }

    _DEFAULT_WORKFLOW: WorkflowType = WorkflowType.DIRECT_CHAT

    # ============================================================
    # Build
    # ============================================================

    def build(self, context: WorkflowContext) -> WorkflowResult:
        strategy = context.execution.strategy
        workflow_type = self._STRATEGY_TO_WORKFLOW.get(
            strategy,
            self._DEFAULT_WORKFLOW,
        )
        workflow = WorkflowFactory.create(workflow_type)
        return workflow.build(context)
