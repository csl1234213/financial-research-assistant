# ============================================================
# Metric Events — Unified event model for auto-collection
# ============================================================
# MetricEvent represents a single metric measurement that
# any module (Workflow, Execution, Tool, Provider, Memory)
# can emit. The MetricCollector converts MetricEvent to
# MetricRecord and records it via MetricEngine.
#
# Why MetricEvent?
#   - Decouples modules from the Metrics API
#   - Modules don't need to import MetricEngine directly
#   - Central aggregation → all events go through one collector
#   - Consistent data model across all modules
#
# Example usage:
#   event = MetricEvent(
#       name="tool_latency",
#       scope=MetricScope.TOOL,
#       metric_type=MetricType.TIMER,
#       value=120.0,
#       labels={"tool": "retrieval"},
#   )
#   collector.emit(event)
# ============================================================

from dataclasses import dataclass
from typing import Dict, Optional

from .metric_enums import MetricScope, MetricType


@dataclass(slots=True)
class MetricEvent:
    name: str
    scope: MetricScope
    metric_type: MetricType
    value: float
    labels: Dict[str, str] = None
    timestamp: Optional[float] = None

    def __post_init__(self) -> None:
        if self.labels is None:
            self.labels = {}
