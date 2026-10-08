# ============================================================
# MemoryTracer — Stores trace output in memory
# ============================================================
# Skeleton implementation. Collects spans and events in memory
# for testing, debugging, and programmatic inspection.
# In Sprint 2, this will be extended with max_span_count
# limits and circular buffer behavior.
# ============================================================

import uuid
from typing import Optional

from agent.tracing.base_tracer import BaseTracer
from agent.tracing.trace_context import TraceContext
from agent.tracing.trace_enums import TraceLevel, TraceStatus, TraceType
from agent.tracing.trace_models import TraceEvent, TraceSpan
from agent.tracing.trace_result import TraceResult


class MemoryTracer(BaseTracer):
    def __init__(self) -> None:
        self._spans: list[TraceSpan] = []
        self._events: list[TraceEvent] = []

    @property
    def tracer_name(self) -> str:
        return "memory"

    def supports(self, context: TraceContext) -> bool:
        return True

    def start_span(
        self,
        name: str,
        trace_type: TraceType,
        context: TraceContext,
        parent_id: Optional[str] = None,
    ) -> TraceSpan:
        span = TraceSpan(
            id=str(uuid.uuid4()),
            trace_type=trace_type,
            name=name,
            parent_id=parent_id,
            status=TraceStatus.STARTED,
        )
        self._spans.append(span)
        return span

    def end_span(
        self,
        span: TraceSpan,
        status: TraceStatus = TraceStatus.SUCCESS,
    ) -> None:
        span.status = status
        span.end_time = span.start_time
        if span.start_time and span.end_time:
            span.duration_ms = (span.end_time - span.start_time).total_seconds() * 1000

    def record_event(
        self,
        message: str,
        level: TraceLevel = TraceLevel.INFO,
        metadata: Optional[dict] = None,
    ) -> TraceEvent:
        event = TraceEvent(
            level=level,
            message=message,
            metadata=metadata or {},
        )
        self._events.append(event)
        return event

    def flush(self) -> TraceResult:
        return TraceResult(
            spans=list(self._spans),
            events=list(self._events),
            duration_ms=sum(s.duration_ms for s in self._spans),
            success=all(s.status != TraceStatus.FAILED for s in self._spans),
        )
