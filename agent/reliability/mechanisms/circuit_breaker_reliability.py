# ============================================================
# CircuitBreakerReliability — Circuit breaker mechanism
# ============================================================
# Implements a 3-state circuit breaker to prevent cascading
# failures when a downstream service (Provider) is unhealthy.
#
# States:
#   CLOSED    → normal operation, passes all calls
#   OPEN      → rejects all calls immediately
#   HALF_OPEN → allows one probe call to test recovery
#
# Transitions:
#   CLOSED → OPEN      : failure_count >= failure_threshold
#   OPEN → HALF_OPEN    : after recovery_timeout_ms
#   HALF_OPEN → CLOSED  : probe call succeeds
#   HALF_OPEN → OPEN    : probe call fails
#
# In the pipeline:
#   Timeout → Retry → CircuitBreaker → Provider
#   CircuitBreaker is the innermost wrapper — it protects
#   the Provider from being called when it's known to be
#   unhealthy.
# ============================================================

import logging
import time
from typing import Optional

from agent.reliability.base_reliability import BaseReliability
from agent.reliability.reliability_context import ReliabilityContext
from agent.reliability.reliability_enums import CircuitState, ReliabilityType
from agent.reliability.reliability_models import CircuitBreakerPolicy, ReliabilityPolicy
from agent.reliability.reliability_result import ReliabilityResult

logger = logging.getLogger(__name__)


class CircuitBreakerReliability(BaseReliability):
    def __init__(self) -> None:
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: Optional[float] = None
        self._last_success_time: Optional[float] = None
        self._total_rejections: int = 0
        self._total_successes: int = 0
        self._total_failures: int = 0

    @property
    def mechanism_name(self) -> str:
        return "circuit_breaker"

    @property
    def mechanism_type(self) -> ReliabilityType:
        return ReliabilityType.CIRCUIT_BREAKER

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
        callable_fn = context.metadata.get("_callable")

        if callable_fn is None:
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.CIRCUIT_BREAKER,
                circuit_state=self._state.value,
            )

        failure_threshold = 5
        recovery_timeout_ms = 30000
        if isinstance(policy, CircuitBreakerPolicy):
            failure_threshold = policy.failure_threshold
            recovery_timeout_ms = policy.recovery_timeout_ms

        self._check_recovery(recovery_timeout_ms)

        if self._state == CircuitState.OPEN:
            self._total_rejections += 1
            logger.warning(
                "CircuitBreaker: OPEN — rejecting call (failures=%d, threshold=%d)",
                self._failure_count,
                failure_threshold,
            )
            return ReliabilityResult(
                success=False,
                policy=ReliabilityType.CIRCUIT_BREAKER,
                error="Circuit is OPEN — call rejected",
                circuit_state=self._state.value,
                metadata={
                    "failure_count": self._failure_count,
                    "failure_threshold": failure_threshold,
                    "state": self._state.value,
                },
            )

        start = time.time()
        try:
            _callable_result = callable_fn()
            elapsed_ms = (time.time() - start) * 1000

            self._on_success()

            logger.info(
                "CircuitBreaker: %s → success (latency=%.2fms)",
                self._state.value,
                elapsed_ms,
            )
            return ReliabilityResult(
                success=True,
                policy=ReliabilityType.CIRCUIT_BREAKER,
                latency_ms=elapsed_ms,
                circuit_state=self._state.value,
                metadata={
                    "failure_count": self._failure_count,
                    "failure_threshold": failure_threshold,
                    "state": self._state.value,
                },
            )
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000

            self._on_failure(failure_threshold)

            logger.error(
                "CircuitBreaker: %s → failure (%s) | failures=%d/%d",
                self._state.value,
                str(e),
                self._failure_count,
                failure_threshold,
            )
            return ReliabilityResult(
                success=False,
                policy=ReliabilityType.CIRCUIT_BREAKER,
                latency_ms=elapsed_ms,
                error=str(e),
                circuit_state=self._state.value,
                metadata={
                    "failure_count": self._failure_count,
                    "failure_threshold": failure_threshold,
                    "state": self._state.value,
                },
            )

    def _check_recovery(self, recovery_timeout_ms: int) -> None:
        if self._state != CircuitState.OPEN:
            return
        if self._last_failure_time is None:
            return
        elapsed_ms = (time.time() - self._last_failure_time) * 1000
        if elapsed_ms >= recovery_timeout_ms:
            self._state = CircuitState.HALF_OPEN
            logger.info(
                "CircuitBreaker: OPEN → HALF_OPEN (recovery timeout reached: %dms)",
                int(elapsed_ms),
            )

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            logger.info("CircuitBreaker: HALF_OPEN → CLOSED (probe succeeded)")
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._total_successes += 1
        self._last_success_time = time.time()

    def _on_failure(self, failure_threshold: int) -> None:
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            logger.warning("CircuitBreaker: HALF_OPEN → OPEN (probe failed)")
            self._state = CircuitState.OPEN
        elif self._failure_count >= failure_threshold:
            logger.warning(
                "CircuitBreaker: CLOSED → OPEN (failures=%d >= threshold=%d)",
                self._failure_count,
                failure_threshold,
            )
            self._state = CircuitState.OPEN

    def reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._last_success_time = None
        self._total_rejections = 0
        self._total_successes = 0
        self._total_failures = 0

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def total_rejections(self) -> int:
        return self._total_rejections

    @property
    def total_successes(self) -> int:
        return self._total_successes

    @property
    def total_failures(self) -> int:
        return self._total_failures
