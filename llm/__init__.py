# LLM Provider Layer
# ============================================================
# Provider abstraction for multi-LLM support
# ============================================================

from llm.factory.provider_factory import ProviderFactory

# Auto-register available providers
from llm.provider import call_llm  # noqa: F401
from llm.providers.base_provider import BaseProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import (
    AuthenticationError,
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderError,
    ProviderNotFound,
    ProviderTimeoutError,
    RateLimitError,
)
from llm.providers.provider_models import (
    ChatRequest,
    ChatResponse,
    ProviderCapability,
)
from llm.providers.provider_registry import ProviderRegistry
from llm.router import (
    BaseRoutingPolicy,
    CapabilityRoutingPolicy,
    ModelRouter,
    RoutingContext,
    RoutingPolicy,
    RoutingPriority,
    RoutingResult,
    TaskType,
)

__all__ = [
    "BaseProvider",
    "ProviderConfig",
    "ChatRequest",
    "ChatResponse",
    "ProviderCapability",
    "ProviderError",
    "ProviderNotFound",
    "AuthenticationError",
    "RateLimitError",
    "ModelNotFoundError",
    "ProviderConnectionError",
    "ProviderTimeoutError",
    "ProviderRegistry",
    "ProviderFactory",
    "RoutingContext",
    "RoutingResult",
    "RoutingPriority",
    "TaskType",
    "BaseRoutingPolicy",
    "CapabilityRoutingPolicy",
    "RoutingPolicy",
    "ModelRouter",
    "call_llm",
]
