# ============================================================
# Metrics
# ============================================================
# Unified exports for the Metrics Layer.
# ============================================================

from .base_metric import BaseMetric

# Auto-register built-in metrics
from .implementations import (  # noqa: F401
    CounterMetric,
    HistogramMetric,
    TimerMetric,
)
from .metric_bridge import MetricBridge
from .metric_collector import MetricCollector
from .metric_context import MetricContext
from .metric_engine import MetricEngine
from .metric_enums import MetricScope, MetricStatus, MetricType
from .metric_events import MetricEvent
from .metric_exceptions import MetricError, MetricNotFound, MetricRegistrationError
from .metric_factory import MetricFactory
from .metric_models import MetricDefinition, MetricRecord
from .metric_registry import MetricRegistry
from .metric_result import MetricResult

__all__ = [
    "BaseMetric",
    "CounterMetric",
    "HistogramMetric",
    "MetricBridge",
    "MetricCollector",
    "MetricContext",
    "MetricDefinition",
    "MetricEngine",
    "MetricError",
    "MetricEvent",
    "MetricFactory",
    "MetricNotFound",
    "MetricRecord",
    "MetricRegistrationError",
    "MetricRegistry",
    "MetricResult",
    "MetricScope",
    "MetricStatus",
    "MetricType",
    "TimerMetric",
]
