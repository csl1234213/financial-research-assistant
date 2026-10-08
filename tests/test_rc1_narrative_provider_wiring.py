"""Request-owned formal ports; no network, secrets or answer semantics changed."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.rc1_delivery import resolve_narrative_ports


@pytest.mark.parametrize("name,model", [("deepseek", "configured-cloud"), ("ollama", "customer-local")])
def test_narrative_ports_resolve_user_config_without_model_switches(monkeypatch, name, model):
    session = MagicMock()
    runtime = SimpleNamespace(repository=SimpleNamespace(session_factory=session))
    monkeypatch.setattr("services.rc1_delivery.get_delivery", lambda: runtime)
    settings = SimpleNamespace(default_provider=name, provider_models={name: model},
        provider_configs={name: {"api_key": "test-only-not-live", "base_url": "http://localhost:1234"}})
    lookup = MagicMock(return_value=settings)
    monkeypatch.setattr("services.llm_settings_service.get_runtime_llm_settings", lookup)
    provider = SimpleNamespace(model=model)
    factory = MagicMock(return_value=provider)
    monkeypatch.setattr("llm.factory.provider_factory.ProviderFactory.create", factory)
    generator = MagicMock()
    reviewer = MagicMock()
    monkeypatch.setattr("core.answer_synthesis_narrative_ollama.LocalQwenNarrativeGenerator", generator)
    monkeypatch.setattr("core.answer_synthesis_semantic_ollama.LocalQwenEntailmentReviewer", reviewer)
    from config.llm import LLM_TIMEOUT, LLM_TOTAL_DEADLINE

    resolve_narrative_ports(tenant_id=7, user_id=9)
    assert lookup.call_args.kwargs == {"tenant_id": 7, "user_id": 9}
    config = factory.call_args.args[0]
    assert (config.provider, config.model, config.base_url) == (name, model, "http://localhost:1234")
    assert config.timeout == LLM_TIMEOUT and config.total_deadline == LLM_TOTAL_DEADLINE
    assert generator.call_args.kwargs == {"provider": provider, "enabled": True,
        "compact_references": True, "request_purpose": "STRUCTURED_GENERATION"}
    assert reviewer.call_args.kwargs == {"provider": provider, "enabled": True,
        "compact_references": True, "request_purpose": "STRUCTURED_REVIEW"}


def test_missing_user_provider_fails_closed(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr("services.rc1_delivery.get_delivery", lambda: SimpleNamespace(
        repository=SimpleNamespace(session_factory=session)))
    monkeypatch.setattr("services.llm_settings_service.get_runtime_llm_settings", lambda *a, **k:
        SimpleNamespace(default_provider=None, provider_models={}, provider_configs={}))
    with pytest.raises(ValueError, match="NARRATIVE_PROVIDER_NOT_CONFIGURED"):
        resolve_narrative_ports(tenant_id=1, user_id=2)
