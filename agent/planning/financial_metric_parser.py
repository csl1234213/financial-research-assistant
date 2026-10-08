"""Deterministic parsing for the governed financial-metrics tool.

This parser intentionally recognises only a small, explicit grammar.  It does
not evaluate expressions and it does not ask an LLM to infer missing values.
Queries outside the grammar remain on the normal planning path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

FinancialMetricOperation = Literal["growth_rate", "margin", "ratio", "cagr"]

_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_NUMBER_TOKEN = re.compile(_NUMBER)

_PATTERNS: tuple[
    tuple[FinancialMetricOperation, re.Pattern[str], tuple[str, ...]],
    ...,
] = (
    (
        "cagr",
        re.compile(
            rf"\bcagr\b.*?\bfrom\s+(?P<starting_value>{_NUMBER})"
            rf"\s+\bto\s+(?P<ending_value>{_NUMBER})"
            rf"\s+\bover\s+(?P<periods>{_NUMBER})\s+"
            r"(?:periods?|years?)\b",
            re.IGNORECASE,
        ),
        ("starting_value", "ending_value", "periods"),
    ),
    (
        "growth_rate",
        re.compile(
            rf"\b(?:growth|growth\s+rate|percentage\s+growth|revenue\s+growth)\b"
            rf".*?\bfrom\s+(?P<previous>{_NUMBER})"
            rf"\s+\bto\s+(?P<current>{_NUMBER})\b",
            re.IGNORECASE,
        ),
        ("previous", "current"),
    ),
    (
        "growth_rate",
        re.compile(
            rf"(?:增长率|增长百分比).*?从\s*(?P<previous>{_NUMBER})"
            rf"\s*(?:增长)?到\s*(?P<current>{_NUMBER})",
        ),
        ("previous", "current"),
    ),
    (
        "margin",
        re.compile(
            rf"\bmargin\b.*?\bof\s+(?P<numerator>{_NUMBER})"
            rf"\s+\bon\s+(?P<denominator>{_NUMBER})\b",
            re.IGNORECASE,
        ),
        ("numerator", "denominator"),
    ),
    (
        "ratio",
        re.compile(
            rf"\bratio\b.*?\bof\s+(?P<numerator>{_NUMBER})"
            rf"\s+\bto\s+(?P<denominator>{_NUMBER})\b",
            re.IGNORECASE,
        ),
        ("numerator", "denominator"),
    ),
)


@dataclass(frozen=True, slots=True)
class FinancialMetricInvocation:
    """A validated, typed invocation emitted by the rule-based planner."""

    operation: FinancialMetricOperation
    parameters: dict[str, int | float | str]
    tool_name: Literal["financial_metrics"] = "financial_metrics"


def parse_financial_metric_query(
    question: str,
) -> FinancialMetricInvocation | None:
    """Parse an unambiguous financial calculation request.

    A match is accepted only when every numeric token in the question belongs
    to the selected operation.  This prevents silently interpreting queries
    that contain dates, multiple candidate values, or other ambiguous inputs.
    """

    normalized = " ".join(question.strip().split())
    if not normalized:
        return None

    numeric_tokens = _NUMBER_TOKEN.findall(normalized)
    for operation, pattern, parameter_names in _PATTERNS:
        match = pattern.search(normalized)
        if match is None or len(numeric_tokens) != len(parameter_names):
            continue

        try:
            parameters = {
                name: _decimal_to_number(match.group(name))
                for name in parameter_names
            }
        except (InvalidOperation, ValueError):
            return None

        parameters["operation"] = operation
        return FinancialMetricInvocation(
            operation=operation,
            parameters=parameters,
        )

    return None


def _decimal_to_number(raw_value: str) -> int | float:
    value = Decimal(raw_value.replace(",", ""))
    if not value.is_finite():
        raise ValueError("financial metric input must be finite")
    if value == value.to_integral_value():
        return int(value)
    return float(value)
