# ============================================================
# Capability Routing Policy
# ============================================================
# Routes requests based on provider capabilities.
# Iterates ProviderRegistry, checks capabilities, returns the
# best match. No hardcoded provider names.
# ============================================================

from config.llm import (
    ANTHROPIC_MODEL,
    DEEPSEEK_MODEL,
    DOUBAO_MODEL,
    GEMINI_MODEL,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
)

from ..providers.provider_config import ProviderConfig
from ..providers.provider_registry import ProviderRegistry
from .base_policy import BaseRoutingPolicy
from .routing_context import RoutingContext
from .routing_result import RoutingResult

_DEFAULT_MODELS = {
    "deepseek": DEEPSEEK_MODEL,
    "gemini": GEMINI_MODEL,
    "openai": OPENAI_MODEL,
    "anthropic": ANTHROPIC_MODEL,
    "doubao": DOUBAO_MODEL,
    "ollama": LLM_MODEL,
}


class CapabilityRoutingPolicy(BaseRoutingPolicy):
    def __init__(
        self,
        default_provider: str | None = None,
        default_model: str | None = None,
        provider_models: dict[str, str] | None = None,
    ):
        self._default_provider = default_provider or LLM_PROVIDER
        self._default_model = default_model or LLM_MODEL
        self._provider_models = provider_models or _DEFAULT_MODELS

    def select(
        self,
        context: RoutingContext,
        providers: list[str] | None = None,
    ) -> RoutingResult:
        # 1. Preferred provider takes priority
        if context.preferred_provider:
            return self._result_for(
                context.preferred_provider,
                context,
                reason="Preferred provider",
                confidence=1.0,
            )

        # 2. Capability-based routing
        result = self._route_by_capability(context, providers)
        if result is not None:
            return result

        # 3. Fallback to default provider
        return self._result_for(
            self._default_provider,
            context,
            reason="Default provider",
            confidence=0.7,
        )

    def _route_by_capability(
        self,
        context: RoutingContext,
        providers: list[str] | None = None,
    ) -> RoutingResult | None:
        if providers is None:
            providers = ProviderRegistry.list_providers()
        best_provider = None
        best_reason = ""
        best_confidence = 0.0

        for name in providers:
            capability = self._get_capability(name)
            if capability is None:
                continue

            reason, confidence = self._match(
                context,
                capability,
                name,
            )
            if confidence > best_confidence:
                best_confidence = confidence
                best_provider = name
                best_reason = reason

        if best_provider and best_confidence > 0:
            return self._result_for(
                best_provider,
                context,
                reason=best_reason,
                confidence=best_confidence,
            )
        return None

    def _match(
        self,
        context: RoutingContext,
        capability,
        provider_name: str,
    ) -> tuple[str, float]:
        required = 0
        matched = 0
        reasons = []

        checks = [
            (context.requires_image, capability.supports_image, "image"),
            (context.requires_audio, capability.supports_audio, "audio"),
            (context.requires_video, capability.supports_video, "video"),
            (context.requires_reasoning, capability.supports_reasoning_effort, "reasoning"),
            (context.requires_tools, capability.supports_tools, "tools"),
            (context.requires_stream, capability.supports_stream, "stream"),
            (context.requires_json, capability.supports_json_mode, "json"),
        ]

        for required_flag, supports_flag, label in checks:
            if required_flag:
                required += 1
                if supports_flag:
                    matched += 1
                    reasons.append(label)

        if required == 0:
            # The user's selected default applies to every task that does not
            # require a specific capability.  Restricting this preference to
            # CHAT made financial/document questions tie at the generic score;
            # registry order could then route them to an unrelated provider.
            if provider_name == self._default_provider:
                return ("Default provider", 0.85)
            return ("General purpose", 0.5)

        if matched != required:
            return ("No capability match", 0.0)

        reason = "Supports: " + ", ".join(reasons)
        return (reason, 1.0)

    def _get_capability(self, name: str):
        provider_class = ProviderRegistry.get(name)
        model = self._provider_models.get(name, "default")
        config = ProviderConfig(
            provider=name,
            model=model,
            api_key="",
        )
        provider = provider_class(config)
        return provider.get_capability()

    def _result_for(
        self,
        provider_name: str,
        context: RoutingContext,
        reason: str,
        confidence: float,
    ) -> RoutingResult:
        model = self._provider_models.get(
            provider_name,
            self._default_model,
        )
        fallback = self._default_provider if provider_name != self._default_provider else None
        return RoutingResult(
            provider=provider_name,
            model=model,
            reason=reason,
            confidence=confidence,
            fallback_provider=fallback,
        )
