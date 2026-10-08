"""Governed bridge from a typed plan step to ``FinancialMetricsTool``."""

from __future__ import annotations

from typing import Any

from agent.execution_plan import PlanStep
from agent.tools.implementations import register_builtin_tools
from agent.tools.implementations.financial_metrics_tool import (
    SUPPORTED_FINANCIAL_METRIC_OPERATIONS,
)
from agent.tools.tool_authorization import ToolAuthorizationDecision
from agent.tools.tool_context import ToolContext
from agent.tools.tool_engine import ToolEngine
from agent.tools.tool_enums import ToolStatus

FINANCIAL_METRICS_TOOL_NAME = "financial_metrics"
FINANCIAL_METRICS_POLICY = "agent_financial_metrics_v1"


def authorize_financial_metrics_tool(
    tool_name: str,
    context: ToolContext,
) -> ToolAuthorizationDecision:
    """Allow only deterministic financial operations; deny everything else."""

    operation = context.parameters.get("operation")
    if tool_name != FINANCIAL_METRICS_TOOL_NAME:
        return ToolAuthorizationDecision(
            allowed=False,
            reason=(
                f"Tool '{tool_name}' is not authorized for Agent execution"
            ),
            metadata={"policy": FINANCIAL_METRICS_POLICY},
        )
    if operation not in SUPPORTED_FINANCIAL_METRIC_OPERATIONS:
        return ToolAuthorizationDecision(
            allowed=False,
            reason="Financial metric operation is not authorized",
            metadata={"policy": FINANCIAL_METRICS_POLICY},
        )
    return ToolAuthorizationDecision(
        allowed=True,
        metadata={
            "policy": FINANCIAL_METRICS_POLICY,
            "operation": operation,
        },
    )


class FinancialMetricsStepHandler:
    """Execute one planned financial metric through the unified ToolEngine."""

    def __init__(self, tool_engine: ToolEngine) -> None:
        self._tool_engine = tool_engine

    def __call__(
        self,
        step: PlanStep,
        shared_context: dict[str, Any],
    ) -> dict[str, Any]:
        tool_name = step.tool_name or ""
        tool_context = ToolContext(
            parameters=dict(step.parameters),
            tenant_id=_trusted_tenant_id(shared_context),
        )
        # Registry tests and plugin reloads may intentionally clear the global
        # registry. The production composition boundary restores the
        # idempotent built-in set before executing its allowlisted tool.
        register_builtin_tools()
        result = self._tool_engine.execute(tool_context, tool_name)

        trace = {
            "step_id": step.step_id,
            "tool_name": tool_name,
            "operation": step.parameters.get("operation"),
            "status": result.status.value,
            "latency_ms": result.latency_ms,
            "policy": FINANCIAL_METRICS_POLICY,
        }
        if result.status is ToolStatus.SUCCESS:
            trace["output"] = result.output
        else:
            trace["error"] = result.error or "Tool execution failed"
        shared_context.setdefault("_tool_trace", []).append(trace)

        if result.status is not ToolStatus.SUCCESS:
            raise RuntimeError(
                result.error or "Financial metrics tool execution failed"
            )
        if not isinstance(result.output, dict):
            raise RuntimeError(
                "Financial metrics tool returned an invalid result"
            )
        return result.output


def _trusted_tenant_id(shared_context: dict[str, Any]) -> int | None:
    tenant_id = shared_context.get("tenant_id")
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int):
        return None
    return tenant_id
