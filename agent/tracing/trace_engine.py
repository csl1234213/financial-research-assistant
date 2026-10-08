# ============================================================
# TraceEngine — Tracing Layer Orchestrator
# ============================================================
# The TraceEngine is the single entry point for the
# Tracing Layer. It receives a TraceContext, creates the
# appropriate Tracer instance via Factory, and delegates
# span/event operations to that instance.
#
# The Engine does NOT make business decisions.
# It does NOT know about:
#   - Which tracer to use (determined by caller or context)
#   - Console / File / OpenTelemetry / Jaeger internals
#   - Export / Format / Serialization
#   - Provider / Runtime / Workflow
#
# It ONLY orchestrates:
#   Context → Factory → Tracer.start_span() / end_span() / record_event() → Result
#
# Key features:
#   - Nested Span support (span stack with automatic parent_id)
#   - Hook system (before_trace / after_trace)
#   - Context manager (`with engine.span(...)`) support
#
# Mirrors:
#   agent.memory.MemoryEngine      → TraceEngine
#   agent.tools.ToolEngine         → TraceEngine
#   agent.workflow.WorkflowEngine  → TraceEngine
# ============================================================

import logging
from contextlib import contextmanager
from typing import Callable, List, Optional, Union

from .base_tracer import BaseTracer
from .trace_context import TraceContext
from .trace_enums import TraceLevel, TraceStatus, TraceType
from .trace_factory import TraceFactory
from .trace_models import TraceEvent, TraceSpan
from .trace_result import TraceResult
from .tracer_enums import TracerType

logger = logging.getLogger(__name__)


class TraceEngine:
    def __init__(self) -> None:
        self._default_tracer_type: Union[str, TracerType] = TracerType.CONSOLE
        self._tracer: Optional[BaseTracer] = None
        self._span_stack: List[TraceSpan] = []
        self._context: Optional[TraceContext] = None
        self._started: bool = False

        self._before_trace_hooks: List[Callable[[TraceContext], None]] = []
        self._after_trace_hooks: List[Callable[[TraceResult], None]] = []

    # ============================================================
    # Default tracer type
    # ============================================================

    def set_default_tracer_type(self, tracer_type: Union[str, TracerType]) -> None:
        if isinstance(tracer_type, str):
            tracer_type = TracerType(tracer_type)
        self._default_tracer_type = tracer_type

    # ============================================================
    # Hooks
    # ============================================================

    def add_before_trace_hook(self, hook: Callable[[TraceContext], None]) -> None:
        self._before_trace_hooks.append(hook)

    def add_after_trace_hook(self, hook: Callable[[TraceResult], None]) -> None:
        self._after_trace_hooks.append(hook)

    def _run_before_hooks(self, context: TraceContext) -> None:
        for hook in self._before_trace_hooks:
            try:
                hook(context)
            except Exception:
                pass

    def _run_after_hooks(self, result: TraceResult) -> None:
        for hook in self._after_trace_hooks:
            try:
                hook(result)
            except Exception:
                pass

    # ============================================================
    # Lifecycle
    # ============================================================

    def start_trace(
        self,
        context: TraceContext,
        tracer_type: Optional[Union[str, TracerType]] = None,
    ) -> "TraceEngine":
        self._run_before_hooks(context)

        if tracer_type is None:
            tracer_type = self._default_tracer_type

        self._tracer = TraceFactory.create(tracer_type)
        self._context = context
        self._span_stack.clear()
        self._started = True

        logger.info(
            "TraceEngine: started with tracer=%s",
            self._tracer.tracer_name,
        )
        return self

    def finish_trace(self) -> TraceResult:
        if self._tracer is None:
            return TraceResult()

        while self._span_stack:
            span = self._span_stack.pop()
            self._tracer.end_span(span)

        result = self._tracer.flush()
        self._started = False
        self._run_after_hooks(result)

        logger.info(
            "TraceEngine: finished spans=%d events=%d duration=%.2fms",
            len(result.spans),
            len(result.events),
            result.duration_ms,
        )
        return result

    # ============================================================
    # Span operations
    # ============================================================

    def start_span(
        self,
        name: str,
        trace_type: TraceType,
        metadata: Optional[dict] = None,
    ) -> TraceSpan:
        if self._tracer is None or self._context is None:
            raise RuntimeError("TraceEngine not started. Call start_trace() first.")

        parent_id = self._span_stack[-1].id if self._span_stack else None

        span = self._tracer.start_span(
            name=name,
            trace_type=trace_type,
            context=self._context,
            parent_id=parent_id,
        )
        if metadata:
            span.metadata.update(metadata)

        self._span_stack.append(span)
        return span

    def end_span(
        self,
        status: TraceStatus = TraceStatus.SUCCESS,
    ) -> Optional[TraceSpan]:
        if not self._span_stack:
            return None

        span = self._span_stack.pop()
        if self._tracer is not None:
            self._tracer.end_span(span, status)
        return span

    def record_event(
        self,
        message: str,
        level: TraceLevel = TraceLevel.INFO,
        metadata: Optional[dict] = None,
    ) -> Optional[TraceEvent]:
        if self._tracer is None:
            return None
        return self._tracer.record_event(message, level, metadata)

    # ============================================================
    # Context manager
    # ============================================================

    @contextmanager
    def span(
        self,
        name: str,
        trace_type: TraceType,
        metadata: Optional[dict] = None,
    ):
        span = self.start_span(name, trace_type, metadata)
        try:
            yield span
            self.end_span(TraceStatus.SUCCESS)
        except Exception:
            self.end_span(TraceStatus.FAILED)
            raise

    # ============================================================
    # Convenience: one-shot trace
    # ============================================================

    def trace(
        self,
        context: TraceContext,
        tracer_type: Optional[Union[str, TracerType]] = None,
    ) -> TraceResult:
        self.start_trace(context, tracer_type)
        return self.finish_trace()

    # ============================================================
    # Query
    # ============================================================

    @property
    def current_span(self) -> Optional[TraceSpan]:
        return self._span_stack[-1] if self._span_stack else None

    @property
    def span_depth(self) -> int:
        return len(self._span_stack)

    @property
    def tracer_name(self) -> Optional[str]:
        return self._tracer.tracer_name if self._tracer else None
