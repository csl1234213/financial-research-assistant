import config
import llm.provider as provider_module
from llm.provider import call_llm
from llm.providers.provider_models import ChatResponse


class _SelectedProvider:
    provider_name = "selected"

    def __init__(self):
        self.requests = []

    def chat(self, request):
        self.requests.append(request)
        return ChatResponse(
            content="selected response",
            provider="selected",
            model="selected-model",
        )


def test_call_llm_uses_the_runtime_selected_provider():
    provider = _SelectedProvider()

    answer = call_llm("Summarize the report", provider=provider)

    assert answer == "selected response"
    assert len(provider.requests) == 1
    assert provider.requests[0].messages[0]["content"] == "Summarize the report"


def test_legacy_provider_imports_generation_defaults_from_public_config():
    assert provider_module.LLM_TEMPERATURE == config.LLM_TEMPERATURE
    assert provider_module.LLM_MAX_TOKENS == config.LLM_MAX_TOKENS


def test_call_llm_uses_the_public_config_generation_parameters(monkeypatch):
    provider = _SelectedProvider()
    monkeypatch.setattr(provider_module, "LLM_TEMPERATURE", 0.37)
    monkeypatch.setattr(provider_module, "LLM_MAX_TOKENS", 2048)

    call_llm("Use configured generation parameters", provider=provider)

    request = provider.requests[0]
    assert request.temperature == 0.37
    assert request.max_tokens == 2048
