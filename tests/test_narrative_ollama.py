import json
from dataclasses import replace

import pytest

from core.answer_synthesis_narrative_ollama import LocalQwenNarrativeGenerator, reviewed_narrative_chunks
from core.answer_synthesis_semantic import EntailmentVerdict, SemanticClaimReview, SemanticReview, semantic_input_digest
from llm.providers.provider_models import ChatResponse
from tests.test_answer_synthesis_narrative import narrative_inputs

MODEL = "local/Qwen3.8:q4"


def test_completed_invalid_candidate_preserves_actual_usage(monkeypatch):
    from core.answer_synthesis_usage import AccountedCompletionFailure

    source, _ = narrative_inputs()
    response = ChatResponse('{"claims": []}', "ollama", MODEL, 100, 50, 150, {"done_reason": "stop"})
    monkeypatch.setattr("llm.adapters.ollama_provider.OllamaProvider.chat", lambda *_: response)
    generator = LocalQwenNarrativeGenerator(model=MODEL, enabled=True)
    with pytest.raises(AccountedCompletionFailure) as error:
        generator.generate(source)
    assert error.value.usage.total_tokens == 150
    assert generator.completion_receipts[0]["total_tokens"] == 150


def test_timeout_records_only_sanitized_failure_type_not_zero_usage(monkeypatch):
    source, _ = narrative_inputs()

    def timeout(*_):
        raise TimeoutError("sensitive fixture error message")

    monkeypatch.setattr("llm.adapters.ollama_provider.OllamaProvider.chat", timeout)
    generator = LocalQwenNarrativeGenerator(model=MODEL, enabled=True)
    with pytest.raises(TimeoutError):
        generator.generate(source)
    assert generator.failure_receipts == [{"phase": "generation", "error_type": "TimeoutError",
                                          "usage_complete": False}]
    assert generator.completion_receipts == []


def test_local_generator_is_disabled_without_explicit_opt_in():
    source, _ = narrative_inputs()
    with pytest.raises(ValueError, match="DISABLED"):
        LocalQwenNarrativeGenerator(model=MODEL).generate(source)


@pytest.mark.parametrize("changes", [{"provider": "deepseek"}, {"model": "other"},
    {"metadata": {"done_reason": "length"}}])
def test_untrusted_completion_identity_and_usage_are_rejected(monkeypatch, changes):
    source, candidate = narrative_inputs()
    response = ChatResponse(json.dumps(candidate), "ollama", MODEL, 100, 50, 150, {"done_reason": "stop"})
    monkeypatch.setattr("llm.adapters.ollama_provider.OllamaProvider.chat",
                        lambda *_: replace(response, **changes))
    with pytest.raises(ValueError):
        LocalQwenNarrativeGenerator(model=MODEL, enabled=True).generate(source)


def test_actual_adapter_port_returns_candidate_not_verified_answer(monkeypatch):
    source, candidate = narrative_inputs()
    seen = []

    def chat(_provider, request):
        seen.append(request)
        return ChatResponse(json.dumps(candidate), "ollama", MODEL, 100, 50, 150, {"done_reason": "stop"})

    monkeypatch.setattr("llm.adapters.ollama_provider.OllamaProvider.chat", chat)
    result = LocalQwenNarrativeGenerator(model=MODEL, enabled=True).generate(source, max_tokens=512)
    assert result.total_tokens == 150
    assert result.buffered.plan.claims[0].fact_status == "UNVERIFIED"
    assert seen[0].max_tokens == 512 and seen[0].deadline is not None
    assert "Simplified Chinese" in seen[0].system_prompt
    buffered = result.buffered
    review = SemanticReview("fixture-review", tuple(SemanticClaimReview(claim.claim_id, claim.evidence_ids,
        EntailmentVerdict.SUPPORTED, claim.causal_strength, "fixture support") for claim in buffered.plan.claims),
        semantic_input_digest(source, buffered.plan, buffered.text))
    assert ''.join(reviewed_narrative_chunks(source, result, review)) == buffered.text
    mutated = replace(result, buffered=replace(buffered, text="unreviewed answer"))
    stream = reviewed_narrative_chunks(source, mutated, review)
    with pytest.raises(ValueError, match="FINAL_NARRATIVE_REVIEW_FAILED"):
        next(stream)
