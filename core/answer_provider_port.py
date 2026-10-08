"""Provider dependency wiring only; contains no financial or model semantics."""
import math
import time
from enum import StrEnum

from llm.factory.provider_factory import ProviderFactory
from llm.providers.base_provider import BaseProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import InvalidProviderResponseError, ProviderError, ProviderTimeoutError
from llm.providers.provider_guard import normalize_local_ollama_url
from llm.providers.provider_models import ChatRequest, GenerationStatus
from llm.providers.timeout_policy import effective_timeout


def resolve_answer_provider(*, provider=None, provider_config=None, model=None, base_url=None):
    if provider is not None:
        if not isinstance(provider, BaseProvider) or provider_config is not None:
            raise ValueError("EXPLICIT_PROVIDER_CONTRACT_REQUIRED")
        return provider
    if provider_config is None:
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError("EXPLICIT_PROVIDER_MODEL_REQUIRED")
        provider_config = ProviderConfig(provider="ollama", model=model, api_key="",
                                         base_url=normalize_local_ollama_url(base_url))
    if not isinstance(provider_config, ProviderConfig):
        raise ValueError("EXPLICIT_PROVIDER_CONFIG_REQUIRED")
    return ProviderFactory.create(provider_config)


class AnswerRequestPurpose(StrEnum):
    STRUCTURED_GENERATION = "STRUCTURED_GENERATION"
    STRUCTURED_REVIEW = "STRUCTURED_REVIEW"


def chat_answer(provider, instruction, payload, *, max_seconds, max_tokens, thinking_enabled=None,
                purpose=None):
    if (isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds) or max_seconds <= 0):
        raise ValueError("INVALID_PROVIDER_DEADLINE")
    capability = provider.get_capability()
    if not capability.supports_system_prompt:
        raise ProviderError("Provider port requires system prompt capability")
    if purpose is not None:
        AnswerRequestPurpose(purpose)
        thinking_enabled = False if capability.supports_thinking_control else None
    deadline = time.monotonic() + max_seconds
    effective_timeout(max_seconds, deadline)
    response = provider.chat(ChatRequest(messages=[{"role": "user", "content": payload}],
        system_prompt=instruction, max_tokens=max_tokens, temperature=0, deadline=deadline,
        thinking_enabled=thinking_enabled))
    if time.monotonic() > deadline:
        raise ProviderTimeoutError("Answer request exceeded its total deadline",
            timeout_source="TOTAL_REQUEST_DEADLINE")
    if response.provider != provider.provider_name or response.model.casefold() != provider.model.casefold():
        raise InvalidProviderResponseError("Provider response identity mismatch")
    if response.generation_status != GenerationStatus.SUCCESS:
        if response.generation_status == GenerationStatus.TIMEOUT:
            raise ProviderTimeoutError("Provider reported generation timeout", timeout_source="GENERATION_TIMEOUT")
        raise InvalidProviderResponseError("Provider did not report successful generation")
    return response


def complete_usage(response):
    values = (response.prompt_tokens, response.completion_tokens, response.total_tokens)
    if all(type(value) is int and value >= 0 for value in values) and values[0] + values[1] == values[2]:
        return values
    return None
