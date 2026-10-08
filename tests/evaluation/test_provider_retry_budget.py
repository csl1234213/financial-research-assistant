"""No credentials/network: exercise the real SDK and adapter retry boundary."""

from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from llm.adapters.deepseek_provider import DeepSeekProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_models import ChatRequest


@pytest.mark.parametrize(
    "status,expected", [(429, "RateLimitError"), (503, "ProviderError"), ("timeout", "ProviderTimeoutError")]
)
def test_one_retry_owner_has_three_attempt_budget(status, expected):
    attempts, delays = [], []

    def transport(request):
        attempts.append(request)
        if status == "timeout":
            raise httpx.ReadTimeout("Injected timeout", request=request)
        return httpx.Response(
            status, headers={"Retry-After": "0.1"}, json={"error": {"message": "PRIVATE_PROVIDER_BODY"}}
        )

    def client_factory(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(transport)))

    provider = DeepSeekProvider(ProviderConfig(provider="deepseek", model="deepseek-v4-flash", api_key="test-only"))
    with (
        patch("llm.adapters.deepseek_provider.OpenAI", side_effect=client_factory),
        patch("time.sleep", side_effect=delays.append),
    ):
        with pytest.raises(Exception) as captured:
            provider.chat(ChatRequest(messages=[{"role": "user", "content": "test"}]))
    assert len(attempts) == (1 if status == "timeout" else 3)
    assert len(delays) == (0 if status == "timeout" else 2)
    assert type(captured.value).__name__ == expected
    assert "PRIVATE_PROVIDER_BODY" not in str(captured.value)
    assert all(0 < d <= 60 for d in delays)
    provider._client.close()


@pytest.mark.parametrize("status", [401, 402, 404])
def test_non_retryable_status_fails_without_backoff(status):
    attempts = []

    def transport(request):
        attempts.append(request)
        return httpx.Response(status, json={"error": {"message": "test error"}})

    def client_factory(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(transport)))

    provider = DeepSeekProvider(ProviderConfig(provider="deepseek", model="deepseek-v4-flash", api_key="test-only"))
    with patch("llm.adapters.deepseek_provider.OpenAI", side_effect=client_factory), patch("time.sleep") as sleep:
        with pytest.raises(Exception):
            provider.chat(ChatRequest(messages=[{"role": "user", "content": "test"}]))
    assert len(attempts) == 1
    sleep.assert_not_called()
    provider._client.close()
