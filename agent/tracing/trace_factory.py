# ============================================================
# Trace Factory — Creates tracer instances by name or type
# ============================================================
# The Factory only knows how to create, not which tracers exist.
# That knowledge lives in the Registry.
#
# Usage:
#   tracer = TraceFactory.create("console")
#   tracer = TraceFactory.create(TracerType.CONSOLE)
#   result = tracer.flush()
#
# Mirrors:
#   TraceFactory ↔ ToolFactory
#   TraceFactory ↔ MemoryFactory
#   TraceFactory ↔ WorkflowFactory
# ============================================================

from typing import Optional, Union

from .base_tracer import BaseTracer
from .trace_registry import TraceRegistry
from .tracer_enums import TracerType


class TraceFactory:
    _default_tracer: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, name: Union[str, TracerType]) -> BaseTracer:
        if isinstance(name, TracerType):
            name = name.value
        tracer_cls = TraceRegistry.get(name)
        return tracer_cls()

    # ============================================================
    # Default tracer
    # ============================================================

    @classmethod
    def set_default(cls, name: Union[str, TracerType]) -> None:
        if isinstance(name, TracerType):
            name = name.value
        if not TraceRegistry.has_tracer(name):
            raise KeyError(f"Cannot set default. Tracer '{name}' not registered.")
        cls._default_tracer = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_tracer

    @classmethod
    def create_default(cls) -> BaseTracer:
        if cls._default_tracer is None:
            raise RuntimeError("No default tracer set. Call TraceFactory.set_default(...) first.")
        return cls.create(cls._default_tracer)
