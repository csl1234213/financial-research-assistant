from types import SimpleNamespace

from llm.adapters.claude_provider import ClaudeProvider
from llm.adapters.doubao_provider import DoubaoProvider
from llm.adapters.gemini_provider import GeminiProvider
from llm.adapters.openai_provider import OpenAIProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_models import ChatRequest


class _FakeCreate:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _openai_response(content: str = "answer"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
        ),
    )


def test_openai_reasoning_models_use_official_completion_parameters():
    provider = OpenAIProvider(
        ProviderConfig(
            provider="openai",
            model="gpt-5.5",
            api_key="test-openai-key",
        )
    )
    create = _FakeCreate(_openai_response())
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=create)
    )

    response = provider.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt="system",
            temperature=0.7,
            max_tokens=256,
        )
    )

    assert response.provider == "openai"
    assert response.total_tokens == 18
    assert create.calls == [
        {
            "model": "gpt-5.5",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
            ],
            "max_completion_tokens": 256,
            "reasoning_effort": "medium",
        }
    ]
    assert provider.list_models() == [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
    ]
    assert provider.get_capability().max_context_tokens == 1_050_000


def test_doubao_uses_volcengine_seed_2_model_contract():
    provider = DoubaoProvider(
        ProviderConfig(
            provider="doubao",
            model="doubao-seed-2-0-pro-260215",
            api_key="test-doubao-key",
        )
    )
    create = _FakeCreate(_openai_response("豆包回答"))
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=create)
    )

    response = provider.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "你好"}],
            temperature=0.2,
            max_tokens=128,
        )
    )

    assert response.content == "豆包回答"
    assert create.calls[0]["model"] == "doubao-seed-2-0-pro-260215"
    assert create.calls[0]["temperature"] == 0.2
    assert create.calls[0]["max_tokens"] == 128
    assert provider._base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert provider.list_models() == [
        "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-0-lite-260215",
        "doubao-seed-2-0-mini-260215",
    ]


def test_anthropic_uses_messages_api_and_top_level_system_prompt():
    anthropic_response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Claude "),
            SimpleNamespace(type="text", text="answer"),
        ],
        usage=SimpleNamespace(input_tokens=9, output_tokens=5),
        stop_reason="end_turn",
    )
    provider = ClaudeProvider(
        ProviderConfig(
            provider="anthropic",
            model="claude-sonnet-5",
            api_key="test-anthropic-key",
        )
    )
    create = _FakeCreate(anthropic_response)
    provider._client = SimpleNamespace(messages=create)

    response = provider.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt="system",
            max_tokens=64,
        )
    )

    assert response.content == "Claude answer"
    assert response.prompt_tokens == 9
    assert response.completion_tokens == 5
    assert create.calls == [
        {
            "model": "claude-sonnet-5",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.0,
            "max_tokens": 64,
            "system": "system",
        }
    ]
    assert "claude-haiku-4-5-20251001" in provider.list_models()
    assert provider.get_capability().max_context_tokens == 1_000_000
    haiku = ClaudeProvider(
        ProviderConfig(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            api_key="test-anthropic-key",
        )
    )
    assert haiku.get_capability().max_context_tokens == 200_000


def test_gemini_3_models_omit_deprecated_temperature():
    gemini_response = SimpleNamespace(
        text="Gemini answer",
        usage_metadata=SimpleNamespace(
            prompt_token_count=4,
            candidates_token_count=3,
            total_token_count=7,
        ),
        candidates=[],
    )
    calls = []

    class _Models:
        @staticmethod
        def generate_content(**kwargs):
            calls.append(kwargs)
            return gemini_response

    provider = GeminiProvider(
        ProviderConfig(
            provider="gemini",
            model="gemini-3.6-flash",
            api_key="test-gemini-key",
        )
    )
    provider._client = SimpleNamespace(models=_Models())

    response = provider.chat(
        ChatRequest(
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.9,
            max_tokens=96,
        )
    )

    assert response.content == "Gemini answer"
    assert calls[0]["config"].temperature is None
    assert calls[0]["config"].max_output_tokens == 96
    assert provider.list_models() == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]
