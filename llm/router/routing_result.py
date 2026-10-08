# ============================================================
# Routing Result
# ============================================================
# Output of the Router — tells the system which provider/model
# to use and why. Designed for explainable routing in UI.
# ============================================================

from dataclasses import dataclass


@dataclass(slots=True)
class RoutingResult:
    provider: str

    model: str

    reason: str

    confidence: float

    fallback_provider: str | None = None

    decision_time_ms: float | None = None

    estimated_cost: float | None = None

    estimated_latency_ms: int | None = None
