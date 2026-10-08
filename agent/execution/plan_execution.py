"""Dependency-aware execution support shared by strategy handlers.

The step engine owns handler dispatch. This coordinator owns scheduling and
deterministic evidence aggregation. Parallel execution is deliberately
limited to independent retrieval steps: arbitrary handlers do not implicitly
become thread-safe merely because a parallel strategy was selected.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from agent.execution.execution_handler import ExecutionHandlerContext, ExecutionOutput
from agent.execution_plan import PlanStep, StepType
from agent.execution_result import ExecutionResult
from agent.reasoning_models import Evidence
from core.context_builder import build_context_from_evidence

MAX_RETRIEVAL_WORKERS = 4


@dataclass(slots=True)
class _StepOutcome:
    result: ExecutionResult
    evidences: list[Evidence]


class PlanExecutionCoordinator:
    """Run an execution plan sequentially or with bounded retrieval fan-out."""

    def __init__(self, ctx: ExecutionHandlerContext) -> None:
        self._ctx = ctx

    def execute_sequential(self) -> ExecutionOutput:
        shared = self._base_context()
        completed: dict[int, Any] = {}

        for step in self._ctx.plan.tasks:
            outcome = self._execute_isolated_step(step, completed)
            if outcome.result.success:
                completed[step.step_id] = outcome.result.output
                shared["_all_evidence"].extend(outcome.evidences)
            shared["_step_results"] = dict(completed)

        return output_from_evidence(
            self._ctx.plan.tasks,
            shared["_all_evidence"],
        )

    def execute_parallel_retrievals(self) -> ExecutionOutput:
        """Execute independent retrieval DAG nodes concurrently.

        Every worker receives a private top-level context and evidence list.
        Results and evidence are merged in plan order after the whole batch
        finishes, so completion timing cannot change citations or reasoning.
        Non-retrieval steps always execute on the caller thread.
        """
        shared = self._base_context()
        completed: dict[int, Any] = {}
        pending = list(self._ctx.plan.tasks)
        max_workers = max(1, min(self._ctx.parallelism, MAX_RETRIEVAL_WORKERS))

        while pending:
            ready = [step for step in pending if all(dep in completed for dep in step.depends_on)]
            if not ready:
                # Remaining nodes are blocked by failed, missing, or cyclic
                # dependencies. The step engine records truthful SKIPPED
                # results using its normal dependency semantics.
                for step in pending:
                    self._ctx.executor.execute_step(step, shared, completed)
                break

            retrievals = [step for step in ready if step.step_type is StepType.RETRIEVE]
            other_steps = [step for step in ready if step.step_type is not StepType.RETRIEVE]

            if len(retrievals) > 1 and max_workers > 1:
                outcomes = self._execute_retrieval_batch(
                    retrievals,
                    completed,
                    max_workers,
                )
                for step in retrievals:
                    outcome = outcomes[step.step_id]
                    if outcome.result.success:
                        completed[step.step_id] = outcome.result.output
                        shared["_all_evidence"].extend(outcome.evidences)
                shared["_step_results"] = dict(completed)
            else:
                for step in retrievals:
                    outcome = self._execute_isolated_step(step, completed)
                    if outcome.result.success:
                        completed[step.step_id] = outcome.result.output
                        shared["_all_evidence"].extend(outcome.evidences)
                    shared["_step_results"] = dict(completed)

            for step in other_steps:
                outcome = self._execute_isolated_step(step, completed)
                if outcome.result.success:
                    completed[step.step_id] = outcome.result.output
                    shared["_all_evidence"].extend(outcome.evidences)
                shared["_step_results"] = dict(completed)

            processed = {id(step) for step in ready}
            pending = [step for step in pending if id(step) not in processed]

        return output_from_evidence(
            self._ctx.plan.tasks,
            shared["_all_evidence"],
        )

    def _execute_retrieval_batch(
        self,
        steps: list[PlanStep],
        completed: dict[int, Any],
        max_workers: int,
    ) -> dict[int, _StepOutcome]:
        dependency_snapshot = dict(completed)

        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(steps)),
            thread_name_prefix="agent-retrieval",
        ) as pool:
            futures = {
                step.step_id: pool.submit(
                    self._execute_isolated_step,
                    step,
                    dependency_snapshot,
                )
                for step in steps
            }
            return {step_id: future.result() for step_id, future in futures.items()}

    def _execute_isolated_step(
        self,
        step: PlanStep,
        completed: dict[int, Any],
    ) -> _StepOutcome:
        local_shared = dict(self._ctx.shared_context)
        local_shared["_all_evidence"] = []
        local_completed = dict(completed)
        result = self._ctx.executor.execute_step(
            step,
            local_shared,
            local_completed,
        )
        return _StepOutcome(
            result=result,
            evidences=list(local_shared["_all_evidence"]),
        )

    def _base_context(self) -> dict[str, Any]:
        shared = dict(self._ctx.shared_context)
        shared["_all_evidence"] = []
        shared["_step_results"] = {}
        return shared


def output_from_evidence(
    steps: list[PlanStep],
    evidences: list[Evidence],
) -> ExecutionOutput:
    """Build the stable dispatcher output in deterministic plan order."""
    context, citations = build_context_from_evidence(evidences)
    return ExecutionOutput(
        context=context,
        citations=citations,
        evidences=evidences,
        execution_results=[step.result for step in steps if step.result is not None],
    )
