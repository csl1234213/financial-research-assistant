# ============================================================
# Reliability Models
# ============================================================
# Core data models for the Reliability Layer.
#
# ReliabilityPolicy    — 抽象策略基类，所有可靠性策略的父类。
# RetryCondition       — 重试触发条件（预留接口，未实现）。
#                         支持 HTTP 429、HTTP 500、Timeout、
#                         Provider Busy、LLM Rate Limit 等。
# RetryPolicy          — 重试策略：max_retries, backoff_ms,
#                         retry_exceptions, retry_conditions。
# TimeoutPolicy        — 超时策略：timeout_ms, timeout_behavior。
# CircuitBreakerPolicy — 熔断策略：failure_threshold,
#                         recovery_timeout_ms, half_open_max_calls,
#                         内部维护 CircuitState。
# FallbackPolicy       — 降级策略：fallback_function, fallback_value。
# HealthCheckPolicy    — 健康检查策略：interval_ms,
#                         check_function（sync/async 统一）。
# RateLimiterPolicy    — 限流策略：max_requests, window_ms。
#
# 设计原则：
#   - 每个策略都是一个独立的数据模型，不包含执行逻辑。
#   - 策略与 Reliability 机制解耦，由 Engine 负责协调。
#   - 不包含 Runtime / Provider 依赖。
#
# Mirrors:
#   ReliabilityPolicy ↔ MetricDefinition
#   RetryPolicy       ↔ MetricRecord
# ============================================================

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, Union

from .reliability_enums import CircuitState, ReliabilityType


@dataclass(slots=True)
class ReliabilityPolicy:
    policy_type: ReliabilityType
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# RetryCondition — 预留接口
# ============================================================
# 企业级重试条件抽象。
# 当前仅定义数据模型，不包含匹配逻辑。
# 后续 Provider / Tool 层可共用。
#
# 典型场景：
#   HTTP 429      → condition_type="http_status", condition_value=429
#   HTTP 500      → condition_type="http_status", condition_value=500
#   Timeout       → condition_type="exception", condition_value="TimeoutError"
#   Provider Busy → condition_type="provider_status", condition_value="busy"
#   LLM Rate Limit→ condition_type="provider_status", condition_value="rate_limited"
# ============================================================


@dataclass(slots=True)
class RetryCondition:
    condition_type: str
    condition_value: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetryPolicy(ReliabilityPolicy):
    policy_type: ReliabilityType = ReliabilityType.RETRY
    max_retries: int = 3
    backoff_ms: int = 1000
    retry_exceptions: List[Type[BaseException]] = field(default_factory=lambda: [Exception])
    retry_conditions: List[RetryCondition] = field(default_factory=list)
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TimeoutPolicy(ReliabilityPolicy):
    policy_type: ReliabilityType = ReliabilityType.TIMEOUT
    timeout_ms: int = 30000
    timeout_behavior: str = "raise"
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CircuitBreakerPolicy(ReliabilityPolicy):
    policy_type: ReliabilityType = ReliabilityType.CIRCUIT_BREAKER
    failure_threshold: int = 5
    recovery_timeout_ms: int = 30000
    half_open_max_calls: int = 1
    initial_state: CircuitState = CircuitState.CLOSED
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FallbackPolicy(ReliabilityPolicy):
    policy_type: ReliabilityType = ReliabilityType.FALLBACK
    fallback_value: Any = None
    fallback_function: Optional[Callable[..., Any]] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HealthCheckPolicy(ReliabilityPolicy):
    policy_type: ReliabilityType = ReliabilityType.HEALTH_CHECK
    interval_ms: int = 30000
    check_function: Optional[Union[Callable[..., bool], Callable[..., Awaitable[bool]]]] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RateLimiterPolicy(ReliabilityPolicy):
    policy_type: ReliabilityType = ReliabilityType.RATE_LIMITER
    max_requests: int = 100
    window_ms: int = 60000
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
