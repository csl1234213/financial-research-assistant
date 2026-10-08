"""Fail-closed execution for explicit governed financial tool calls."""

from __future__ import annotations

from typing import Any

from agent.execution.execution_handler import (
    BaseExecutionHandler,
    ExecutionHandlerContext,
    ExecutionOutput,
)
from agent.execution.strategy_enums import ExecutionStrategyType
from agent.execution_plan import PlanStep, StepStatus, StepType
from agent.execution_result import ExecutionResult

_ALLOWED_TOOL = "financial_metrics"


class ToolCallingHandler(BaseExecutionHandler):
    """Dispatch typed tool steps exactly once through the step engine."""

    @property
    def strategy_type(self) -> ExecutionStrategyType:
        return ExecutionStrategyType.TOOL_CALLING

    def execute(
        self,
        ctx: ExecutionHandlerContext,
    ) -> ExecutionOutput:
        shared = dict(ctx.shared_context)
        shared["_all_evidence"] = []
        shared["_tool_trace"] = []
        completed: dict[int, Any] = {}

        for step in ctx.plan.tasks:
            if not all(
                dependency in completed
                for dependency in step.depends_on
            ):
                self._record_rejection(
                    step,
                    "Dependencies not met",
                    StepStatus.SKIPPED,
                    shared,
                )
                continue

            if step.step_type is not StepType.TOOL_CALL:
                self._record_rejection(
                    step,
                    (
                        "Tool-calling strategy requires an explicit "
                        "tool_call plan step"
                    ),
                    StepStatus.SKIPPED,
                    shared,
                )
                continue

            if step.tool_name != _ALLOWED_TOOL:
                self._record_rejection(
                    step,
                    (
                        f"Tool '{step.tool_name or '<missing>'}' is not "
                        f"enabled; allowed tool: {_ALLOWED_TOOL}"
                    ),
                    StepStatus.FAILED,
                    shared,
                )
                continue

            # The composition root owns the TOOL_CALL handler and its
            # ToolEngine authorization hook.  Calling execute_step once here
            # preserves dependency bookkeeping without duplicating execution.
            trace_count = len(shared["_tool_trace"])
            result = ctx.executor.execute_step(step, shared, completed)
            if len(shared["_tool_trace"]) == trace_count:
                trace = {
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "operation": step.parameters.get("operation"),
                    "status": (
                        "success"
                        if result.success
                        else StepStatus.FAILED.value
                    ),
                    "policy": "financial_metrics_only",
                }
                if result.success:
                    trace["output"] = result.output
                else:
                    trace["error"] = result.error or "Tool execution failed"
                shared["_tool_trace"].append(trace)

        tool_calls = list(shared["_tool_trace"])
        return ExecutionOutput(
            context=_format_tool_context(tool_calls),
            citations=[],
            evidences=[],
            execution_results=[
                step.result
                for step in ctx.plan.tasks
                if step.result is not None
            ],
            tool_calls=tool_calls,
        )

    @staticmethod
    def _record_rejection(
        step: PlanStep,
        error: str,
        status: StepStatus,
        shared: dict[str, Any],
    ) -> None:
        step.status = status
        step.result = ExecutionResult(
            step_id=step.step_id,
            success=False,
            error=error,
        )
        shared["_tool_trace"].append(
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "operation": step.parameters.get("operation"),
                "status": status.value,
                "error": error,
                "policy": "financial_metrics_only",
            }
        )


def _format_tool_context(tool_calls: list[dict[str, Any]]) -> str:
    successful = [
        call
        for call in tool_calls
        if call.get("status") == "success"
        and isinstance(call.get("output"), dict)
    ]
    if not successful:
        return ""

    lines = ["Deterministic financial calculation:"]
    for call in successful:
        output = call["output"]
        operation = output.get("operation", call.get("operation", "metric"))
        value = output.get("value")
        unit = output.get("unit", "")
        inputs = output.get("inputs", {})
        input_text = ", ".join(
            f"{key}={value}"
            for key, value in sorted(inputs.items())
        )
        unit_suffix = f" {unit}" if unit else ""
        lines.append(
            f"- {operation}: {value}{unit_suffix} ({input_text})"
        )
    return "\n".join(lines)
