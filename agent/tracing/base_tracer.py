# ============================================================
# BaseTracer — Abstract interface for all tracer implementations
# ============================================================
# 每一个具体 Tracer（ConsoleTracer、MemoryTracer、
# FileTracer、OpenTelemetryTracer 等）都必须实现这个接口。
#
# 设计原则：
#   - Tracer 不负责决定「要不要 trace」— 由 Engine 决定
#   - Tracer 只负责 start_span / end_span / record_event
#   - 不包含 Export / Runtime 依赖
#   - 不包含 Registry / Factory 逻辑
#
# Mirrors:
#   BaseMemory              ↔ BaseTracer
#   BaseExecutionStrategy   ↔ BaseTracer
#   BaseTool                ↔ BaseTracer
#   BaseProvider            ↔ BaseTracer
# ============================================================

from abc import ABC, abstractmethod
from typing import Optional

from .trace_context import TraceContext
from .trace_enums import TraceLevel, TraceStatus, TraceType
from .trace_models import TraceEvent, TraceSpan
from .trace_result import TraceResult


class BaseTracer(ABC):
    @property
    @abstractmethod
    def tracer_name(self) -> str: ...

    @abstractmethod
    def supports(
        self,
        context: TraceContext,
    ) -> bool: ...

    @abstractmethod
    def start_span(
        self,
        name: str,
        trace_type: TraceType,
        context: TraceContext,
        parent_id: Optional[str] = None,
    ) -> TraceSpan: ...

    @abstractmethod
    def end_span(
        self,
        span: TraceSpan,
        status: TraceStatus = TraceStatus.SUCCESS,
    ) -> None: ...

    @abstractmethod
    def record_event(
        self,
        message: str,
        level: TraceLevel = TraceLevel.INFO,
        metadata: Optional[dict] = None,
    ) -> TraceEvent: ...

    @abstractmethod
    def flush(self) -> TraceResult: ...
