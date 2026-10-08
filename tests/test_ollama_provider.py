from __future__ import annotations

import time
from unittest.mock import MagicMock

import httpx
import pytest

from llm.adapters.ollama_provider import OllamaProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import ProviderError, ProviderTimeoutError
from llm.providers.provider_models import ChatRequest


def _provider() -> OllamaProvider:
    return OllamaProvider(
        ProviderConfig(
            provider="ollama",
            model="qwen3.8",
            api_key="",
            base_url="http://host.docker.internal:11434",
            max_tokens=512,
            timeout=90,
            read_timeout=75,
            total_deadline=90,
        )
    )


def test_ollama_chat_uses_native_options_and_reports_usage(monkeypatch):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "model": "qwen3.8",
        "message": {"content": "答复内容"},
        "prompt_eval_count": 123,
        "eval_count": 45,
        "done_reason": "stop",
    }
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr("llm.adapters.ollama_provider.httpx.Client", lambda **_: client)

    result = _provider().chat(
        ChatRequest(
            messages=[{"role": "user", "content": "问题"}],
            system_prompt="只基于证据回答",
            max_tokens=256,
        )
    )

    payload = client.post.call_args.kwargs["json"]
    assert client.post.call_args.args[0].endswith("/api/chat")
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["options"] == {
        "temperature": 0.0,
        "num_ctx": 8192,
        "num_predict": 256,
    }
    assert payload["messages"][0]["role"] == "system"
    assert result.content == "答复内容"
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (123, 45, 168)


def test_ollama_rejects_non_local_endpoint_even_if_real_provider_opted_in(monkeypatch):
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "true")
    provider = OllamaProvider(
        ProviderConfig(
            provider="ollama",
            model="qwen3.8",
            api_key="",
            base_url="https://example.com",
        )
    )

    with pytest.raises(ProviderError, match="local endpoint"):
        provider.chat(ChatRequest(messages=[{"role": "user", "content": "x"}]))


def test_ollama_empty_response_fails_closed(monkeypatch):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"message": {"content": "  "}}
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr("llm.adapters.ollama_provider.httpx.Client", lambda **_: client)

    with pytest.raises(ProviderError, match="empty model content"):
        _provider().chat(ChatRequest(messages=[{"role": "user", "content": "x"}]))


def test_ollama_timeout_is_translated(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = httpx.ReadTimeout("timed out")
    monkeypatch.setattr("llm.adapters.ollama_provider.httpx.Client", lambda **_: client)

    with pytest.raises(ProviderTimeoutError, match="Ollama request timed out"):
        _provider().chat(ChatRequest(messages=[{"role": "user", "content": "x"}]))


def test_ollama_expired_absolute_deadline_fails_before_network(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("llm.adapters.ollama_provider.httpx.Client", lambda **_: client)

    with pytest.raises(ProviderTimeoutError, match="exceeded its total deadline"):
        _provider().chat(
            ChatRequest(
                messages=[{"role": "user", "content": "x"}],
                deadline=0.0,
            )
        )
    client.assert_not_called()


def test_ollama_socket_timeout_uses_remaining_request_deadline():
    provider = OllamaProvider(
        ProviderConfig(
            provider="ollama",
            model="qwen3.8",
            api_key="",
            timeout=120,
            connect_timeout=10,
            read_timeout=120,
            total_deadline=120,
        )
    )

    timeout = provider._timeout_config(
        ChatRequest(messages=[], deadline=time.monotonic() + 20),
    )

    assert timeout.connect == 10
    assert 19 < timeout.read <= 20


def test_legacy_config_preserves_ollama_timeout_and_total_deadline(monkeypatch):
    import llm.provider as legacy_provider

    monkeypatch.setattr(legacy_provider, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(legacy_provider, "LLM_TIMEOUT", 60)
    monkeypatch.setattr(legacy_provider, "LLM_READ_TIMEOUT", 45)
    monkeypatch.setattr(legacy_provider, "LLM_CONNECT_TIMEOUT", 10)
    monkeypatch.setattr(legacy_provider, "LLM_TOTAL_DEADLINE", 120)

    config = legacy_provider._build_config()

    assert config.timeout == 60
    assert config.read_timeout == 45
    assert config.connect_timeout == 10
    assert config.total_deadline == 120
