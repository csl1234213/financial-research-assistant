# ============================================================
# Routing Policy — Unified entry point
# ============================================================
# Wraps a single routing strategy.
# Later can be extended to chain multiple policies:
#   Capability → Cost → Latency → Balanced
# ============================================================

from .base_policy import BaseRoutingPolicy
from .routing_context import RoutingContext
from .routing_result import RoutingResult


class RoutingPolicy:
    def __init__(
        self,
        policy: BaseRoutingPolicy,
    ):
        self._policy = policy

    def select(
        self,
        context: RoutingContext,
        providers: list[str] | None = None,
    ) -> RoutingResult:
        return self._policy.select(context, providers)
