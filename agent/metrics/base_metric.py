# ============================================================
# BaseMetric — Abstract interface for all metric implementations
# ============================================================
# 每一个具体 Metric（CounterMetric、GaugeMetric、
# HistogramMetric、TimerMetric 等）都必须实现这个接口。
#
# 设计原则：
#   - Metric 不负责决定「要不要采集」— 由 Engine 决定
#   - Metric 只负责 record / collect
#   - 不包含 Export / Runtime 依赖
#   - 不包含 Registry / Factory 逻辑
#
# Mirrors:
#   BaseMetric      ↔ BaseTracer
#   BaseMetric      ↔ BaseTool
#   BaseMetric      ↔ BaseMemory
#   BaseMetric      ↔ BaseProvider
# ============================================================

from abc import ABC, abstractmethod

from .metric_context import MetricContext
from .metric_models import MetricRecord
from .metric_result import MetricResult


class BaseMetric(ABC):
    @property
    @abstractmethod
    def metric_name(self) -> str: ...

    @abstractmethod
    def record(
        self,
        context: MetricContext,
        record: MetricRecord,
    ) -> None: ...

    @abstractmethod
    def collect(self) -> MetricResult: ...
