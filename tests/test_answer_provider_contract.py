"""Provider/model/endpoint switching without changing financial semantics."""
import ast
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.answer_synthesis_narrative import assemble_narrative
from core.answer_synthesis_narrative_ollama import LocalQwenNarrativeGenerator
from core.answer_synthesis_narrative_workflow import synthesize_narrative, verified_narrative_outcome_chunks
from core.answer_synthesis_ollama import LocalQwenDraftGenerator
from core.answer_synthesis_semantic import validate_grounded_answer_review
from core.answer_synthesis_semantic_ollama import LocalQwenEntailmentReviewer
from core.answer_synthesis_usage import AccountedCompletionFailure
from core.answer_synthesis_workflow import BoundedSynthesisWorkflow
from llm.providers.base_provider import BaseProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import ProviderTimeoutError, StructuredOutputError
from llm.providers.provider_models import ChatResponse, ProviderCapability
from llm.providers.provider_registry import ProviderRegistry
from tests.test_answer_synthesis_ollama import request as draft_request
from tests.test_narrative_ollama import narrative_inputs


def registered_fixture(monkeypatch, *, usage="full", malformed=False, unsupported=False):
    source, candidate = narrative_inputs()

    class FixtureProvider(BaseProvider):
        def __init__(self, config):
            self.config = config
            self.requests = []

        @property
        def provider_name(self):
            return self.config.provider

        @property
        def model(self):
            return self.config.model

        def get_capability(self):
            return ProviderCapability(supports_system_prompt=True, supports_usage=usage != "unsupported")

        def health(self):
            return True

        def list_models(self):
            return [self.model]

        def chat(self, request):
            self.requests.append(request)
            try:
                data = json.loads(request.messages[0]["content"])
            except ValueError:
                # The existing closed fact grammar remains the correctness gate.
                content = request.messages[0]["content"].split("Grounded factual answer:\n", 1)[1]
            else:
                if "draft" in data:
                    content = json.dumps({"claims": [{"claim_id": claim["claim_id"],
                        "evidence_ids": claim["evidence_ids"],
                        "verdict": "UNSUPPORTED" if unsupported else "SUPPORTED",
                        "causal_strength": claim["claimed_causal_strength"], "rationale": "fixture evidence"}
                        for claim in data["claims"]]})
                else:
                    content = "{invalid" if malformed else json.dumps(candidate)
            counts = (100, 20, 120) if usage == "full" else (100, None, None) if usage == "partial" else (None, None, None)
            return ChatResponse(content, self.provider_name, self.model, *counts,
                metadata={"finish_reason": "stop"},
                usage_status="UNSUPPORTED" if usage == "unsupported" else None)

    for name in ("fixture_a", "fixture_b"):
        monkeypatch.setitem(ProviderRegistry._registry, name, FixtureProvider)
    return source, candidate


def config(name):
    return ProviderConfig(provider="fixture_" + name, model="customer-model-" + name,
        api_key="", base_url="http://localhost:1234/" + name, timeout=60)


@pytest.mark.parametrize("port_kind", ["draft", "narrative", "review"])
def test_all_three_ports_switch_only_configuration_and_preserve_prompts(monkeypatch, port_kind):
    source, candidate = registered_fixture(monkeypatch)
    results, prompts = [], []
    for name in ("a", "b"):
        if port_kind == "draft":
            port = LocalQwenDraftGenerator(provider_config=config(name), enabled=True)
            result = port.generate(draft_request())
            results.append(result.text)
        elif port_kind == "narrative":
            port = LocalQwenNarrativeGenerator(provider_config=config(name), enabled=True)
            result = port.generate(source)
            results.append(result.buffered.text)
        else:
            port = LocalQwenEntailmentReviewer(provider_config=config(name), enabled=True)
            buffered = assemble_narrative(source, candidate)
            result = port.review(source, buffered.plan, buffered.text)
            assert validate_grounded_answer_review(source, buffered.plan, result, buffered.text)
            results.append(result.claims)
        sent = port.provider.requests[0]
        prompts.append((sent.system_prompt, sent.messages))
        assert port.provider.config.base_url.endswith("/" + name)
        assert "qwen" not in port.model.casefold()
    assert results[0] == results[1]
    assert prompts[0] == prompts[1]


@pytest.mark.parametrize("usage", ["full", "missing", "partial", "unsupported"])
def test_valid_reviewed_answer_releases_without_usage(monkeypatch, usage):
    source, _ = registered_fixture(monkeypatch, usage=usage)
    generator = LocalQwenNarrativeGenerator(provider_config=config("a"), enabled=True)
    reviewer = LocalQwenEntailmentReviewer(provider_config=config("b"), enabled=True)
    result = synthesize_narrative(source, generator=generator, reviewer=reviewer, enabled=True)
    assert result.reason == "REVIEWED_NARRATIVE"
    assert result.generation_status == "SUCCESS"
    assert "".join(verified_narrative_outcome_chunks(source, result)) == result.text
    if usage != "full":
        assert result.total_tokens is None
        assert result.usage_complete is False
        assert result.usage_status == "UNKNOWN"


def test_valid_fact_draft_releases_without_usage(monkeypatch):
    registered_fixture(monkeypatch, usage="missing")
    incoming = draft_request()
    generator = LocalQwenDraftGenerator(provider_config=config("a"), enabled=True)
    result = BoundedSynthesisWorkflow().run(incoming.source, incoming.plan, generator=generator, enabled=True)
    assert result.mode == "VERIFIED_FACT_DRAFT"
    assert result.total_tokens is None


@pytest.mark.parametrize("failure", ["schema", "review"])
def test_usage_does_not_authorize_invalid_schema_or_failed_review(monkeypatch, failure):
    source, _ = registered_fixture(monkeypatch, malformed=failure == "schema", unsupported=failure == "review")
    result = synthesize_narrative(source,
        generator=LocalQwenNarrativeGenerator(provider_config=config("a"), enabled=True),
        reviewer=LocalQwenEntailmentReviewer(provider_config=config("b"), enabled=True),
        enabled=True, max_revisions=0)
    assert result.text is None
    if failure == "schema":
        assert result.failure_class == "STRUCTURED_OUTPUT_ERROR"
        assert result.reason == "STRUCTURED_OUTPUT_ERROR"


def test_historical_timeout_has_separate_statuses_and_no_retry(monkeypatch):
    source, _ = registered_fixture(monkeypatch)
    generator = LocalQwenNarrativeGenerator(provider_config=config("a"), enabled=True)
    calls = []

    def timed_out(*_):
        calls.append(1)
        raise ProviderTimeoutError("fixture timeout")

    monkeypatch.setattr(generator.provider, "chat", timed_out)
    result = synthesize_narrative(source, generator=generator,
        reviewer=LocalQwenEntailmentReviewer(provider_config=config("b"), enabled=True), enabled=True)
    assert result.reason == "GENERATION_TIMEOUT"
    assert result.generation_status == result.failure_class == "TIMEOUT"
    assert result.usage_status == "UNAVAILABLE"
    assert len(calls) == 1


def test_usage_metadata_cannot_revoke_verified_release(monkeypatch):
    source, _ = registered_fixture(monkeypatch)
    outcome = synthesize_narrative(source,
        generator=LocalQwenNarrativeGenerator(provider_config=config("a"), enabled=True),
        reviewer=LocalQwenEntailmentReviewer(provider_config=config("b"), enabled=True), enabled=True)
    outcome = replace(outcome, total_tokens=None, usage_complete=False, usage_status="UNKNOWN")
    assert "".join(verified_narrative_outcome_chunks(source, outcome)) == outcome.text


def test_ports_do_not_inspect_model_tags_or_instantiate_adapters():
    root = Path(__file__).resolve().parent.parent
    for name in ("answer_synthesis_ollama", "answer_synthesis_narrative_ollama", "answer_synthesis_semantic_ollama"):
        text = (root / "core" / (name + ".py")).read_text(encoding="utf-8")
        assert "qwen3.8" not in text.casefold()
        tree = ast.parse(text)
        assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("llm.adapters")
                       for node in ast.walk(tree))


@pytest.mark.parametrize("port_kind", ["draft", "narrative", "review"])
def test_ports_use_explicitly_injected_provider(monkeypatch, port_kind):
    source, candidate = registered_fixture(monkeypatch)
    provider = LocalQwenDraftGenerator(provider_config=config("a"), enabled=True).provider

    def forbidden(*_):
        raise AssertionError("Factory must not replace the injected Provider")

    monkeypatch.setattr("core.answer_provider_port.ProviderFactory.create", forbidden)
    if port_kind == "draft":
        LocalQwenDraftGenerator(provider=provider, enabled=True).generate(draft_request())
    elif port_kind == "narrative":
        LocalQwenNarrativeGenerator(provider=provider, enabled=True).generate(source)
    else:
        draft = assemble_narrative(source, candidate)
        LocalQwenEntailmentReviewer(provider=provider, enabled=True).review(source, draft.plan, draft.text)
    assert len(provider.requests) == 1


@pytest.mark.parametrize("remaining,expected", [(20, 20), (120, 60)])
def test_narrative_uses_provider_deadline_policy(monkeypatch, remaining, expected):
    source, candidate = narrative_inputs()
    captured = []
    monkeypatch.setattr("time.monotonic", lambda: 100)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"model": "customer-model", "message": {"content": json.dumps(candidate)},
        "prompt_eval_count": 100, "eval_count": 20, "done_reason": "stop"}
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response

    def factory(**kwargs):
        captured.append(kwargs["timeout"])
        return client

    monkeypatch.setattr("llm.adapters.ollama_provider.httpx.Client", factory)
    generator = LocalQwenNarrativeGenerator(provider_config=ProviderConfig(provider="ollama",
        model="customer-model", base_url="http://127.0.0.1:11434", api_key="", timeout=60), enabled=True)
    generator.generate(source, max_seconds=remaining)
    assert captured[0].read == expected
    client.__exit__.assert_called_once()


def test_batched_review_without_usage_preserves_verified_output(monkeypatch):
    from core.answer_synthesis_batched_reviewer import BatchedNarrativeReviewer
    source, candidate = registered_fixture(monkeypatch, usage="missing")
    buffered = assemble_narrative(source, candidate)
    reviewer = BatchedNarrativeReviewer(LocalQwenEntailmentReviewer(provider_config=config("a"), enabled=True),
        max_total_tokens=32768)
    result = reviewer.review(source, buffered.plan, buffered.text)
    assert result.total_tokens is None
    assert validate_grounded_answer_review(source, buffered.plan, result, buffered.text)


@pytest.mark.parametrize("usage", ["full", "missing"])
@pytest.mark.parametrize("content", ["{invalid", "```json\n{}\n```"])
def test_strict_narrative_structured_failure_does_not_retry(monkeypatch, usage, content):
    source, _ = registered_fixture(monkeypatch, usage=usage)
    generator = LocalQwenNarrativeGenerator(provider_config=config("a"), enabled=True)
    calls = []

    def malformed(_):
        calls.append(1)
        counts = (100, 20, 120) if usage == "full" else (None, None, None)
        return ChatResponse(content, generator.provider.provider_name, generator.provider.model, *counts,
            metadata={"finish_reason": "stop"})

    monkeypatch.setattr(generator.provider, "chat", malformed)
    with pytest.raises((StructuredOutputError, AccountedCompletionFailure)) as caught:
        generator.generate(source)
    assert caught.value.failure_class == "STRUCTURED_OUTPUT_ERROR"
    assert len(calls) == 1
