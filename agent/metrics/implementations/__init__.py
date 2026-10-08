# ============================================================
# Implementations — Auto-registration
# ============================================================
# All metric implementations are registered here on import.
# Add new metric classes here and they become available
# through MetricFactory without any code changes.
# ============================================================

from agent.metrics.metric_enums import MetricType
from agent.metrics.metric_models import MetricDefinition
from agent.metrics.metric_registry import MetricRegistry

from .counter_metric import CounterMetric
from .histogram_metric import HistogramMetric
from .timer_metric import TimerMetric

MetricRegistry.register(
    "counter",
    CounterMetric,
    MetricDefinition(
        name="counter",
        metric_type=MetricType.COUNTER,
        description="Cumulative count of events",
        unit="count",
    ),
)
MetricRegistry.register(
    "timer",
    TimerMetric,
    MetricDefinition(
        name="timer",
        metric_type=MetricType.TIMER,
        description="Latency measurement",
        unit="ms",
    ),
)
MetricRegistry.register(
    "histogram",
    HistogramMetric,
    MetricDefinition(
        name="histogram",
        metric_type=MetricType.HISTOGRAM,
        description="Value distribution",
        unit="unit",
    ),
)
