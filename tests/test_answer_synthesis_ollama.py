import time
from dataclasses import replace

import pytest

from core.answer_synthesis_ollama import LocalQwenDraftGenerator
from core.answer_synthesis_planner import DeterministicAnswerPlanner
from core.answer_synthesis_renderer import RestrictedAnswerRenderer
from core.answer_synthesis_workflow import DraftRequest
from llm.providers.provider_models import ChatResponse, ProviderCapability
from tests.test_answer_synthesis_renderer import ready_input

MODEL = "srchmnmichael/Qwen3.8-Uncensored:Q4_K_M"


def request():
    source = ready_input()
    plan = DeterministicAnswerPlanner().plan(source)
    return DraftRequest(
        source, plan, RestrictedAnswerRenderer().render(source, plan), 0, (), 4096, 96, time.monotonic() + 60
    )


@pytest.mark.parametrize("url", ["https://api.deepseek.com", "http://example.com:11434", "http://localhost/private"])
def test_cloud_or_arbitrary_endpoints_rejected(url):
    with pytest.raises(ValueError):
        LocalQwenDraftGenerator(model=MODEL, base_url=url, enabled=True)


def test_disabled_generator_does_not_construct_network_client(monkeypatch):
    monkeypatch.setattr(
        "llm.adapters.ollama_provider.OllamaProvider.chat", lambda *args: pytest.fail("network client created")
    )
    with pytest.raises(ValueError, match="disabled"):
        LocalQwenDraftGenerator(model=MODEL).generate(request())


def test_model_usage_deadline_and_output_limit(monkeypatch):
    requests = []

    class Provider:
        model = MODEL
        provider_name = "ollama"

        def __init__(self, config):
            assert config.provider == "ollama" and config.api_key == ""

        def get_capability(self):
            return ProviderCapability(supports_system_prompt=True)

        def chat(self, incoming):
            requests.append(incoming)
            return ChatResponse(
                provider="ollama",
                model=MODEL,
                content="draft",
                prompt_tokens=50,
                completion_tokens=10,
                total_tokens=60,
                metadata={"done_reason": "stop"},
            )

    monkeypatch.setattr("core.answer_provider_port.ProviderFactory.create", Provider)
    incoming = request()
    result = LocalQwenDraftGenerator(model=MODEL, enabled=True).generate(incoming)
    assert result.total_tokens == 60
    assert requests[0].max_tokens <= 96 and abs(requests[0].deadline - incoming.deadline) < .01


def test_exhausted_budget_never_constructs_provider(monkeypatch):
    monkeypatch.setattr(
        "llm.adapters.ollama_provider.OllamaProvider.chat", lambda *args: pytest.fail("network client created")
    )
    with pytest.raises(ValueError):
        LocalQwenDraftGenerator(model=MODEL, enabled=True).generate(replace(request(), remaining_total_tokens=1))


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "deepseek"},
        {"model": "qwen3.5:9b"},
        {"metadata": {"done_reason": "length"}},
    ],
)
def test_model_identity_usage_and_truncation_cannot_pass(changes, monkeypatch):
    response = {
        "provider": "ollama",
        "model": MODEL,
        "content": "draft",
        "prompt_tokens": 50,
        "completion_tokens": 10,
        "total_tokens": 60,
        "metadata": {"done_reason": "stop"},
    }
    response.update(changes)

    class Provider:
        model = MODEL
        provider_name = "ollama"

        def __init__(self, config):
            pass

        def get_capability(self):
            return ProviderCapability(supports_system_prompt=True)

        def chat(self, incoming):
            return ChatResponse(**response)

    monkeypatch.setattr("core.answer_provider_port.ProviderFactory.create", Provider)
    with pytest.raises(ValueError):
        LocalQwenDraftGenerator(model=MODEL, enabled=True).generate(request())
