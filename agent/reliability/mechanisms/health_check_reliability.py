# ============================================================
# HealthCheckReliability — Health check mechanism
# ============================================================
# Validates whether a downstream service (Provider) is healthy
# before allowing calls to proceed. Uses a check function with
# configurable interval to avoid excessive pings.
#
# States:
#   "healthy"   — service is available, calls proceed
#   "unhealthy" — service is unavailable, calls are rejected
#
# In the pipeline:
#   HealthCheck → RateLimiter → Timeout → Retry → CircuitBreaker → Fallback → Provider
#   HealthCheck is the outermost guard — it prevents the entire
#   pipeline from running when the service is known to be down.
# ============================================================

import logging
import time
from typing import Optional

from agent.reliability.base_reliability import BaseReliability
from agent.reliability.reliability_context import ReliabilityContext
from agent.reliability.reliability_enums import ReliabilityType
from agent.reliability.reliability_models import HealthCheckPolicy, ReliabilityPolicy
from agent.reliability.reliability_result import ReliabilityResult

logger = logging.getLogger(__name__)


class HealthCheckReliability(BaseReliability):
    def __init__(self) -> None:
        self._is_healthy: bool = True
        self._last_check_time: float = 0.0
        self._check_count: int = 0
        self._failed_check_count: int = 0
        self._default_check_fn: Optional[callable] = None

    @property
    def mechanism_name(self) -> str:
        return "health_check"

    @property
    def mechanism_type(self) -> ReliabilityType:
        return ReliabilityType.HEALTH_CHECK

    @property
    def is_healthy(self) -> bool:
        return self._is_healthy

    @property
    def check_count(self) -> int:
        return self._check_count

    @property
    def failed_check_count(self) -> int:
        return self._failed_check_count

    def set_healthy(self) -> None:
        self._is_healthy = True
        self._last_check_time = time.time()

    def set_unhealthy(self) -> None:
        self._is_healthy = False
        self._last_check_time = time.time()

    def set_check_function(self, fn: callable) -> None:
        self._default_check_fn = fn

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
        interval_ms = 30000
        check_fn = self._default_check_fn

        if isinstance(policy, HealthCheckPolicy):
            interval_ms = policy.interval_ms
            if policy.check_function is not None:
                check_fn = policy.check_function

        if not policy.enabled:
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.HEALTH_CHECK,
                metadata={
                    "health_status": "healthy",
                    "reason": "health check disabled",
                },
            )

        now = time.time()
        elapsed_ms = (now - self._last_check_time) * 1000

        if elapsed_ms < interval_ms and self._last_check_time > 0:
            if not self._is_healthy:
                return ReliabilityResult(
                    success=False,
                    policy=ReliabilityType.HEALTH_CHECK,
                    error="Service is unhealthy",
                    metadata={
                        "health_status": "unhealthy",
                        "reason": "cached unhealthy status",
                    },
                )
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.HEALTH_CHECK,
                metadata={
                    "health_status": "healthy",
                    "reason": "cached healthy status",
                },
            )

        self._check_count += 1
        self._last_check_time = now

        if check_fn is not None:
            try:
                healthy = check_fn()
            except Exception:
                healthy = False
        else:
            healthy = self._is_healthy

        if healthy:
            self._is_healthy = True
            logger.info("HealthCheck: healthy (check #%d)", self._check_count)
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.HEALTH_CHECK,
                metadata={
                    "health_status": "healthy",
                    "check_count": self._check_count,
                },
            )
        else:
            self._is_healthy = False
            self._failed_check_count += 1
            logger.warning("HealthCheck: unhealthy (check #%d)", self._check_count)
            return ReliabilityResult(
                success=False,
                policy=ReliabilityType.HEALTH_CHECK,
                error="Service is unhealthy",
                metadata={
                    "health_status": "unhealthy",
                    "check_count": self._check_count,
                    "failed_check_count": self._failed_check_count,
                },
            )

    def reset(self) -> None:
        self._is_healthy = True
        self._last_check_time = 0.0
        self._check_count = 0
        self._failed_check_count = 0
        self._default_check_fn = None
