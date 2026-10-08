# ============================================================
# Reliability Enums
# ============================================================
# Unified enums for reliability type, status, and scope.
# 不依赖 Runtime / Provider / Tool。
# 独立领域模型，与 Resilience4j / Polly 设计对齐。
#
# ReliabilityType  → 可靠性机制类型（Retry / Timeout / CircuitBreaker 等）
# ReliabilityStatus → 机制启用状态（ACTIVE / DISABLED）
#                      —— 所有机制共用的通用状态
# CircuitState      → 熔断器状态（OPEN / HALF_OPEN / CLOSED）
#                      —— 仅 CircuitBreaker 维护，不污染通用状态
# ReliabilityScope  → 作用范围（哪个模块应用可靠性策略）
# ============================================================

from enum import Enum


class ReliabilityType(Enum):
    RETRY = "retry"
    TIMEOUT = "timeout"
    CIRCUIT_BREAKER = "circuit_breaker"
    FALLBACK = "fallback"
    HEALTH_CHECK = "health_check"
    RATE_LIMITER = "rate_limiter"


class ReliabilityStatus(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class CircuitState(Enum):
    OPEN = "open"
    HALF_OPEN = "half_open"
    CLOSED = "closed"


class ReliabilityScope(Enum):
    RUNTIME = "runtime"
    WORKFLOW = "workflow"
    EXECUTION = "execution"
    TOOL = "tool"
    PROVIDER = "provider"
    MEMORY = "memory"
