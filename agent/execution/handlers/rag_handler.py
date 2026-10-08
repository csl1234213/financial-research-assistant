# ============================================================
# RAGHandler — Execute the RAG pipeline (retrieval + context building)
# ============================================================
# Used when ExecutionResult.strategy == ExecutionStrategyType.RAG
# Executes the plan via the V3 ExecutionEngine, collects evidence,
# and builds context and citations from the retrieved evidence.
# ============================================================

from agent.execution.execution_handler import (
    BaseExecutionHandler,
    ExecutionHandlerContext,
    ExecutionOutput,
)
from agent.execution.plan_execution import output_from_evidence
from agent.execution.strategy_enums import ExecutionStrategyType


class RagHandler(BaseExecutionHandler):
    @property
    def strategy_type(self) -> ExecutionStrategyType:
        return ExecutionStrategyType.RAG

    def execute(
        self,
        ctx: ExecutionHandlerContext,
    ) -> ExecutionOutput:
        # Keep the original whole-plan executor contract for simple RAG.
        # Advanced strategies use the step-level coordinator.
        shared = dict(ctx.shared_context)
        shared["_all_evidence"] = []
        ctx.executor.execute(ctx.plan, shared)
        return output_from_evidence(
            ctx.plan.tasks,
            shared["_all_evidence"],
        )
