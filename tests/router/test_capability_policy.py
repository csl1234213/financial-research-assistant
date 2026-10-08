import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import patch

import pytest

from agent.planning.task_enums import TaskType as PlannedTaskType
from llm.providers.base_provider import BaseProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_models import (
    ChatRequest,
    ChatResponse,
    ProviderCapability,
)
from llm.providers.provider_registry import ProviderRegistry
from llm.router import CapabilityRoutingPolicy, RoutingPriority, TaskType
from llm.router.routing_context import RoutingContext
from llm.router.routing_result import RoutingResult


class _MockDeepSeekProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self._config = config

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(content="", provider="deepseek", model="")

    def health(self) -> bool:
        return True

    def list_models(self) -> list:
        return ["deepseek-v4-flash"]

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_stream=True,
            supports_function_call=True,
            supports_image=False,
            supports_audio=False,
            supports_video=False,
            supports_json_mode=True,
            supports_reasoning_effort=False,
            supports_tools=True,
            max_context_tokens=128000,
        )


class _MockGeminiProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self._config = config

    @property
    def provider_name(self) -> str:
        return "gemini"

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(content="", provider="gemini", model="")

    def health(self) -> bool:
        return True

    def list_models(self) -> list:
        return ["gemini-2.5-flash"]

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_stream=True,
            supports_function_call=True,
            supports_image=True,
            supports_audio=True,
            supports_video=True,
            supports_json_mode=True,
            supports_reasoning_effort=True,
            supports_tools=True,
            supports_multimodal=True,
            max_context_tokens=1048576,
        )


class TestCapabilityRoutingPolicy:

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        ProviderRegistry.clear()
        ProviderRegistry.register("deepseek", _MockDeepSeekProvider)
        ProviderRegistry.register("gemini", _MockGeminiProvider)
        yield
        ProviderRegistry.clear()

    @pytest.fixture
    def policy(self):
        return CapabilityRoutingPolicy(
            default_provider="deepseek",
            default_model="deepseek-v4-flash",
            provider_models={
                "deepseek": "deepseek-v4-flash",
                "gemini": "gemini-2.5-flash",
            },
        )

    # =========================
    # select() — preferred_provider
    # =========================

    def test_preferred_provider_takes_priority(self, policy):
        ctx = RoutingContext(
            task=TaskType.CHAT,
            preferred_provider="gemini",
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.model == "gemini-2.5-flash"
        assert result.reason == "Preferred provider"
        assert result.confidence == 1.0
        assert result.fallback_provider == "deepseek"

    # =========================
    # select() — capability-based routing
    # =========================

    def test_image_requirement_routes_to_gemini(self, policy):
        ctx = RoutingContext(
            task=TaskType.IMAGE_ANALYSIS,
            requires_image=True,
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert "image" in result.reason.lower()
        assert result.confidence > 0
        assert result.fallback_provider == "deepseek"

    def test_audio_requirement_routes_to_gemini(self, policy):
        ctx = RoutingContext(
            task=TaskType.DOCUMENT_QA,
            requires_audio=True,
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.fallback_provider == "deepseek"

    def test_reasoning_requirement_routes_to_gemini(self, policy):
        ctx = RoutingContext(
            task=TaskType.REASONING,
            requires_reasoning=True,
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.fallback_provider == "deepseek"

    def test_tools_requirement_both_match(self, policy):
        ctx = RoutingContext(
            task=TaskType.CHAT,
            requires_tools=True,
        )
        result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.confidence == 1.0

    def test_stream_requirement_both_match(self, policy):
        ctx = RoutingContext(
            task=TaskType.CHAT,
            requires_stream=True,
        )
        result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.confidence == 1.0

    def test_json_requirement_both_match(self, policy):
        ctx = RoutingContext(
            task=TaskType.CHAT,
            requires_json=True,
        )
        result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.confidence == 1.0

    def test_video_requirement_routes_to_gemini(self, policy):
        ctx = RoutingContext(
            task=TaskType.DOCUMENT_QA,
            requires_video=True,
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.fallback_provider == "deepseek"

    def test_mixed_requirements_gemini_wins(self, policy):
        ctx = RoutingContext(
            task=TaskType.IMAGE_ANALYSIS,
            requires_image=True,
            requires_reasoning=True,
            requires_tools=True,
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.confidence == 1.0
        assert result.fallback_provider == "deepseek"

    def test_capability_no_match_both_lack(self, policy):
        ctx = RoutingContext(
            task=TaskType.CHAT,
            requires_audio=True,
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.confidence > 0

    # =========================
    # select() — default fallback
    # =========================

    def test_chat_task_defaults_to_default_provider(self, policy):
        ctx = RoutingContext(task=TaskType.CHAT)
        result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.model == "deepseek-v4-flash"
        assert result.reason == "Default provider"
        assert result.confidence == 0.85
        assert result.fallback_provider is None

    def test_document_qa_defaults_to_the_user_selected_provider(self, policy):
        ctx = RoutingContext(task=TaskType.DOCUMENT_QA)
        result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.reason == "Default provider"
        assert result.confidence == 0.85
        assert result.fallback_provider is None

    def test_summarization_defaults_to_the_user_selected_provider(self, policy):
        ctx = RoutingContext(task=TaskType.SUMMARIZATION)
        result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.reason == "Default provider"
        assert result.confidence == 0.85

    @pytest.mark.parametrize(
        "task_type",
        [
            TaskType.DOCUMENT_QA,
            PlannedTaskType.RESEARCH,
            PlannedTaskType.FINANCIAL_ANALYSIS,
            PlannedTaskType.COMPARISON,
        ],
    )
    def test_configured_local_default_wins_ties_for_financial_tasks(self, task_type):
        policy = CapabilityRoutingPolicy(
            default_provider="gemini",
            default_model="gemini-2.5-flash",
            provider_models={
                "deepseek": "deepseek-v4-flash",
                "gemini": "gemini-2.5-flash",
            },
        )
        # The external provider is deliberately listed first, matching the
        # production registration order that previously won an equal score.
        result = policy.select(
            RoutingContext(task=task_type),
            providers=["deepseek", "gemini"],
        )

        assert result.provider == "gemini"
        assert result.reason == "Default provider"
        assert result.confidence == 0.85

    # =========================
    # select() — custom default_provider
    # =========================

    def test_custom_default_provider_is_used(self):
        policy = CapabilityRoutingPolicy(
            default_provider="gemini",
            default_model="gemini-2.5-flash",
        )
        ctx = RoutingContext(task=TaskType.CHAT)
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.fallback_provider is None

    # =========================
    # select() — with explicit providers list
    # =========================

    def test_select_with_explicit_providers(self, policy):
        ctx = RoutingContext(
            task=TaskType.IMAGE_ANALYSIS,
            requires_image=True,
        )
        result = policy.select(ctx, providers=["deepseek", "gemini"])

        assert result.provider == "gemini"

    def test_select_with_limited_providers(self, policy):
        ctx = RoutingContext(
            task=TaskType.IMAGE_ANALYSIS,
            requires_image=True,
        )
        result = policy.select(ctx, providers=["deepseek"])

        assert result.provider == "deepseek"
        assert result.reason == "Default provider"

    # =========================
    # _match() — edge cases
    # =========================

    def test_chat_task_default_provider_gets_higher_confidence(self, policy):
        ctx = RoutingContext(
            task=TaskType.CHAT,
            priority=RoutingPriority.BALANCED,
        )
        result = policy.select(ctx, providers=["deepseek", "gemini"])

        assert result.provider == "deepseek"
        assert result.reason == "Default provider"
        assert result.confidence == 0.85

    def test_chat_task_with_non_default(self):
        policy = CapabilityRoutingPolicy(
            default_provider="gemini",
            default_model="gemini-2.5-flash",
        )
        ctx = RoutingContext(task=TaskType.CHAT)
        result = policy.select(ctx, providers=["deepseek", "gemini"])

        assert result.provider == "gemini"

    # =========================
    # _result_for() — fallback_provider
    # =========================

    def test_default_provider_has_no_fallback(self, policy):
        ctx = RoutingContext(task=TaskType.CHAT)
        result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.fallback_provider is None

    def test_non_default_provider_has_fallback(self, policy):
        ctx = RoutingContext(
            task=TaskType.IMAGE_ANALYSIS,
            requires_image=True,
        )
        result = policy.select(ctx)

        assert result.provider == "gemini"
        assert result.fallback_provider == "deepseek"

    # =========================
    # Provider model override
    # =========================

    def test_custom_provider_models(self):
        policy = CapabilityRoutingPolicy(
            default_provider="deepseek",
            default_model="deepseek-v4-flash",
            provider_models={
                "deepseek": "deepseek-v4-pro",
                "gemini": "gemini-2.5-pro",
            },
        )
        ctx = RoutingContext(task=TaskType.CHAT)
        result = policy.select(ctx)

        assert result.model == "deepseek-v4-pro"

    # =========================
    # RoutingResult fields
    # =========================

    def test_routing_result_fields_are_set(self, policy):
        ctx = RoutingContext(
            task=TaskType.IMAGE_ANALYSIS,
            requires_image=True,
        )
        result = policy.select(ctx)

        assert isinstance(result, RoutingResult)
        assert result.provider
        assert result.model
        assert result.reason
        assert result.confidence is not None
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0

    # =========================
    # _route_by_capability — None capability
    # =========================

    def test_skips_provider_with_none_capability(self, policy):
        with patch.object(
            policy,
            "_get_capability",
            return_value=None,
        ):
            ctx = RoutingContext(
                task=TaskType.IMAGE_ANALYSIS,
                requires_image=True,
            )
            result = policy.select(ctx)

        assert result.provider == "deepseek"
        assert result.reason == "Default provider"
        assert result.confidence == 0.7
