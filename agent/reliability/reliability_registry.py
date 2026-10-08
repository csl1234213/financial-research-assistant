# ============================================================
# Reliability Registry — Central registration for all reliability implementations
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new mechanisms without modifying Factory
# 2. Plugin architecture: Mechanisms can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
# 4. Policy metadata: Engine can query mechanism capabilities
#    without instantiating the mechanism
#
# Mirrors:
#   ReliabilityRegistry ↔ MetricRegistry ↔ TraceRegistry
#   ReliabilityRegistry ↔ ToolRegistry ↔ MemoryRegistry
# ============================================================

from typing import Dict, List, Optional, Type

from .base_reliability import BaseReliability
from .reliability_exceptions import ReliabilityNotFound, ReliabilityRegistrationError
from .reliability_models import ReliabilityPolicy


class ReliabilityRegistry:
    _registry: Dict[str, Type[BaseReliability]] = {}
    _policies: Dict[str, ReliabilityPolicy] = {}

    # ============================================================
    # Register
    # ============================================================

    @classmethod
    def register(
        cls,
        name: str,
        mechanism_cls: Type[BaseReliability],
        default_policy: Optional[ReliabilityPolicy] = None,
    ) -> None:
        if not issubclass(mechanism_cls, BaseReliability):
            raise ReliabilityRegistrationError(f"'{mechanism_cls.__name__}' must be a subclass of BaseReliability")
        if name in cls._registry:
            raise ReliabilityRegistrationError(f"Reliability mechanism '{name}' is already registered")
        cls._registry[name] = mechanism_cls
        if default_policy is not None:
            cls._policies[name] = default_policy

    # ============================================================
    # Query
    # ============================================================

    @classmethod
    def get(cls, name: str) -> Type[BaseReliability]:
        if not cls.has_mechanism(name):
            raise ReliabilityNotFound(
                f"Reliability mechanism '{name}' not registered. Available: {cls.list_mechanisms()}"
            )
        return cls._registry[name]

    @classmethod
    def get_default_policy(cls, name: str) -> ReliabilityPolicy:
        if name not in cls._policies:
            raise ReliabilityNotFound(
                f"Default policy for mechanism '{name}' not found. Available policies: {list(cls._policies.keys())}"
            )
        return cls._policies[name]

    @classmethod
    def has_mechanism(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def list_mechanisms(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
        cls._policies.clear()
