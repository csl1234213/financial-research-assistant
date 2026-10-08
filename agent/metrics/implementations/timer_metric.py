# ============================================================
# TimerMetric — Tracks timing / latency measurements
# ============================================================
# Skeleton implementation. Collects individual MetricRecord
# entries for latency/duration measurements.
#
# Usage:
#   timer = TimerMetric()
#   timer.record(ctx, MetricRecord(name="provider_latency", value=320, ...))
#   result = timer.collect()
# ============================================================

from agent.metrics.base_metric import BaseMetric
from agent.metrics.metric_context import MetricContext
from agent.metrics.metric_models import MetricRecord
from agent.metrics.metric_result import MetricResult


class TimerMetric(BaseMetric):
    def __init__(self) -> None:
        self._records: list[MetricRecord] = []

    @property
    def metric_name(self) -> str:
        return "timer"

    def record(
        self,
        context: MetricContext,
        record: MetricRecord,
    ) -> None:
        self._records.append(record)

    def collect(self) -> MetricResult:
        return MetricResult(
            records=list(self._records),
            count=len(self._records),
            success=True,
        )
