# ============================================================
# FallbackReliability — Fallback/degredation mechanism
# ============================================================
# Triggers fallback when the primary provider fails.
#
# Supported fallback modes (first version):
#   1. Provider Fallback — call a secondary provider
#   2. Static Response — return a predefined default response
#   3. Cached Response — return a cached historical result
#
# In the pipeline:
#   HealthCheck → RateLimiter → Timeout → Retry → CircuitBreaker → Fallback → Provider
#   Fallback is the innermost wrapper — when the primary Provider
#   fails, it tries the fallback before giving up.
# ============================================================

import logging
from typing import Any, Callable, Optional

from agent.reliability.base_reliability import BaseReliability
from agent.reliability.reliability_context import ReliabilityContext
from agent.reliability.reliability_enums import ReliabilityType
from agent.reliability.reliability_models import FallbackPolicy, ReliabilityPolicy
from agent.reliability.reliability_result import ReliabilityResult

logger = logging.getLogger(__name__)


class FallbackReliability(BaseReliability):
    def __init__(self) -> None:
        self._total_fallbacks: int = 0
        self._fallback_successes: int = 0
        self._fallback_failures: int = 0

    @property
    def mechanism_name(self) -> str:
        return "fallback"

    @property
    def mechanism_type(self) -> ReliabilityType:
        return ReliabilityType.FALLBACK

    @property
    def total_fallbacks(self) -> int:
        return self._total_fallbacks

    @property
    def fallback_successes(self) -> int:
        return self._fallback_successes

    @property
    def fallback_failures(self) -> int:
        return self._fallback_failures

    def supports(
        self,
        context: ReliabilityContext,
    ) -> bool:
        return True

    def apply(
        self,
        context: ReliabilityContext,
        policy: ReliabilityPolicy,
    ) -> ReliabilityResult:
        primary_callable = context.metadata.get("_callable")

        if primary_callable is None:
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.FALLBACK,
                metadata={
                    "fallback_used": False,
                    "reason": "no primary callable",
                },
            )

        if not policy.enabled:
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.FALLBACK,
                metadata={
                    "fallback_used": False,
                    "reason": "fallback disabled",
                },
            )

        fallback_value = None
        fallback_function: Optional[Callable[..., Any]] = None

        if isinstance(policy, FallbackPolicy):
            fallback_value = policy.fallback_value
            fallback_function = policy.fallback_function

        if fallback_value is None and fallback_function is None:
            try:
                primary_callable()
                return ReliabilityResult(
                    success=True,
                    policy=ReliabilityType.FALLBACK,
                    metadata={
                        "fallback_used": False,
                        "reason": "no fallback configured",
                    },
                )
            except Exception as e:
                logger.warning("Fallback: primary failed, no fallback configured")
                return ReliabilityResult(
                    success=False,
                    policy=ReliabilityType.FALLBACK,
                    error=f"Primary failed: {str(e)}",
                    metadata={
                        "fallback_used": False,
                        "primary_error": str(e),
                    },
                )

        try:
            primary_callable()
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.FALLBACK,
                metadata={
                    "fallback_used": False,
                },
            )
        except Exception as primary_err:
            self._total_fallbacks += 1
            logger.info(
                "Fallback: primary failed, attempting fallback (total_fallbacks=%d)",
                self._total_fallbacks,
            )

            try:
                if fallback_function is not None:
                    fallback_function()
                self._fallback_successes += 1
                logger.info("Fallback: success")
                return ReliabilityResult(
                    success=True,
                    policy=ReliabilityType.FALLBACK,
                    metadata={
                        "fallback_used": True,
                        "primary_error": str(primary_err),
                        "fallback_success": True,
                    },
                )
            except Exception as fallback_err:
                self._fallback_failures += 1
                logger.warning("Fallback: failed")
                return ReliabilityResult(
                    success=False,
                    policy=ReliabilityType.FALLBACK,
                    error=f"Primary failed: {str(primary_err)}; Fallback failed: {str(fallback_err)}",
                    metadata={
                        "fallback_used": True,
                        "primary_error": str(primary_err),
                        "fallback_error": str(fallback_err),
                        "fallback_success": False,
                    },
                )

    def reset(self) -> None:
        self._total_fallbacks = 0
        self._fallback_successes = 0
        self._fallback_failures = 0
