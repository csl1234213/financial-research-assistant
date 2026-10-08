# ============================================================
# Metric Factory — Creates metric instances by name or type
# ============================================================
# The Factory only knows how to create, not which metrics exist.
# That knowledge lives in the Registry.
#
# Usage:
#   metric = MetricFactory.create("timer")
#   metric = MetricFactory.create(MetricType.TIMER)
#   result = metric.collect()
#
# Mirrors:
#   MetricFactory ↔ ToolFactory
#   MetricFactory ↔ MemoryFactory
#   MetricFactory ↔ TraceFactory
# ============================================================

from typing import Optional, Union

from .base_metric import BaseMetric
from .metric_enums import MetricType
from .metric_registry import MetricRegistry


class MetricFactory:
    _default_metric: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, name: Union[str, MetricType]) -> BaseMetric:
        if isinstance(name, MetricType):
            name = name.value
        metric_cls = MetricRegistry.get(name)
        return metric_cls()

    # ============================================================
    # Default metric
    # ============================================================

    @classmethod
    def set_default(cls, name: Union[str, MetricType]) -> None:
        if isinstance(name, MetricType):
            name = name.value
        if not MetricRegistry.has_metric(name):
            raise KeyError(f"Cannot set default. Metric '{name}' not registered.")
        cls._default_metric = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_metric

    @classmethod
    def create_default(cls) -> BaseMetric:
        if cls._default_metric is None:
            # Default to timer since latency is the most critical metric
            cls.set_default(MetricType.TIMER)
        return cls.create(cls._default_metric)
