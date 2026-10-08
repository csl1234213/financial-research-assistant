from typing import Any, Callable, Dict, Optional

from agent.execution_plan import ExecutionPlan, PlanStep, StepStatus, StepType
from agent.execution_result import ExecutionResult

Handler = Callable[[PlanStep, Dict[str, Any]], Any]


class ExecutionEngine:
    """
    Step Execution Engine

    Responsible for executing individual workflow steps
    through registered handlers.

    Different from:
    agent.execution.execution_engine.StrategyExecutionEngine
    which decides execution strategy (RAG / DirectLLM / Parallel / MultiStep).

    This engine delegates actual step execution to handlers.
    """

    def __init__(self):
        self._handlers: Dict[StepType, Handler] = {}

    # =========================
    # Handler Registration
    # =========================

    def register_handler(self, step_type: StepType, handler: Handler):
        self._handlers[step_type] = handler

    # =========================
    # Main Entry
    # =========================

    def execute(
        self,
        plan: ExecutionPlan,
        shared_context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """
        Execute all tasks in the plan.

        Returns the same plan with status and result populated on each step.
        """
        if shared_context is None:
            shared_context = {}

        completed: Dict[int, Any] = {}

        for step in plan.tasks:
            self.execute_step(step, shared_context, completed)

        return plan

    def execute_step(
        self,
        step: PlanStep,
        shared_context: Optional[Dict[str, Any]] = None,
        completed: Optional[Dict[int, Any]] = None,
    ) -> ExecutionResult:
        """Execute one plan step against an explicit dependency snapshot.

        Advanced execution handlers use this method to schedule independent
        retrieval steps concurrently without sharing mutable evidence lists.
        A production engine is fully configured before it serves requests;
        handlers must not be registered while steps are executing.
        """
        if shared_context is None:
            shared_context = {}
        if completed is None:
            completed = {}

        self._execute_step(step, shared_context, completed)
        return step.result

    # =========================
    # Step Execution
    # =========================

    def _execute_step(
        self,
        step: PlanStep,
        shared_context: Dict[str, Any],
        completed: Dict[int, Any],
    ):
        shared_context["_step_results"] = dict(completed)

        if not self._dependencies_met(step, completed):
            step.status = StepStatus.SKIPPED
            step.result = ExecutionResult(
                step_id=step.step_id,
                success=False,
                error="Dependencies not met",
            )
            return

        step.status = StepStatus.RUNNING

        handler = self._handlers.get(step.step_type)

        if handler is None:
            step.status = StepStatus.FAILED
            step.result = ExecutionResult(
                step_id=step.step_id,
                success=False,
                error=f"No handler registered for {step.step_type.value}",
            )
            return

        try:
            output = handler(step, shared_context)
            step.status = StepStatus.COMPLETED
            step.result = ExecutionResult(
                step_id=step.step_id,
                success=True,
                output=output,
            )
            completed[step.step_id] = output
            shared_context["_step_results"] = dict(completed)
        except Exception as e:
            step.status = StepStatus.FAILED
            step.result = ExecutionResult(
                step_id=step.step_id,
                success=False,
                error=str(e),
            )

    # =========================
    # Dependency Resolution
    # =========================

    def _dependencies_met(
        self,
        step: PlanStep,
        completed: Dict[int, Any],
    ) -> bool:
        if not step.depends_on:
            return True

        for dep_id in step.depends_on:
            if dep_id not in completed:
                return False

        return True


# Explicit architectural name for new callers.  Keeping the implementation
# class at its historical location preserves import, introspection, and
# serialization compatibility.
StepExecutionEngine = ExecutionEngine

__all__ = ["ExecutionEngine", "StepExecutionEngine"]
