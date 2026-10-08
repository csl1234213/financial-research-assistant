# ============================================================
# Base Routing Policy
# ============================================================
# Abstract interface for all routing policies.
# Every policy takes a RoutingContext and returns a RoutingResult.
# This layer will never change — new policies only add new
# implementations.
# ============================================================

from abc import ABC, abstractmethod

from .routing_context import RoutingContext
from .routing_result import RoutingResult


class BaseRoutingPolicy(ABC):
    @abstractmethod
    def select(
        self,
        context: RoutingContext,
        providers: list[str] | None = None,
    ) -> RoutingResult:
        """Return the best routing result for the given context.

        Args:
            context: Business requirements for this request.
            providers: Available provider names (optional).
                       If None, the policy discovers providers itself.
        """
        ...
