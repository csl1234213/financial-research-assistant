# ============================================================
# Tracers — Auto-registration
# ============================================================
# All tracers are registered here on import.
# Add new tracer classes here and they become available
# through TraceFactory without any code changes.
# ============================================================

from agent.tracing.trace_registry import TraceRegistry, TracerMetadata

from .console_tracer import ConsoleTracer
from .file_tracer import FileTracer
from .memory_tracer import MemoryTracer

TraceRegistry.register(
    "console",
    ConsoleTracer,
    TracerMetadata(
        name="console",
        supports_stream=True,
        supports_async=False,
        persistent=False,
    ),
)
TraceRegistry.register(
    "memory",
    MemoryTracer,
    TracerMetadata(
        name="memory",
        supports_stream=False,
        supports_async=False,
        persistent=False,
    ),
)
TraceRegistry.register(
    "file",
    FileTracer,
    TracerMetadata(
        name="file",
        supports_stream=True,
        supports_async=False,
        persistent=True,
    ),
)
