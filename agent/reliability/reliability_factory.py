# ============================================================
# Reliability Factory — Creates reliability instances by name or type
# ============================================================
# The Factory only knows how to create, not which mechanisms exist.
# That knowledge lives in the Registry.
#
# Usage:
#   mechanism = ReliabilityFactory.create("retry")
#   mechanism = ReliabilityFactory.create(ReliabilityType.RETRY)
#   result = mechanism.apply(context, policy)
#
# Mirrors:
#   ReliabilityFactory ↔ MetricFactory ↔ TraceFactory
#   ReliabilityFactory ↔ ToolFactory ↔ MemoryFactory
# ============================================================

from typing import Optional, Union

from .base_reliability import BaseReliability
from .reliability_enums import ReliabilityType
from .reliability_registry import ReliabilityRegistry


class ReliabilityFactory:
    _default_mechanism: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, name: Union[str, ReliabilityType]) -> BaseReliability:
        if isinstance(name, ReliabilityType):
            name = name.value
        mechanism_cls = ReliabilityRegistry.get(name)
        return mechanism_cls()

    # ============================================================
    # Default mechanism
    # ============================================================

    @classmethod
    def set_default(cls, name: Union[str, ReliabilityType]) -> None:
        if isinstance(name, ReliabilityType):
            name = name.value
        if not ReliabilityRegistry.has_mechanism(name):
            raise KeyError(f"Cannot set default. Reliability mechanism '{name}' not registered.")
        cls._default_mechanism = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_mechanism

    @classmethod
    def create_default(cls) -> BaseReliability:
        if cls._default_mechanism is None:
            # Default to Retry since it's the most fundamental
            # and commonly used reliability mechanism
            cls.set_default(ReliabilityType.RETRY)
        return cls.create(cls._default_mechanism)
