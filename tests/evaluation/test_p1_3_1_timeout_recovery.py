"""Deterministic provider deadline/cancellation tests; no network or credentials."""

import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

from llm.adapters.deepseek_provider import DeepSeekProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import ProviderTimeoutError
from llm.providers.provider_models import ChatRequest


def _response(content: str = "answer"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
    )


def _provider(client, *, deadline: float = 0.2) -> DeepSeekProvider:
    provider = DeepSeekProvider(
        ProviderConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="offline-test-only",
            connect_timeout=0.05,
            read_timeout=0.1,
            total_deadline=deadline,
        )
    )
    provider._client = client
    return provider


def _client(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_normal_provider_completes_before_total_deadline():
    provider = _provider(_client(lambda **_: _response()))
    result = provider.chat(ChatRequest(messages=[{"role": "user", "content": "test"}]))
    assert result.content == "answer"


def test_slow_but_valid_provider_is_not_cancelled_early():
    def create(**_):
        time.sleep(0.02)
        return _response("slow answer")

    provider = _provider(_client(create), deadline=0.2)
    assert provider.chat(ChatRequest(messages=[])).content == "slow answer"


def test_hanging_provider_is_cancelled_by_total_deadline():
    def create(**_):
        time.sleep(2)
        return _response("late answer")

    provider = _provider(_client(create), deadline=0.05)
    started = time.monotonic()
    with pytest.raises(ProviderTimeoutError):
        provider.chat(ChatRequest(messages=[]))
    assert time.monotonic() - started < 0.5


def test_read_timeout_does_not_restart_a_fresh_total_budget():
    attempts = 0

    def create(**_):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("offline read timeout")

    provider = _provider(_client(create), deadline=0.05)
    with pytest.raises(ProviderTimeoutError):
        provider.chat(ChatRequest(messages=[]))
    assert 1 <= attempts <= 3


def test_connect_timeout_uses_shared_retry_budget():
    attempts = 0

    def create(**_):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("offline connect timeout")

    provider = _provider(_client(create), deadline=0.05)
    with pytest.raises(ProviderTimeoutError):
        provider.chat(ChatRequest(messages=[]))
    assert 1 <= attempts <= 3


def test_timeout_then_next_request_is_clean():
    calls = 0

    def hanging(**_):
        time.sleep(1)
        return _response("late")

    timed_out = _provider(_client(hanging), deadline=0.02)
    with pytest.raises(ProviderTimeoutError):
        timed_out.chat(ChatRequest(messages=[]))

    def healthy(**_):
        nonlocal calls
        calls += 1
        return _response("fresh")

    healthy_provider = _provider(_client(healthy), deadline=0.2)
    assert healthy_provider.chat(ChatRequest(messages=[])).content == "fresh"
    assert calls == 1


def test_provider_timeout_has_explicit_504_contract():
    from api.routers.chat import chat, chat_service
    from api.schemas.request import ChatRequest as APIChatRequest

    with patch.object(chat_service, "chat", side_effect=ProviderTimeoutError("deadline")):
        with pytest.raises(HTTPException) as caught:
            chat(APIChatRequest(question="offline"), None, None, None)
    assert caught.value.status_code == 504
