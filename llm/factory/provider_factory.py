# ============================================================
# Provider Factory — Creates provider instances by name
# ============================================================
# The Factory only knows how to create, not which providers exist.
# That knowledge lives in the Registry.
#
# Usage:
#   config = ProviderConfig(provider="deepseek", model="deepseek-v4-flash", ...)
#   provider = ProviderFactory.create(config)
#   response = provider.chat(request)
# ============================================================

from typing import Optional, Union

from ..providers.base_provider import BaseProvider
from ..providers.provider_config import ProviderConfig
from ..providers.provider_exceptions import ProviderNotFound
from ..providers.provider_registry import ProviderRegistry


class ProviderFactory:
    _default_provider: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, config_or_name: Union[ProviderConfig, str]) -> BaseProvider:
        if isinstance(config_or_name, ProviderConfig):
            config = config_or_name
            name = config.provider
        else:
            name = config_or_name
            config = ProviderConfig(provider=name, model="", api_key="")

        if not ProviderRegistry.has_provider(name):
            raise ProviderNotFound(f"Provider '{name}' not registered. Available: {ProviderRegistry.list_providers()}")
        provider_class = ProviderRegistry.get(name)
        return provider_class(config)

    # ============================================================
    # Default provider
    # ============================================================

    @classmethod
    def set_default(cls, name: str) -> None:
        if not ProviderRegistry.has_provider(name):
            raise ProviderNotFound(f"Cannot set default. Provider '{name}' not registered.")
        cls._default_provider = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_provider

    @classmethod
    def create_default(cls) -> BaseProvider:
        if cls._default_provider is None:
            raise ProviderNotFound("No default provider set. Call ProviderFactory.set_default(name) first.")
        return cls.create(cls._default_provider)

    # ============================================================
    # Discovery
    # ============================================================

    @classmethod
    def list_providers(cls) -> list[str]:
        return ProviderRegistry.list_providers()
