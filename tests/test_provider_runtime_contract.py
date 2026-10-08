"""Deterministic generation/telemetry/deadline separation."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from llm.adapters.deepseek_provider import DeepSeekProvider
from llm.adapters.openai_provider import OpenAIProvider
from llm.providers.provider_config import ProviderConfig, timeout_budget_for_provider
from llm.providers.provider_exceptions import ProviderTimeoutError
from llm.providers.provider_models import ChatRequest, ChatResponse, GenerationStatus, UsageStatus
from llm.providers.timeout_policy import effective_timeout


@pytest.mark.parametrize("counts,status", [
    ((10, 4, 14), UsageStatus.KNOWN),
    ((None, None, None), UsageStatus.UNKNOWN),
    ((10, None, None), UsageStatus.PARTIAL),
    (("bad", None, None), UsageStatus.UNKNOWN),
    ((0, 0, 0), UsageStatus.KNOWN),
])
def test_usage_cannot_change_generation_success(counts, status):
    result = ChatResponse("valid answer", "fixture", "any-model", *counts)
    assert result.generation_status == GenerationStatus.SUCCESS
    assert result.usage_status == status
    assert result.content == "valid answer"


def test_explicit_unsupported_usage():
    result = ChatResponse("valid", "fixture", "model", usage_status=UsageStatus.UNSUPPORTED)
    assert result.generation_status == GenerationStatus.SUCCESS
    assert result.total_tokens is None


@pytest.mark.parametrize("adapter", [OpenAIProvider, DeepSeekProvider])
def test_success_with_empty_usage_object(adapter):
    provider = adapter(ProviderConfig(provider="fixture", model="customer-model", api_key="fixture"))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(usage=SimpleNamespace(),
        choices=[SimpleNamespace(message=SimpleNamespace(content="valid"), finish_reason="stop")])
    provider._client = client
    response = provider.chat(ChatRequest([]))
    assert response.generation_status == GenerationStatus.SUCCESS
    assert response.usage_status == UsageStatus.UNKNOWN
    assert response.total_tokens is None


def test_local_wiring_does_not_increase_configured_timeout():
    assert timeout_budget_for_provider("ollama", timeout=60, read_timeout=45, total_deadline=120) == (60, 45)


@pytest.mark.parametrize("configured,remaining,expected", [(60, 20, 20), (60, 120, 60), (240, 30, 30)])
def test_shorter_timeout_wins(configured, remaining, expected):
    assert effective_timeout(configured, 100 + remaining, now=100) == expected


def test_expired_deadline_is_timeout_not_usage_failure():
    with pytest.raises(ProviderTimeoutError) as captured:
        effective_timeout(60, 99, now=100)
    assert captured.value.timeout_source == "TOTAL_REQUEST_DEADLINE"
    assert captured.value.generation_status == "TIMEOUT"
    assert captured.value.usage_status == "UNAVAILABLE"
    assert captured.value.cancellation_guaranteed is False


@pytest.mark.parametrize("remaining,expected", [(20, 20), (120, 60)])
def test_openai_request_deadline_uses_scoped_client(monkeypatch, remaining, expected):
    monkeypatch.setattr("llm.adapters.openai_provider.time.monotonic", lambda: 100)
    instance = OpenAIProvider(ProviderConfig(provider="openai", model="customer-model", api_key="fixture", timeout=60))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")])
    instance._client = client
    response = instance.chat(ChatRequest([], deadline=100 + remaining))
    assert client.with_options.call_args.kwargs["timeout"].read == expected
    assert response.generation_status == GenerationStatus.SUCCESS
    assert response.usage_status == UsageStatus.UNKNOWN


def test_openai_timeout_is_not_retried():
    instance = OpenAIProvider(ProviderConfig(provider="openai", model="model", api_key="fixture"))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = httpx.ReadTimeout("private transport message")
    instance._client = client
    with pytest.raises(ProviderTimeoutError) as captured:
        instance.chat(ChatRequest([]))
    assert client.chat.completions.create.call_count == 1
    assert "private" not in str(captured.value)


def test_native_stream_and_cancellation_are_not_claimed():
    from llm.adapters.ollama_provider import OllamaProvider
    for adapter in (OllamaProvider, OpenAIProvider, DeepSeekProvider):
        capability = adapter(ProviderConfig(provider="fixture", model="model", api_key="fixture")).get_capability()
        assert capability.supports_stream is False
        assert capability.supports_cancellation is False


@pytest.mark.parametrize("status", [429, 503, None])
def test_openai_transient_attempts_are_bounded(monkeypatch, status):
    class APIConnectionError(Exception):
        status_code = status
    instance = OpenAIProvider(ProviderConfig(provider="openai", model="model", api_key="fixture"))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = APIConnectionError("fixture")
    instance._client = client
    sleeps = []
    monkeypatch.setattr("llm.adapters.openai_provider.time.sleep", sleeps.append)
    with pytest.raises(Exception):
        instance.chat(ChatRequest([]))
    assert client.chat.completions.create.call_count == 3
    assert sleeps == [1, 2]


@pytest.mark.parametrize("status", [401, 403, 400, 422])
def test_openai_auth_and_invalid_request_are_not_retried(status):
    class StatusError(Exception):
        status_code = status
    instance = OpenAIProvider(ProviderConfig(provider="openai", model="model", api_key="fixture"))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = StatusError("fixture")
    instance._client = client
    with pytest.raises(Exception):
        instance.chat(ChatRequest([]))
    assert client.chat.completions.create.call_count == 1


@pytest.mark.parametrize("remaining,expected", [(20, 20), (120, 60)])
def test_deepseek_uses_same_configured_deadline(monkeypatch, remaining, expected):
    monkeypatch.setattr("llm.adapters.deepseek_provider.time.monotonic", lambda: 100)
    instance = DeepSeekProvider(ProviderConfig(provider="deepseek", model="customer-model", api_key="fixture",
        timeout=60))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")])
    instance._client = client
    response = instance.chat(ChatRequest([], deadline=100 + remaining))
    assert client.with_options.call_args.kwargs["timeout"].read == expected
    assert response.total_tokens is None
    assert response.generation_status == GenerationStatus.SUCCESS


@pytest.mark.parametrize("exception,expected", [
    (httpx.ConnectTimeout("fixture"), "CONNECTION_TIMEOUT"),
    (httpx.ReadTimeout("fixture"), "HTTP_TIMEOUT"),
])
def test_transport_timeout_has_truthful_classification(exception, expected):
    instance = OpenAIProvider(ProviderConfig(provider="openai", model="model", api_key="fixture"))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = exception
    instance._client = client
    with pytest.raises(ProviderTimeoutError) as caught:
        instance.chat(ChatRequest([]))
    assert caught.value.timeout_source == expected
    assert caught.value.cancellation_guaranteed is False
    assert client.chat.completions.create.call_count == 1


def test_hung_openai_transport_is_bounded_without_claiming_cancellation():
    import threading
    import time
    release = threading.Event()
    completed = threading.Event()
    calls = []

    def hung(**_):
        calls.append(1)
        release.wait(2)
        completed.set()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="late"), finish_reason="stop")])

    provider = OpenAIProvider(ProviderConfig(provider="openai", model="model", api_key="fixture", timeout=.03))
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = hung
    provider._client = client
    started = time.monotonic()
    try:
        with pytest.raises(ProviderTimeoutError) as caught:
            provider.chat(ChatRequest([]))
        assert time.monotonic() - started < .5
        assert caught.value.cancellation_guaranteed is False
        assert not completed.is_set()
        assert len(calls) == 1
    finally:
        release.set()
        assert completed.wait(.5)


def test_ollama_timeout_returns_before_deferred_transport_cleanup(monkeypatch):
    import threading

    from llm.adapters.ollama_provider import OllamaProvider
    release = threading.Event()
    closed = threading.Event()
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.side_effect = lambda *_: closed.set()
    client.post.side_effect = lambda *_a, **_k: release.wait(2)
    monkeypatch.setattr("llm.adapters.ollama_provider.httpx.Client", lambda **_: client)
    provider = OllamaProvider(ProviderConfig(provider="ollama", model="model", api_key="", timeout=.03))
    try:
        with pytest.raises(ProviderTimeoutError) as caught:
            provider.chat(ChatRequest([]))
        assert caught.value.cancellation_guaranteed is False
        assert not closed.is_set()
        assert client.post.call_count == 1
    finally:
        release.set()
        assert closed.wait(.5)


def test_deepseek_unknown_retry_usage_is_not_reported_as_complete(monkeypatch):
    calls = []

    def create(**_):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("connection interrupted")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20))

    monkeypatch.setattr("llm.adapters.deepseek_provider.time.sleep", lambda _: None)
    provider = DeepSeekProvider(ProviderConfig(provider="deepseek", model="customer-model", api_key="fixture"))
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response = provider.chat(ChatRequest([]))
    assert response.generation_status == GenerationStatus.SUCCESS
    assert response.usage_status == UsageStatus.UNKNOWN
    assert response.total_tokens is None
    assert response.metadata["attempt_usage"] == [None, {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}]
