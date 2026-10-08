"""Typed public result contract for the composed RAG pipeline."""

from __future__ import annotations

from typing import Any, NamedTuple

from agent.execution_plan import ExecutionPlan
from agent.reasoning_models import Evidence


class RAGResult(NamedTuple):
    """Final output of :func:`core.core_engine.run_rag`.

    ``NamedTuple`` is intentional here: new callers can use stable field
    names, while legacy callers retain the original eleven-item tuple
    unpacking and indexing behavior.
    """

    report: str
    citations: list[dict[str, Any]]
    context: str
    research_mode: str
    intent: dict[str, Any]
    evidence: list[Evidence]
    plan: ExecutionPlan | None
    routing: dict[str, Any] | None
    planning: dict[str, Any] | None
    execution: dict[str, Any] | None
    workflow: dict[str, Any] | None
