# ============================================================
# Tracing
# ============================================================
# Unified exports for the Tracing Layer.
# ============================================================

from .base_tracer import BaseTracer
from .trace_context import TraceContext
from .trace_engine import TraceEngine
from .trace_enums import TraceLevel, TraceStatus, TraceType
from .trace_exceptions import TraceError, TracerNotFound, TracerRegistrationError
from .trace_factory import TraceFactory
from .trace_models import TraceEvent, TraceSpan
from .trace_registry import TraceRegistry, TracerMetadata
from .trace_result import TraceResult
from .tracer_enums import TracerType

# Auto-register built-in tracers
from .tracers import (  # noqa: F401
    ConsoleTracer,
    FileTracer,
    MemoryTracer,
)

__all__ = [
    "BaseTracer",
    "ConsoleTracer",
    "FileTracer",
    "MemoryTracer",
    "TraceContext",
    "TraceEngine",
    "TraceError",
    "TraceEvent",
    "TraceFactory",
    "TraceLevel",
    "TraceRegistry",
    "TraceResult",
    "TraceSpan",
    "TraceStatus",
    "TraceType",
    "TracerMetadata",
    "TracerNotFound",
    "TracerRegistrationError",
    "TracerType",
]
