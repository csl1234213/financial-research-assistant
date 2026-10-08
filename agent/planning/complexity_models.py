# ============================================================
# Complexity Model — Unified Complexity Data Model
# ============================================================
# Describes the estimated complexity of one task.
# No calculation logic here — all scoring lives in
# ComplexityAnalyzer (Step 2).
# ============================================================

from dataclasses import dataclass

from .task_enums import ComplexityLevel


@dataclass(slots=True)
class ComplexityModel:
    level: ComplexityLevel = ComplexityLevel.LOW

    score: float = 0.0

    estimated_tokens: int = 0

    estimated_latency_ms: int = 0

    estimated_cost: float = 0.0
