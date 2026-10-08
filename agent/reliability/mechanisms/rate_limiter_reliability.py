# ============================================================
# RateLimiterReliability — Fixed-window rate limiter
# ============================================================
# Limits the number of requests within a time window.
# Uses a simple fixed-window algorithm:
#   - Track request timestamps in a list
#   - On each call, remove timestamps outside the window
#   - If count exceeds max_requests, reject the call
#
# In the pipeline:
#   HealthCheck → RateLimiter → Timeout → Retry → CircuitBreaker → Fallback → Provider
#   RateLimiter protects the downstream service from being
#   overwhelmed by excessive requests.
# ============================================================

import logging
import time

from agent.reliability.base_reliability import BaseReliability
from agent.reliability.reliability_context import ReliabilityContext
from agent.reliability.reliability_enums import ReliabilityType
from agent.reliability.reliability_models import RateLimiterPolicy, ReliabilityPolicy
from agent.reliability.reliability_result import ReliabilityResult

logger = logging.getLogger(__name__)


class RateLimiterReliability(BaseReliability):
    def __init__(self) -> None:
        self._timestamps: list = []
        self._total_requests: int = 0
        self._blocked_requests: int = 0

    @property
    def mechanism_name(self) -> str:
        return "rate_limiter"

    @property
    def mechanism_type(self) -> ReliabilityType:
        return ReliabilityType.RATE_LIMITER

    @property
    def total_requests(self) -> int:
        return self._total_requests

    @property
    def blocked_requests(self) -> int:
        return self._blocked_requests

    @property
    def remaining(self) -> int:
        return max(0, len(self._timestamps))

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
        max_requests = 100
        window_ms = 60000

        if isinstance(policy, RateLimiterPolicy):
            max_requests = policy.max_requests
            window_ms = policy.window_ms

        if not policy.enabled:
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.RATE_LIMITER,
                metadata={
                    "rate_limit_remaining": max_requests,
                    "reason": "rate limiter disabled",
                },
            )

        now = time.time()
        window_seconds = window_ms / 1000.0
        cutoff = now - window_seconds

        self._timestamps = [t for t in self._timestamps if t > cutoff]

        current_count = len(self._timestamps)

        if current_count >= max_requests:
            self._blocked_requests += 1
            logger.warning(
                "RateLimiter: blocked — %d/%d requests in window",
                current_count,
                max_requests,
            )
            return ReliabilityResult(
                success=False,
                policy=ReliabilityType.RATE_LIMITER,
                error=f"Rate limit exceeded: {current_count}/{max_requests} requests",
                metadata={
                    "rate_limit_remaining": 0,
                    "rate_limit_max": max_requests,
                    "rate_limit_blocked": True,
                    "window_ms": window_ms,
                },
            )

        self._timestamps.append(now)
        self._total_requests += 1
        remaining = max_requests - len(self._timestamps)

        logger.info(
            "RateLimiter: allowed — %d/%d remaining",
            remaining,
            max_requests,
        )
        return ReliabilityResult(
            success=True,
            policy=ReliabilityType.RATE_LIMITER,
            metadata={
                "rate_limit_remaining": remaining,
                "rate_limit_max": max_requests,
                "rate_limit_blocked": False,
                "window_ms": window_ms,
            },
        )

    def reset(self) -> None:
        self._timestamps.clear()
        self._total_requests = 0
        self._blocked_requests = 0
