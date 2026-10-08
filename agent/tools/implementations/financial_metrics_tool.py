"""Deterministic financial calculations exposed through the Tool layer.

The tool deliberately supports a small, audited operation set.  It performs no
code execution, database access, or network I/O, which makes it safe to reuse
from the Agent runtime and MCP composition root.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from agent.tools.base_tool import BaseTool
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolStatus, ToolType
from agent.tools.tool_models import ToolCapability, ToolMetadata
from agent.tools.tool_result import ToolResult

SUPPORTED_FINANCIAL_METRIC_OPERATIONS = frozenset(
    {"growth_rate", "margin", "ratio", "cagr"}
)


class FinancialMetricsTool(BaseTool):
    """Calculate common financial metrics from explicit numeric inputs."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="financial_metrics",
            tool_type=ToolType.CUSTOM,
            description=(
                "Calculate growth rate, margin, ratio, or CAGR using explicit "
                "numeric inputs"
            ),
            version="1.0.0",
            capability=ToolCapability(
                supports_parallel=True,
                supports_retry=False,
                supports_async=False,
            ),
            metadata={
                "operations": sorted(SUPPORTED_FINANCIAL_METRIC_OPERATIONS),
                "side_effects": "none",
            },
        )

    def supports(self, context: ToolContext) -> bool:
        return (
            context.parameters.get("operation")
            in SUPPORTED_FINANCIAL_METRIC_OPERATIONS
        )

    def execute(self, context: ToolContext) -> ToolResult:
        started = perf_counter()
        operation = context.parameters.get("operation")
        precision = context.parameters.get("precision", 4)

        try:
            if operation not in SUPPORTED_FINANCIAL_METRIC_OPERATIONS:
                raise ValueError(
                    "operation must be one of: "
                    + ", ".join(
                        sorted(SUPPORTED_FINANCIAL_METRIC_OPERATIONS)
                    )
                )
            if isinstance(precision, bool) or not isinstance(precision, int):
                raise ValueError("precision must be an integer")
            if not 0 <= precision <= 10:
                raise ValueError("precision must be between 0 and 10")

            value, unit, inputs = self._calculate(operation, context.parameters)
            rounded = round(value, precision)
        except (InvalidOperation, TypeError, ValueError, ZeroDivisionError) as exc:
            return ToolResult(
                status=ToolStatus.FAILED,
                error=str(exc),
                latency_ms=(perf_counter() - started) * 1_000,
                metadata={
                    "tool": type(self).__name__,
                    "operation": operation,
                    "failure_code": "invalid_input",
                },
            )

        return ToolResult(
            status=ToolStatus.SUCCESS,
            output={
                "operation": operation,
                "value": rounded,
                "unit": unit,
                "precision": precision,
                "inputs": inputs,
            },
            latency_ms=(perf_counter() - started) * 1_000,
            metadata={
                "tool": type(self).__name__,
                "operation": operation,
                "deterministic": True,
                "side_effects": "none",
            },
        )

    def _calculate(
        self,
        operation: str,
        parameters: dict[str, Any],
    ) -> tuple[float, str, dict[str, float]]:
        if operation == "growth_rate":
            current = self._number(parameters, "current")
            previous = self._number(parameters, "previous")
            if previous == 0:
                raise ValueError("previous must be non-zero")
            result = ((current - previous) / abs(previous)) * Decimal("100")
            return float(result), "percent", {
                "current": float(current),
                "previous": float(previous),
            }

        if operation == "margin":
            numerator = self._number(parameters, "numerator")
            denominator = self._number(parameters, "denominator")
            if denominator == 0:
                raise ValueError("denominator must be non-zero")
            result = (numerator / denominator) * Decimal("100")
            return float(result), "percent", {
                "numerator": float(numerator),
                "denominator": float(denominator),
            }

        if operation == "ratio":
            numerator = self._number(parameters, "numerator")
            denominator = self._number(parameters, "denominator")
            if denominator == 0:
                raise ValueError("denominator must be non-zero")
            return float(numerator / denominator), "ratio", {
                "numerator": float(numerator),
                "denominator": float(denominator),
            }

        starting_value = self._number(parameters, "starting_value")
        ending_value = self._number(parameters, "ending_value")
        periods = self._number(parameters, "periods")
        if starting_value <= 0 or ending_value <= 0:
            raise ValueError("starting_value and ending_value must be positive")
        if periods <= 0:
            raise ValueError("periods must be positive")
        result = (
            math.pow(float(ending_value / starting_value), 1 / float(periods))
            - 1
        ) * 100
        if not math.isfinite(result):
            raise ValueError("calculation produced a non-finite result")
        return result, "percent", {
            "starting_value": float(starting_value),
            "ending_value": float(ending_value),
            "periods": float(periods),
        }

    @staticmethod
    def _number(parameters: dict[str, Any], name: str) -> Decimal:
        value = parameters.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError(f"{name} must be a number")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return Decimal(str(value))
