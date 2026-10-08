import pytest

from llm.adapters.claude_provider import ClaudeProvider
from llm.adapters.deepseek_provider import DeepSeekProvider
from llm.adapters.doubao_provider import DoubaoProvider
from llm.adapters.gemini_provider import GeminiProvider
from llm.adapters.openai_provider import OpenAIProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import ProviderError
from llm.providers.provider_guard import ensure_real_provider_allowed


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("deepseek", "https://api.deepseek.com"),
        ("openai", "https://api.openai.com/v1"),
        ("gemini", None),
        ("anthropic", "https://api.anthropic.com"),
        ("doubao", "https://ark.cn-beijing.volces.com/api/v3"),
    ],
)
def test_external_provider_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    base_url: str | None,
) -> None:
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "false")

    with pytest.raises(ProviderError, match="Real provider calls are disabled"):
        ensure_real_provider_allowed(provider, base_url)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:11434/v1",
        "http://localhost:11434/v1",
        "http://host.docker.internal:11434/v1",
    ],
)
def test_local_ollama_endpoint_is_allowed_without_paid_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
) -> None:
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "false")
    ensure_real_provider_allowed("openai", base_url)


def test_external_provider_is_allowed_only_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "true")
    ensure_real_provider_allowed("deepseek", "https://api.deepseek.com")


@pytest.mark.parametrize(
    ("provider_cls", "provider_name", "base_url"),
    [
        (DeepSeekProvider, "deepseek", "https://api.deepseek.com"),
        (OpenAIProvider, "openai", "https://api.openai.com/v1"),
        (GeminiProvider, "gemini", None),
        (ClaudeProvider, "anthropic", "https://api.anthropic.com"),
        (DoubaoProvider, "doubao", "https://ark.cn-beijing.volces.com/api/v3"),
    ],
)
def test_registered_external_adapters_fail_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
    provider_cls: type,
    provider_name: str,
    base_url: str | None,
) -> None:
    """The shared guard must be wired into every production adapter.

    This intentionally calls each adapter's lazy client boundary instead of
    only testing the helper in isolation.  A future adapter that forgets the
    guard would otherwise be able to spend against a configured credential.
    """

    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "false")
    config = ProviderConfig(
        provider=provider_name,
        model="test-model",
        api_key="test-only-not-a-secret",
        base_url=base_url,
    )
    provider = provider_cls(config)

    with pytest.raises(ProviderError, match="Real provider calls are disabled"):
        client_boundary = provider._get_client
        if callable(client_boundary):
            client_boundary()
        else:
            _ = client_boundary
