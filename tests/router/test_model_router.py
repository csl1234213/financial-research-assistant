import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import MagicMock

import pytest

from llm.adapters.ollama_provider import OllamaProvider
from llm.providers.base_provider import BaseProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_models import (
    ChatRequest,
    ChatResponse,
    ProviderCapability,
)
from llm.providers.provider_registry import ProviderRegistry
from llm.router import (
    ModelRouter,
    RoutingPolicy,
    TaskType,
)
from llm.router.routing_context import RoutingContext
from llm.router.routing_result import RoutingResult


class _MockProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self._config = config

    @property
    def provider_name(self) -> str:
        return self._config.provider

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="mock",
            provider=self._config.provider,
            model=self._config.model,
        )

    def health(self) -> bool:
        return True

    def list_models(self) -> list:
        return [self._config.model]

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_stream=True,
            supports_tools=True,
            max_context_tokens=8192,
        )


class TestModelRouter:

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        ProviderRegistry.clear()
        ProviderRegistry.register("deepseek", _MockProvider)
        ProviderRegistry.register("gemini", _MockProvider)
        yield
        ProviderRegistry.clear()

    @pytest.fixture
    def context(self):
        return RoutingContext(task=TaskType.CHAT)

    @pytest.fixture
    def router(self):
        policy = MagicMock()
        policy.select.return_value = RoutingResult(
            provider="deepseek",
            model="deepseek-v4-flash",
            reason="Default provider",
            confidence=0.7,
        )
        return ModelRouter(
            policy=RoutingPolicy(policy),
            provider_configs={
                "deepseek": {
                    "api_key": "test-deepseek-key",
                    "base_url": "https://test.deepseek.com",
                },
                "gemini": {
                    "api_key": "test-gemini-key",
                },
            },
        )

    # =========================
    # route()
    # =========================

    def test_route_returns_provider_and_routing(self, router, context):
        result = router.route(context)

        assert "provider" in result
        assert "routing" in result
        assert isinstance(result["provider"], BaseProvider)
        assert isinstance(result["routing"], RoutingResult)

    def test_route_sets_decision_time_ms(self, router, context):
        result = router.route(context)

        assert result["routing"].decision_time_ms is not None
        assert result["routing"].decision_time_ms >= 0.0

    def test_route_routing_matches_policy(self, router, context):
        result = router.route(context)

        assert result["routing"].provider == "deepseek"
        assert result["routing"].model == "deepseek-v4-flash"
        assert result["routing"].reason == "Default provider"
        assert result["routing"].confidence == 0.7

    def test_available_provider_allowlist_rejects_policy_escape(self, context):
        policy = MagicMock()
        policy.select.return_value = RoutingResult(
            provider="gemini",
            model="gemini-test",
            reason="unexpected selection",
            confidence=1.0,
        )
        router = ModelRouter(
            policy=RoutingPolicy(policy),
            available_providers=["deepseek"],
        )

        with pytest.raises(ValueError, match="outside the configured allowlist"):
            router.route(context)

    # =========================
    # _build_config()
    # =========================

    def test_build_config_uses_provider_overrides(self, router, context):
        result = router.route(context)

        provider = result["provider"]
        assert provider._config.api_key == "test-deepseek-key"
        assert provider._config.base_url == "https://test.deepseek.com"

    def test_build_config_gemini_uses_override(self, router, context):
        policy = router._policy._policy
        policy.select.return_value = RoutingResult(
            provider="gemini",
            model="gemini-2.5-flash",
            reason="Gemini selected",
            confidence=0.95,
        )

        result = router.route(context)

        provider = result["provider"]
        assert provider._config.api_key == "test-gemini-key"

    def test_ollama_read_timeout_matches_total_deadline_without_widening_remote_defaults(
        self, router, monkeypatch,
    ):
        import llm.router.model_router as model_router_module

        monkeypatch.setattr(model_router_module, "LLM_TIMEOUT", 60)
        monkeypatch.setattr(model_router_module, "LLM_READ_TIMEOUT", 45)
        monkeypatch.setattr(model_router_module, "LLM_TOTAL_DEADLINE", 120)

        local_config = router._build_config(
            RoutingResult("ollama", "qwen3.8", "test", 1.0),
        )
        remote_config = router._build_config(
            RoutingResult("deepseek", "deepseek-v4-flash", "test", 1.0),
        )

        assert local_config.timeout == 120
        assert local_config.read_timeout == 120
        assert local_config.connect_timeout == 10
        assert local_config.total_deadline == 120
        assert remote_config.timeout == 60
        assert remote_config.read_timeout == 45

    def test_build_config_falls_back_to_default(self):
        policy = MagicMock()
        policy.select.return_value = RoutingResult(
            provider="deepseek",
            model="deepseek-v4-flash",
            reason="Default provider",
            confidence=0.5,
        )
        router = ModelRouter(
            policy=RoutingPolicy(policy),
            provider_configs={},
        )

        result = router.route(RoutingContext(task=TaskType.CHAT))

        provider = result["provider"]
        assert provider._config.provider == "deepseek"
        assert provider._config.model == "deepseek-v4-flash"

    # =========================
    # route() with custom provider_configs
    # =========================

    def test_custom_provider_configs(self, context):
        policy = MagicMock()
        policy.select.return_value = RoutingResult(
            provider="deepseek",
            model="deepseek-v4-pro",
            reason="Custom config",
            confidence=1.0,
        )
        router = ModelRouter(
            policy=RoutingPolicy(policy),
            provider_configs={
                "deepseek": {
                    "api_key": "custom-key",
                    "base_url": "https://custom.deepseek.com",
                },
            },
        )

        result = router.route(context)

        assert result["provider"]._config.api_key == "custom-key"
        assert result["provider"]._config.base_url == "https://custom.deepseek.com"

    def test_routes_local_ollama_with_saved_endpoint_and_model(self, context):
        ProviderRegistry.register("ollama", OllamaProvider)
        policy = MagicMock()
        policy.select.return_value = RoutingResult(
            provider="ollama",
            model="qwen3.8:latest",
            reason="Configured local model",
            confidence=1.0,
        )
        router = ModelRouter(
            policy=RoutingPolicy(policy),
            provider_configs={
                "ollama": {
                    "api_key": "",
                    "base_url": "http://host.docker.internal:11434",
                },
            },
        )

        result = router.route(context)

        assert result["provider"]._config.provider == "ollama"
        assert result["provider"]._config.model == "qwen3.8:latest"
        assert result["provider"]._config.base_url == "http://host.docker.internal:11434"

    # =========================
    # decision_time_ms
    # =========================

    def test_decision_time_ms_is_positive_float(self, router, context):
        result = router.route(context)

        dt = result["routing"].decision_time_ms
        assert isinstance(dt, float)
        assert dt >= 0.0

    def test_decision_time_ms_is_rounded(self, router, context):
        result = router.route(context)

        dt = result["routing"].decision_time_ms
        assert dt == round(dt, 3)

    # =========================
    # RoutingResult fields on route()
    # =========================

    def test_routing_result_fallback_in_route(self, router, context):
        result = router.route(context)

        assert hasattr(result["routing"], "fallback_provider")
        assert hasattr(result["routing"], "decision_time_ms")
