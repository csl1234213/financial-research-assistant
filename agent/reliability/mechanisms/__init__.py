# ============================================================
# Mechanisms — Auto-registration
# ============================================================
# All reliability mechanism implementations are registered here on import.
# Add new mechanism classes here and they become available
# through ReliabilityFactory without any code changes.
# ============================================================

from agent.reliability.reliability_models import (
    CircuitBreakerPolicy,
    FallbackPolicy,
    HealthCheckPolicy,
    RateLimiterPolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from agent.reliability.reliability_registry import ReliabilityRegistry

from .circuit_breaker_reliability import CircuitBreakerReliability
from .fallback_reliability import FallbackReliability
from .health_check_reliability import HealthCheckReliability
from .rate_limiter_reliability import RateLimiterReliability
from .retry_reliability import RetryReliability
from .timeout_reliability import TimeoutReliability

ReliabilityRegistry.register(
    "retry",
    RetryReliability,
    RetryPolicy(),
)

ReliabilityRegistry.register(
    "timeout",
    TimeoutReliability,
    TimeoutPolicy(),
)

ReliabilityRegistry.register(
    "circuit_breaker",
    CircuitBreakerReliability,
    CircuitBreakerPolicy(),
)

ReliabilityRegistry.register(
    "fallback",
    FallbackReliability,
    FallbackPolicy(),
)

ReliabilityRegistry.register(
    "health_check",
    HealthCheckReliability,
    HealthCheckPolicy(),
)

ReliabilityRegistry.register(
    "rate_limiter",
    RateLimiterReliability,
    RateLimiterPolicy(),
)
