# ============================================================
# Provider Registry — Central registration for all providers
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new providers without modifying Factory
# 2. Plugin architecture: Providers can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
# ============================================================

from typing import Dict, Type

from .base_provider import BaseProvider


class ProviderRegistry:
    _registry: Dict[str, Type[BaseProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: Type[BaseProvider]) -> None:
        cls._registry[name] = provider_class

    @classmethod
    def get(cls, name: str) -> Type[BaseProvider]:
        return cls._registry[name]

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def has_provider(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
