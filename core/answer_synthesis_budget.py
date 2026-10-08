"""Server-owned bounded narrative time policy; never inferred from client input."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class NarrativeTimeBudget:
    total_seconds: float = 120
    per_call_seconds: float | None = None

    def __post_init__(self):
        values = [(self.total_seconds, 600)]
        if self.per_call_seconds is not None:
            values.append((self.per_call_seconds, float("inf")))
        for value, maximum in values:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 < value <= maximum):
                raise ValueError("INVALID_NARRATIVE_TIME_BUDGET")

    def allowance(self, *, deadline: float, now: float) -> float:
        """Limit each call by both absolute workflow deadline and phase ceiling."""
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in (deadline, now)):
            raise ValueError("INVALID_NARRATIVE_CLOCK")
        remaining = max(0, deadline - now)
        return remaining if self.per_call_seconds is None else min(self.per_call_seconds, remaining)
