from types import SimpleNamespace

import pytest

from llm.adapters.deepseek_provider import DeepSeekProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import ProviderError
from llm.providers.provider_models import ChatRequest


def test_real_provider_guard_blocks_production_process_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted DeepSeek route cannot spend while the guard is disabled."""

    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "false")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    provider = DeepSeekProvider(
        ProviderConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="test-only-key",
        )
    )

    with pytest.raises(ProviderError, match="Real provider calls are disabled"):
        provider._get_client()


def test_v4_chat_uses_the_official_thinking_request_contract() -> None:
    calls: list[dict[str, object]] = []

    def create_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="final answer"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=8,
                total_tokens=20,
            ),
        )

    provider = DeepSeekProvider(
        ProviderConfig(
            provider="deepseek",
            model="deepseek-v4-pro",
            api_key="test-only-key",
            temperature=0.7,
        )
    )
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_completion),
        )
    )

    response = provider.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "Hello"}],
            temperature=0.7,
        )
    )

    assert response.content == "final answer"
    assert response.model == "deepseek-v4-pro"
    assert calls == [
        {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 4096,
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled"}},
        }
    ]


def test_explicit_structured_answer_mode_disables_thinking_without_recovery():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="bounded output"), finish_reason="length")],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20))
    provider = DeepSeekProvider(ProviderConfig(provider="deepseek", model="deepseek-v4-flash",
                                             api_key="test-only-key"))
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response = provider.chat(ChatRequest(messages=[{"role": "user", "content": "JSON"}],
                                        thinking_enabled=False, max_tokens=1024))
    assert len(calls) == 1
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in calls[0]
    assert calls[0]["max_tokens"] == 1024
    assert response.metadata["api_attempts"] == 1


def test_failed_attempt_usage_is_unknown_not_zero(monkeypatch):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("connection interrupted")
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="answer"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20))
    monkeypatch.setattr("llm.adapters.deepseek_provider.time.sleep", lambda _: None)
    provider = DeepSeekProvider(ProviderConfig(provider="deepseek", model="deepseek-v4-flash",
                                             api_key="test-only-key"))
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    response = provider.chat(ChatRequest(messages=[{"role": "user", "content": "JSON"}],
                                        thinking_enabled=False))
    assert response.metadata["api_attempts"] == 2
    assert response.metadata["attempt_usage"] == [None,
        {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}]
    assert response.metadata["all_attempt_usage_complete"] is False


def test_v4_empty_length_response_recovers_with_bounded_answer_request() -> None:
    calls: list[dict[str, object]] = []

    def create_completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=""),
                        finish_reason="length",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=4096,
                    total_tokens=4106,
                ),
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="recovered answer"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=12,
                total_tokens=22,
            ),
        )

    provider = DeepSeekProvider(
        ProviderConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="test-only-key",
            max_tokens=8192,
        )
    )
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_completion),
        )
    )

    response = provider.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "Summarize the filing"}],
            max_tokens=8192,
        )
    )

    assert response.content == "recovered answer"
    assert len(calls) == 2
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[1]["max_tokens"] == 2048
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert response.metadata["api_attempts"] == 2
    assert response.metadata["all_attempt_usage_complete"] is True
    assert response.metadata["attempt_usage"] == [
        {"prompt_tokens": 10, "completion_tokens": 4096, "total_tokens": 4106},
        {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
    ]
