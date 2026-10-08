# ============================================================
# Complexity Result — Analyzer Output
# ============================================================
# Output of ComplexityAnalyzer — one complexity assessment
# with reasoning and factor breakdown. UI can display
# the reason and factors for explainable routing decisions.
# ============================================================

from dataclasses import dataclass, field

from .complexity_models import ComplexityModel


@dataclass(slots=True)
class ComplexityResult:
    complexity: ComplexityModel

    reason: str

    factors: dict[str, float] = field(default_factory=dict)
