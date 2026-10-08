"""Bounded parallel retrieval execution handler."""

from agent.execution.execution_handler import (
    BaseExecutionHandler,
    ExecutionHandlerContext,
    ExecutionOutput,
)
from agent.execution.plan_execution import PlanExecutionCoordinator
from agent.execution.strategy_enums import ExecutionStrategyType


class ParallelHandler(BaseExecutionHandler):
    @property
    def strategy_type(self) -> ExecutionStrategyType:
        return ExecutionStrategyType.PARALLEL

    def execute(
        self,
        ctx: ExecutionHandlerContext,
    ) -> ExecutionOutput:
        return PlanExecutionCoordinator(ctx).execute_parallel_retrievals()
