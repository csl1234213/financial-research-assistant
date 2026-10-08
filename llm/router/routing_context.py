# ============================================================
# Routing Context
# ============================================================
# Business requirement object — no provider-specific knowledge.
# Planner fills this; Router consumes it to produce a RoutingResult.
# ============================================================

from dataclasses import dataclass

from .routing_enums import (
    RoutingPriority,
    TaskType,
)


@dataclass(slots=True)
class RoutingContext:
    task: TaskType

    priority: RoutingPriority = RoutingPriority.BALANCED

    requires_image: bool = False

    requires_audio: bool = False

    requires_video: bool = False

    requires_reasoning: bool = False

    requires_tools: bool = False

    requires_stream: bool = False

    requires_json: bool = False

    estimated_tokens: int = 0

    max_cost: float | None = None

    complexity_score: float | None = None

    preferred_provider: str | None = None
