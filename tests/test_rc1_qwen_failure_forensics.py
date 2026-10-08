"""Offline adapter evidence only; never substitutes for real original acceptance."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from llm.adapters.ollama_provider import OllamaProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import ProviderError, ProviderTimeoutError
from llm.providers.provider_models import ChatRequest


def provider():
    return OllamaProvider(ProviderConfig(provider="ollama", model="fixture-local",
        api_key="", base_url="http://127.0.0.1:11434", timeout=120,
        total_deadline=120, read_timeout=120))


def client_with(monkeypatch, body=None, error=None):
    client = MagicMock()
    client.__enter__.return_value = client
    response = httpx.Response(200, json=body, request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"))
    client.post.return_value = response
    if error:
        client.post.side_effect = error
    monkeypatch.setattr("llm.adapters.ollama_provider.httpx.Client", lambda **_: client)
    return client


@pytest.mark.parametrize("usage,expected", [
    ({"prompt_eval_count": 10, "eval_count": 4}, (10, 4, 14)),
    ({}, (None, None, None)),
    ({"prompt_eval_count": 10}, (10, None, None)),
    ({"usage": {}}, (None, None, None)),
])
def test_valid_generation_is_not_discarded_by_native_adapter_for_missing_usage(monkeypatch, usage, expected):
    # Missing native counts remain absent, never fabricated as zero cost.
    body = {"message": {"content": '{"answer": 4}'}, "done_reason": "stop", **usage}
    client_with(monkeypatch, body)
    result = provider().chat(ChatRequest(messages=[]))
    assert json.loads(result.content) == {"answer": 4}
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == expected


def test_original_timeout_fixture_translates_without_retry(monkeypatch):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "rc1_qwen_original_timeout.json").read_text(encoding="utf-8"))
    assert fixture["failure_class"] == "TIMEOUT"
    client = client_with(monkeypatch, error=httpx.ReadTimeout("injected private details"))
    with pytest.raises(ProviderTimeoutError, match="^Ollama request timed out$") as captured:
        provider().chat(ChatRequest(messages=[{"role": "user", "content": fixture["query"]}]))
    assert isinstance(captured.value.__cause__, httpx.ReadTimeout)
    assert client.post.call_count == 1


@pytest.mark.parametrize("status", [429, 401, 400, 503])
def test_http_errors_have_one_attempt_and_no_private_body_leak(monkeypatch, status):
    client = client_with(monkeypatch, {})
    client.post.return_value = httpx.Response(status, json={"error": "PRIVATE"},
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"))
    with pytest.raises(ProviderError) as captured:
        provider().chat(ChatRequest(messages=[]))
    assert client.post.call_count == 1
    assert "PRIVATE" not in str(captured.value)


def test_empty_generation_is_failure_even_with_usage(monkeypatch):
    client_with(monkeypatch, {"message": {"content": ""}, "eval_count": 4})
    with pytest.raises(ProviderError, match="empty model content"):
        provider().chat(ChatRequest(messages=[]))
