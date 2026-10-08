# ============================================================
# HistogramMetric — Tracks value distributions
# ============================================================
# Skeleton implementation. Collects individual MetricRecord
# entries for distribution analysis (e.g., token_usage, response_size).
# Aggregation (p50, p95, p99) will be implemented in Sprint 3.
#
# Usage:
#   histogram = HistogramMetric()
#   histogram.record(ctx, MetricRecord(name="token_usage", value=1024, ...))
#   result = histogram.collect()
# ============================================================

from agent.metrics.base_metric import BaseMetric
from agent.metrics.metric_context import MetricContext
from agent.metrics.metric_models import MetricRecord
from agent.metrics.metric_result import MetricResult


class HistogramMetric(BaseMetric):
    def __init__(self) -> None:
        self._records: list[MetricRecord] = []

    @property
    def metric_name(self) -> str:
        return "histogram"

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
