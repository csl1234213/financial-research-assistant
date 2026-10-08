# llm/provider.py
# ============================================================
# Legacy adapter — delegates to ProviderFactory
# ============================================================
# This module exists for backward compatibility with existing code
# that calls call_llm(prompt). New code should use:
#
#   from config import LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, ...
#   from llm.factory.provider_factory import ProviderFactory
#   from llm.providers.provider_config import ProviderConfig
#
#   config = ProviderConfig(
#       provider=LLM_PROVIDER,
#       model=LLM_MODEL,
#       api_key=LLM_API_KEY,
#       ...
#   )
#   provider = ProviderFactory.create(config)
#   response = provider.chat(ChatRequest(...))
# ============================================================

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_CONNECT_TIMEOUT,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_READ_TIMEOUT,
    LLM_STREAM,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    LLM_TOTAL_DEADLINE,
)

from .adapters.claude_provider import ClaudeProvider
from .adapters.deepseek_provider import DeepSeekProvider
from .adapters.doubao_provider import DoubaoProvider
from .adapters.gemini_provider import GeminiProvider
from .adapters.ollama_provider import OllamaProvider
from .adapters.openai_provider import OpenAIProvider
from .factory.provider_factory import ProviderFactory
from .providers.base_provider import BaseProvider
from .providers.provider_config import ProviderConfig, timeout_budget_for_provider
from .providers.provider_models import ChatRequest
from .providers.provider_registry import ProviderRegistry
from .usage import record_failed_usage, record_usage

# Register providers at import time
ProviderRegistry.register("deepseek", DeepSeekProvider)
ProviderRegistry.register("gemini", GeminiProvider)
ProviderRegistry.register("openai", OpenAIProvider)
ProviderRegistry.register("anthropic", ClaudeProvider)
ProviderRegistry.register("doubao", DoubaoProvider)
ProviderRegistry.register("ollama", OllamaProvider)


def _build_config() -> ProviderConfig:
    timeout, read_timeout = timeout_budget_for_provider(
        LLM_PROVIDER,
        timeout=LLM_TIMEOUT,
        read_timeout=LLM_READ_TIMEOUT,
        total_deadline=LLM_TOTAL_DEADLINE,
    )
    return ProviderConfig(
        provider=LLM_PROVIDER,
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        timeout=timeout,
        stream=LLM_STREAM,
        connect_timeout=LLM_CONNECT_TIMEOUT,
        read_timeout=read_timeout,
        total_deadline=LLM_TOTAL_DEADLINE,
    )


def call_llm(
    prompt: str,
    *,
    provider: BaseProvider | None = None,
    system_prompt: str = "You are a professional financial analyst.",
    deadline: float | None = None,
) -> str:
    """Generate through the provider selected by the runtime when supplied."""
    if provider is None:
        config = _build_config()
        provider = ProviderFactory.create(config)
    request = ChatRequest(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=system_prompt,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        deadline=deadline,
    )
    try:
        response = provider.chat(request)
    except Exception:
        record_failed_usage(provider.provider_name, getattr(provider, "model", "unknown"))
        raise
    record_usage(response)
    return response.content
