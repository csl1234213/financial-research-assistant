"""Cloud-port contracts use injected responses, never network credentials."""

import json
from dataclasses import replace

import pytest

from core.answer_synthesis_deepseek import DeepSeekSynthesisPorts
from core.answer_synthesis_narrative import assemble_narrative
from core.answer_synthesis_narrative_ollama import LocalQwenNarrativeGenerator
from core.answer_synthesis_reference_transport import CompactEvidenceReferences
from core.answer_synthesis_semantic_ollama import LocalQwenEntailmentReviewer, build_semantic_review_prompt
from core.answer_synthesis_usage import AccountedCompletionFailure, ProviderPreflightFailure
from llm.providers.provider_models import ChatResponse
from tests.test_answer_synthesis_narrative import narrative_inputs


def test_disabled_port_never_calls_provider(monkeypatch):
    source, _ = narrative_inputs()
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat",
                        lambda *_: pytest.fail("network must not be called"))
    with pytest.raises(ValueError, match="DISABLED"):
        DeepSeekSynthesisPorts(model="test-model", api_key="test").generate(source)


def test_review_input_overflow_has_zero_provider_attempts(monkeypatch):
    source, candidate = narrative_inputs()
    buffered = assemble_narrative(source, candidate)
    def overflow(*_, **kwargs):
        error = ValueError("semantic input exceeds local context budget")
        error.input_bytes = 17001
        raise error
    monkeypatch.setattr("core.answer_synthesis_deepseek.build_semantic_review_prompt", overflow)
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat",
                        lambda *_: pytest.fail("Preflight must not call Provider"))
    port = DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True)
    with pytest.raises(ProviderPreflightFailure):
        port.review(source, buffered.plan, buffered.text)
    assert port.completion_receipts == []
    assert port.preflight_receipts == [{"phase": "review", "api_attempts": 0,
        "code": "SEMANTIC_INPUT_BUDGET_EXCEEDED", "input_bytes": 17001}]


def test_truncated_single_attempt_retains_verified_usage_but_no_candidate(monkeypatch):
    source, _ = narrative_inputs()
    response = ChatResponse('{"claims":[', "deepseek", "test-model", 4210, 1024, 5234,
                            {"finish_reason": "length", "api_attempts": 1})
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat", lambda *_: response)
    port = DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True)
    with pytest.raises(AccountedCompletionFailure) as failure:
        port.generate(source)
    assert failure.value.usage.total_tokens == 5234
    assert len(port.completion_receipts) == 1


@pytest.mark.parametrize("phase", ["generate", "review"])
@pytest.mark.parametrize("content", ['{"claims":[', '{"claims":[{"evidence_ids":["unknown"]}]}'])
def test_completed_but_invalid_contract_retains_spent_usage(monkeypatch, phase, content):
    source, candidate = narrative_inputs()
    response = ChatResponse(content, "deepseek", "test-model", 100, 50, 150,
                            {"finish_reason": "stop", "api_attempts": 1})
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat", lambda *_: response)
    port = DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True)
    with pytest.raises(AccountedCompletionFailure) as failure:
        if phase == "generate":
            port.generate(source)
        else:
            buffered = assemble_narrative(source, candidate)
            port.review(source, buffered.plan, buffered.text)
    assert failure.value.usage.total_tokens == 150
    assert str(failure.value) == f"DEEPSEEK_{'GENERATION' if phase == 'generate' else 'REVIEW'}_CONTRACT_FAILED"


def test_contract_failure_diagnostic_exposes_only_allowlisted_code(monkeypatch):
    source, candidate = narrative_inputs()
    candidate["claims"][0]["text"] = "Revenue fell 99%."
    refs = CompactEvidenceReferences(source)
    candidate["claims"][0]["evidence_ids"] = [refs.encode[source.evidence[0].evidence_id]]
    response = ChatResponse(json.dumps(candidate), "deepseek", "test-model", 100, 50, 150,
                            {"finish_reason": "stop", "api_attempts": 1})
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat", lambda *_: response)
    port = DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True)
    with pytest.raises(AccountedCompletionFailure):
        port.generate(source)
    assert port.completion_receipts[-1]["contract_failure_code"] == "NARRATIVE_NUMERIC_MUTATION"
    assert "content" not in port.completion_receipts[-1]


@pytest.mark.parametrize("changes", [{"provider": "ollama"}, {"model": "other"},
    {"metadata": {"finish_reason": "length"}}])
def test_invalid_completion_never_becomes_candidate(monkeypatch, changes):
    source, candidate = narrative_inputs()
    response = ChatResponse(json.dumps(candidate), "deepseek", "test-model", 100, 50, 150,
                            {"finish_reason": "stop", "api_attempts": 1})
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat",
                        lambda *_: replace(response, **changes))
    with pytest.raises(ValueError):
        DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True).generate(source)


def test_cloud_reviewer_uses_same_locked_prompt_and_claim_bindings(monkeypatch):
    source, candidate = narrative_inputs()
    buffered = assemble_narrative(source, candidate)
    references = CompactEvidenceReferences(source)
    expected = build_semantic_review_prompt(source, buffered.plan, buffered.text,
                                           reference_transport=references)
    def chat(_, request):
        assert (request.system_prompt, request.messages[0]["content"]) == expected
        claims = [{"claim_id": claim.claim_id,
                   "evidence_ids": [references.encode[value] for value in claim.evidence_ids],
                   "verdict": "SUPPORTED", "causal_strength": claim.causal_strength.value,
                   "rationale": "fixture"} for claim in buffered.plan.claims]
        return ChatResponse(json.dumps({"claims": claims}), "deepseek", "test-model",
                            100, 50, 150, {"finish_reason": "stop", "api_attempts": 1})
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat", chat)
    review = DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True).review(
        source, buffered.plan, buffered.text)
    assert review.total_tokens == 150
    assert review.reviewer_version == "deepseek-entailment.v1:test-model"


def test_compact_cloud_generation_restores_canonical_citations(monkeypatch):
    source, candidate = narrative_inputs()
    references = CompactEvidenceReferences(source)
    compact = {"claims": [{**claim, "evidence_ids": [references.encode[value]
        for value in claim["evidence_ids"]]} for claim in candidate["claims"]]}
    def chat(_, request):
        assert json.loads(request.messages[0]["content"])["evidence"][0]["evidence_id"] == "r1"
        return ChatResponse(json.dumps(compact), "deepseek", "test-model", 100, 50, 150,
                            {"finish_reason": "stop", "api_attempts": 1})
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat", chat)
    result = DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True).generate(source)
    assert result.buffered == assemble_narrative(source, candidate)


@pytest.mark.parametrize("with_subject_context", [False, True])
def test_local_and_cloud_compact_ports_share_prompt_and_canonical_plan(monkeypatch, with_subject_context):
    source, candidate = narrative_inputs()
    if with_subject_context:
        evidence = replace(source.evidence[0], payload={**source.evidence[0].payload, "page": 10,
            "provenance": {"subject_context": json.dumps({"role": "CONTROLLING_SHAREHOLDER", "page": 10,
                "context_text": "控股股东情况 名称 Example Group 单位负责人 Example Person",
                "rule": "explicit-same-page-owner-header.v1"})}})
        source = replace(source, evidence=(evidence,))
        candidate["claims"][0]["text"] = "Example Group revenue fell 10%."
    refs = CompactEvidenceReferences(source)
    compact = {"claims": [{**claim, "evidence_ids": [refs.encode[value]
        for value in claim["evidence_ids"]]} for claim in candidate["claims"]]}
    seen = []
    def cloud(_, request):
        seen.append((request.system_prompt, request.messages))
        return ChatResponse(json.dumps(compact), "deepseek", "test-model", 100, 50, 150,
                            {"finish_reason": "stop", "api_attempts": 1})
    def local(_, request):
        seen.append((request.system_prompt, request.messages))
        return ChatResponse(json.dumps(compact), "ollama", "local/Qwen3.8:q4", 100, 50, 150,
                            {"done_reason": "stop"})
    monkeypatch.setattr("llm.adapters.deepseek_provider.DeepSeekProvider.chat", cloud)
    monkeypatch.setattr("llm.adapters.ollama_provider.OllamaProvider.chat", local)
    first = DeepSeekSynthesisPorts(model="test-model", api_key="test", enabled=True).generate(source)
    second = LocalQwenNarrativeGenerator(model="local/Qwen3.8:q4", enabled=True,
                                        compact_references=True).generate(source)
    assert seen[0] == seen[1]
    assert first.buffered == second.buffered == assemble_narrative(source, candidate)


def test_local_compact_review_restores_canonical_bindings(monkeypatch):
    source, candidate = narrative_inputs()
    buffered = assemble_narrative(source, candidate)
    refs = CompactEvidenceReferences(source)
    def chat(_, request):
        assert json.loads(request.messages[0]["content"])["evidence"][0]["evidence_id"] == "r1"
        claims = [{"claim_id": claim.claim_id, "evidence_ids": [refs.encode[value]
            for value in claim.evidence_ids], "verdict": "SUPPORTED",
            "causal_strength": claim.causal_strength.value, "rationale": "fixture"}
            for claim in buffered.plan.claims]
        return ChatResponse(json.dumps({"claims": claims}), "ollama", "local/Qwen3.8:q4",
                            100, 50, 150, {"done_reason": "stop"})
    monkeypatch.setattr("llm.adapters.ollama_provider.OllamaProvider.chat", chat)
    review = LocalQwenEntailmentReviewer(model="local/Qwen3.8:q4", enabled=True,
        compact_references=True).review(source, buffered.plan, buffered.text)
    assert [claim.evidence_ids for claim in review.claims] == [claim.evidence_ids for claim in buffered.plan.claims]
