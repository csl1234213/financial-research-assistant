# ============================================================
# CounterMetric — Tracks cumulative counts
# ============================================================
# Skeleton implementation. Collects individual MetricRecord
# entries and returns total count on collect().
#
# Usage:
#   counter = CounterMetric()
#   counter.record(ctx, MetricRecord(name="tool_calls_total", ...))
#   counter.record(ctx, MetricRecord(name="tool_calls_total", ...))
#   result = counter.collect()  # count=2
# ============================================================

from agent.metrics.base_metric import BaseMetric
from agent.metrics.metric_context import MetricContext
from agent.metrics.metric_models import MetricRecord
from agent.metrics.metric_result import MetricResult


class CounterMetric(BaseMetric):
    def __init__(self) -> None:
        self._records: list[MetricRecord] = []
        self._count: float = 0.0

    @property
    def metric_name(self) -> str:
        return "counter"

    def record(
        self,
        context: MetricContext,
        record: MetricRecord,
    ) -> None:
        self._records.append(record)
        self._count += record.value

    def collect(self) -> MetricResult:
        return MetricResult(
            records=list(self._records),
            count=len(self._records),
            success=True,
        )
