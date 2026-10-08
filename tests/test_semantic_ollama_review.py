import json

import pytest

from core.answer_synthesis_semantic import validate_semantic_review
from core.answer_synthesis_semantic_ollama import LocalQwenEntailmentReviewer, parse_local_review
from llm.providers.provider_models import ChatResponse
from tests.test_answer_synthesis_workflow import inputs


def test_review_wire_budget_remains_finite_and_rejects_before_transport():
    from core.answer_synthesis_semantic_ollama import (
        SEMANTIC_REVIEW_INPUT_MAX_BYTES,
        build_semantic_review_prompt,
    )
    source, plan = inputs()
    assert SEMANTIC_REVIEW_INPUT_MAX_BYTES == 32768
    assert SEMANTIC_REVIEW_INPUT_MAX_BYTES <= 65536
    with pytest.raises(ValueError, match="semantic input exceeds") as caught:
        build_semantic_review_prompt(source, plan, "x" * SEMANTIC_REVIEW_INPUT_MAX_BYTES)
    assert caught.value.input_bytes > SEMANTIC_REVIEW_INPUT_MAX_BYTES


def test_local_review_disabled_by_default():
    source, plan = inputs()
    reviewer = LocalQwenEntailmentReviewer(model="local/Qwen3.8:q4")
    with pytest.raises(ValueError, match="disabled"):
        reviewer.review(source, plan, "draft")


def test_review_reports_authoritative_usage_and_requested_limits(monkeypatch):
    source, plan = inputs()
    claim = plan.claims[0]
    payload = {"claims": [{"claim_id": claim.claim_id, "evidence_ids": list(claim.evidence_ids),
        "verdict": "SUPPORTED", "causal_strength": "UNSUPPORTED", "rationale": "explicit observation"}]}
    model = "local/Qwen3.8:q4"
    requests = []

    def chat(_provider, request):
        requests.append(request)
        return ChatResponse(json.dumps(payload), "ollama", model, 100, 20, 120, {"done_reason": "stop"})

    monkeypatch.setattr("llm.adapters.ollama_provider.OllamaProvider.chat", chat)
    result = LocalQwenEntailmentReviewer(model=model, enabled=True).review(source, plan, "draft",
        max_seconds=10, max_tokens=128)
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (100, 20, 120)
    assert requests[0].max_tokens == 128 and requests[0].deadline is not None
    sent = json.loads(requests[0].messages[0]["content"])
    assert sent["locale"] == source.locale
    assert sent["required_dimensions"] == dict(source.required_dimensions)
    assert "caveat" in sent["claims"][0]
    assert "lexical presence of a number is not sufficient" in requests[0].system_prompt
    assert validate_semantic_review(source, plan, result, "draft")


def test_strict_review_response_is_bound_to_exact_draft():
    source, plan = inputs()
    claim = plan.claims[0]
    payload = {"claims": [{"claim_id": claim.claim_id, "evidence_ids": list(claim.evidence_ids),
        "verdict": "SUPPORTED", "causal_strength": "UNSUPPORTED", "rationale": "explicit observation"}]}
    result = parse_local_review(json.dumps(payload), source, plan, "draft", "fixture-not-model-evidence")
    assert validate_semantic_review(source, plan, result, "draft")
    assert not validate_semantic_review(source, plan, result, "changed draft")
    fenced = parse_local_review('```json\n' + json.dumps(payload) + '\n```', source, plan, "draft", "fixture")
    assert validate_semantic_review(source, plan, fenced, "draft")
    with pytest.raises(ValueError):
        parse_local_review('unreviewed prose\n```json\n' + json.dumps(payload) + '\n```',
                           source, plan, "draft", "fixture")


@pytest.mark.parametrize("text", ['{"claims":[],"extra":true}', 'not json', '{"claims":"wrong"}',
    '{"claims":null,"claims":[]}', '{"claims":[],"claims":[]}',
    '{"claims":NaN}', '{"claims":Infinity}',
    '{"claims":[{"claim_id":"wrong","claim_id":"correct"}]}'])
def test_malformed_model_output_fails_closed(text):
    source, plan = inputs()
    with pytest.raises((ValueError, TypeError)):
        parse_local_review(text, source, plan, "draft", "fixture")
