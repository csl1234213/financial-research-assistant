# ============================================================
# Trace Registry — Central registration for all tracer implementations
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new tracers without modifying Factory
# 2. Plugin architecture: Tracers can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
# 4. Metadata index: Engine can query TracerType / capabilities
#    without instantiating the Tracer
#
# Mirrors:
#   TraceRegistry ↔ ToolRegistry
#   TraceRegistry ↔ MemoryRegistry
#   TraceRegistry ↔ WorkflowRegistry
#   TraceRegistry ↔ StrategyRegistry
# ============================================================

from dataclasses import dataclass
from typing import Dict, List, Optional, Type

from .base_tracer import BaseTracer
from .trace_exceptions import TracerNotFound, TracerRegistrationError


@dataclass(slots=True)
class TracerMetadata:
    name: str
    supports_stream: bool = False
    supports_async: bool = False
    persistent: bool = False


class TraceRegistry:
    _registry: Dict[str, Type[BaseTracer]] = {}
    _metadata: Dict[str, TracerMetadata] = {}

    # ============================================================
    # Register
    # ============================================================

    @classmethod
    def register(
        cls,
        name: str,
        tracer_cls: Type[BaseTracer],
        metadata: Optional[TracerMetadata] = None,
    ) -> None:
        if not issubclass(tracer_cls, BaseTracer):
            raise TracerRegistrationError(f"'{tracer_cls.__name__}' must be a subclass of BaseTracer")
        if name in cls._registry:
            raise TracerRegistrationError(f"Tracer '{name}' is already registered")
        cls._registry[name] = tracer_cls
        if metadata is not None:
            cls._metadata[name] = metadata

    # ============================================================
    # Query
    # ============================================================

    @classmethod
    def get(cls, name: str) -> Type[BaseTracer]:
        if not cls.has_tracer(name):
            raise TracerNotFound(f"Tracer '{name}' not registered. Available: {cls.list_tracers()}")
        return cls._registry[name]

    @classmethod
    def get_metadata(cls, name: str) -> TracerMetadata:
        if name not in cls._metadata:
            raise TracerNotFound(
                f"Metadata for tracer '{name}' not found. Available metadata: {list(cls._metadata.keys())}"
            )
        return cls._metadata[name]

    @classmethod
    def has_tracer(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def list_tracers(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
        cls._metadata.clear()
