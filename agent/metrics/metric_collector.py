# ============================================================
# MetricCollector — MetricEvent → MetricEngine
# ============================================================
# The MetricCollector is the central event-to-metric converter.
# Any module emits a MetricEvent, and the collector:
#   1. Converts MetricEvent → MetricRecord
#   2. Delegates to MetricEngine.record()
#
# The collector does NOT know about:
#   - Which metric type to use → determined by MetricEvent
#   - Storage / Export / DB → handled by MetricEngine
#   - Runtime / Workflow / Tool internals
#
# It ONLY converts:
#   MetricEvent → MetricRecord → MetricEngine
#
# Usage:
#   collector = MetricCollector(MetricEngine())
#   collector.emit(MetricEvent(name="tool_latency", ...))
#   result = collector.collect()
# ============================================================

import logging
import time
from typing import Dict, List, Optional

from .metric_context import MetricContext
from .metric_engine import MetricEngine
from .metric_enums import MetricScope, MetricType
from .metric_events import MetricEvent
from .metric_models import MetricRecord
from .metric_result import MetricResult

logger = logging.getLogger(__name__)


class MetricCollector:
    def __init__(self, engine: MetricEngine) -> None:
        self._engine = engine
        self._events: List[MetricEvent] = []

    # ============================================================
    # Emit
    # ============================================================

    def emit(self, event: MetricEvent) -> None:
        self._events.append(event)

        record = MetricRecord(
            name=event.name,
            metric_type=event.metric_type,
            value=event.value,
            scope=event.scope,
            timestamp=event.timestamp or time.time(),
            labels=dict(event.labels),
        )

        ctx = MetricContext()
        self._engine.record(ctx, record)

        logger.debug(
            "MetricCollector: %s=%s type=%s scope=%s labels=%s",
            event.name,
            event.value,
            event.metric_type.value,
            event.scope.value,
            event.labels,
        )

    def emit_batch(self, events: List[MetricEvent]) -> None:
        for event in events:
            self.emit(event)

    # ============================================================
    # Convenience: direct emit helpers
    # ============================================================

    def emit_counter(
        self,
        name: str,
        scope: MetricScope,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        self.emit(
            MetricEvent(
                name=name,
                scope=scope,
                metric_type=MetricType.COUNTER,
                value=value,
                labels=labels or {},
            )
        )

    def emit_timer(
        self,
        name: str,
        scope: MetricScope,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        self.emit(
            MetricEvent(
                name=name,
                scope=scope,
                metric_type=MetricType.TIMER,
                value=value,
                labels=labels or {},
            )
        )

    def emit_histogram(
        self,
        name: str,
        scope: MetricScope,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        self.emit(
            MetricEvent(
                name=name,
                scope=scope,
                metric_type=MetricType.HISTOGRAM,
                value=value,
                labels=labels or {},
            )
        )

    # ============================================================
    # Collect
    # ============================================================

    def collect(self) -> MetricResult:
        return self._engine.collect()

    # ============================================================
    # Query
    # ============================================================

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def engine(self) -> MetricEngine:
        return self._engine
