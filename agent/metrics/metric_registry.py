# ============================================================
# Metric Registry — Central registration for all metric implementations
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new metrics without modifying Factory
# 2. Plugin architecture: Metrics can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
# 4. Definition index: Engine can query MetricType / unit / description
#    without instantiating the Metric
#
# Mirrors:
#   MetricRegistry ↔ ToolRegistry
#   MetricRegistry ↔ MemoryRegistry
#   MetricRegistry ↔ TraceRegistry
# ============================================================

from typing import Dict, List, Optional, Type

from .base_metric import BaseMetric
from .metric_exceptions import MetricNotFound, MetricRegistrationError
from .metric_models import MetricDefinition


class MetricRegistry:
    _registry: Dict[str, Type[BaseMetric]] = {}
    _definitions: Dict[str, MetricDefinition] = {}

    # ============================================================
    # Register
    # ============================================================

    @classmethod
    def register(
        cls,
        name: str,
        metric_cls: Type[BaseMetric],
        definition: Optional[MetricDefinition] = None,
    ) -> None:
        if not issubclass(metric_cls, BaseMetric):
            raise MetricRegistrationError(f"'{metric_cls.__name__}' must be a subclass of BaseMetric")
        if name in cls._registry:
            raise MetricRegistrationError(f"Metric '{name}' is already registered")
        cls._registry[name] = metric_cls
        if definition is not None:
            cls._definitions[name] = definition

    # ============================================================
    # Query
    # ============================================================

    @classmethod
    def get(cls, name: str) -> Type[BaseMetric]:
        if not cls.has_metric(name):
            raise MetricNotFound(f"Metric '{name}' not registered. Available: {cls.list_metrics()}")
        return cls._registry[name]

    @classmethod
    def get_definition(cls, name: str) -> MetricDefinition:
        if name not in cls._definitions:
            raise MetricNotFound(
                f"Definition for metric '{name}' not found. Available definitions: {list(cls._definitions.keys())}"
            )
        return cls._definitions[name]

    @classmethod
    def has_metric(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def list_metrics(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
        cls._definitions.clear()
