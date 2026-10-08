# ============================================================
# MetricEngine — Metrics Layer Orchestrator
# ============================================================
# The MetricEngine is the single entry point for the
# Metrics Layer. It receives a MetricContext, creates the
# appropriate Metric instance via Factory, and delegates
# record / increment / observe / collect to that instance.
#
# The Engine does NOT make business decisions.
# It does NOT know about:
#   - Which metric to use (determined by caller or context)
#   - Counter / Timer / Histogram internals
#   - Export / Storage / Database / Prometheus
#   - Provider / Runtime / Workflow
#
# It ONLY orchestrates:
#   Context → Factory → Metric.record() / Metric.collect() → Result
#
# Key features:
#   - Multi-metric support: lazily creates metric instances per type
#   - Convenience API: increment() / observe()
#   - Hook system: before_record / after_record / before_collect / after_collect
#
# Mirrors:
#   agent.memory.MemoryEngine      → MetricEngine
#   agent.tools.ToolEngine         → MetricEngine
#   agent.tracing.TraceEngine      → MetricEngine
# ============================================================

import logging
import time
from typing import Callable, Dict, List, Optional, Union

from .base_metric import BaseMetric
from .metric_context import MetricContext
from .metric_enums import MetricScope, MetricType
from .metric_factory import MetricFactory
from .metric_models import MetricRecord
from .metric_result import MetricResult

logger = logging.getLogger(__name__)


class MetricEngine:
    def __init__(self) -> None:
        self._default_metric_type: Union[str, MetricType] = MetricType.TIMER
        self._instances: Dict[str, BaseMetric] = {}
        self._default_scope: MetricScope = MetricScope.RUNTIME

        self._before_record_hooks: List[Callable[[MetricContext, MetricRecord], None]] = []
        self._after_record_hooks: List[Callable[[MetricContext, MetricRecord], None]] = []
        self._before_collect_hooks: List[Callable[[MetricContext], None]] = []
        self._after_collect_hooks: List[Callable[[MetricResult], None]] = []

    # ============================================================
    # Configuration
    # ============================================================

    def set_default_metric_type(self, metric_type: Union[str, MetricType]) -> None:
        if isinstance(metric_type, str):
            metric_type = MetricType(metric_type)
        self._default_metric_type = metric_type

    def set_default_scope(self, scope: MetricScope) -> None:
        self._default_scope = scope

    # ============================================================
    # Hooks
    # ============================================================

    def add_before_record_hook(
        self,
        hook: Callable[[MetricContext, MetricRecord], None],
    ) -> None:
        self._before_record_hooks.append(hook)

    def add_after_record_hook(
        self,
        hook: Callable[[MetricContext, MetricRecord], None],
    ) -> None:
        self._after_record_hooks.append(hook)

    def add_before_collect_hook(
        self,
        hook: Callable[[MetricContext], None],
    ) -> None:
        self._before_collect_hooks.append(hook)

    def add_after_collect_hook(
        self,
        hook: Callable[[MetricResult], None],
    ) -> None:
        self._after_collect_hooks.append(hook)

    def _run_before_record_hooks(
        self,
        context: MetricContext,
        record: MetricRecord,
    ) -> None:
        for hook in self._before_record_hooks:
            try:
                hook(context, record)
            except Exception:
                pass

    def _run_after_record_hooks(
        self,
        context: MetricContext,
        record: MetricRecord,
    ) -> None:
        for hook in self._after_record_hooks:
            try:
                hook(context, record)
            except Exception:
                pass

    def _run_before_collect_hooks(self, context: MetricContext) -> None:
        for hook in self._before_collect_hooks:
            try:
                hook(context)
            except Exception:
                pass

    def _run_after_collect_hooks(self, result: MetricResult) -> None:
        for hook in self._after_collect_hooks:
            try:
                hook(result)
            except Exception:
                pass

    # ============================================================
    # Internal: resolve metric instance
    # ============================================================

    def _resolve_metric(self, metric_type: Union[str, MetricType]) -> BaseMetric:
        if isinstance(metric_type, MetricType):
            key = metric_type.value
        else:
            key = metric_type

        if key not in self._instances:
            self._instances[key] = MetricFactory.create(key)
        return self._instances[key]

    # ============================================================
    # Record
    # ============================================================

    def record(
        self,
        context: MetricContext,
        record: MetricRecord,
    ) -> None:
        self._run_before_record_hooks(context, record)

        metric = self._resolve_metric(record.metric_type)
        metric.record(context, record)

        self._run_after_record_hooks(context, record)

        logger.debug(
            "MetricEngine: recorded %s=%s type=%s scope=%s",
            record.name,
            record.value,
            record.metric_type.value,
            record.scope.value,
        )

    # ============================================================
    # Convenience: increment (Counter)
    # ============================================================

    def increment(
        self,
        context: MetricContext,
        name: str,
        value: float = 1.0,
        scope: Optional[MetricScope] = None,
        labels: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        record = MetricRecord(
            name=name,
            metric_type=MetricType.COUNTER,
            value=value,
            scope=scope or self._default_scope,
            timestamp=time.time(),
            labels=labels or {},
            metadata=metadata or {},
        )
        self.record(context, record)

    # ============================================================
    # Convenience: observe (Timer / Histogram)
    # ============================================================

    def observe(
        self,
        context: MetricContext,
        name: str,
        value: float,
        metric_type: MetricType = MetricType.TIMER,
        scope: Optional[MetricScope] = None,
        labels: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        record = MetricRecord(
            name=name,
            metric_type=metric_type,
            value=value,
            scope=scope or self._default_scope,
            timestamp=time.time(),
            labels=labels or {},
            metadata=metadata or {},
        )
        self.record(context, record)

    # ============================================================
    # Collect
    # ============================================================

    def collect(
        self,
        context: Optional[MetricContext] = None,
    ) -> MetricResult:
        if context is not None:
            self._run_before_collect_hooks(context)

        all_records: List[MetricRecord] = []
        for instance in self._instances.values():
            result = instance.collect()
            all_records.extend(result.records)

        final_result = MetricResult(
            records=all_records,
            count=len(all_records),
            success=True,
        )

        if context is not None:
            self._run_after_collect_hooks(final_result)

        logger.info(
            "MetricEngine: collected %d records",
            final_result.count,
        )
        return final_result

    # ============================================================
    # Query
    # ============================================================

    @property
    def instance_count(self) -> int:
        return len(self._instances)

    @property
    def active_metric_types(self) -> List[str]:
        return list(self._instances.keys())
