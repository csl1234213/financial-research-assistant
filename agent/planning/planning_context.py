# ============================================================
# Planning Context
# ============================================================
# Unified input for all Planner components.
# Intent, task, complexity, and routing all read from
# this single context object.
# ============================================================

from dataclasses import dataclass, field


@dataclass(slots=True)
class PlanningContext:
    question: str

    companies: list[str] = field(default_factory=list)

    years: list[str] = field(default_factory=list)

    metadata: dict = field(default_factory=dict)
