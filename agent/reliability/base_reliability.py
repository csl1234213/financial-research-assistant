# ============================================================
# BaseReliability — Abstract interface for all reliability mechanisms
# ============================================================
# 每一个具体 Reliability 机制（Retry、Timeout、CircuitBreaker、
# Fallback、HealthCheck、RateLimiter）都必须实现这个接口。
#
# 设计原则：
#   - Reliability 不负责决定「要不要应用」— 由 Engine 决定
#   - Reliability 只负责 supports / apply / reset
#   - 不包含 Export / Runtime 依赖
#   - 不包含 Registry / Factory 逻辑
#
# Mirrors:
#   BaseReliability ↔ BaseMetric
#   BaseReliability ↔ BaseTracer
#   BaseReliability ↔ BaseTool
#   BaseReliability ↔ BaseMemory
# ============================================================

from abc import ABC, abstractmethod

from .reliability_context import ReliabilityContext
from .reliability_enums import ReliabilityType
from .reliability_models import ReliabilityPolicy
from .reliability_result import ReliabilityResult


class BaseReliability(ABC):
    @property
    @abstractmethod
    def mechanism_name(self) -> str: ...

    @property
    @abstractmethod
    def mechanism_type(self) -> ReliabilityType: ...

    @abstractmethod
    def supports(
        self,
        context: ReliabilityContext,
    ) -> bool: ...

    @abstractmethod
    def apply(
        self,
        context: ReliabilityContext,
        policy: ReliabilityPolicy,
    ) -> ReliabilityResult: ...

    @abstractmethod
    def reset(self) -> None: ...
