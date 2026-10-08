"""Offline actual SDK/adapter/port regressions; synthetic bodies are not live evidence."""
import json
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from core.answer_synthesis_contracts import AnswerType, EvidenceSnapshot, SynthesisInput
from core.answer_synthesis_narrative_ollama import LocalQwenNarrativeGenerator
from core.answer_synthesis_narrative_strategy import parse_narrative_json
from core.answer_synthesis_narrative_workflow import synthesize_narrative
from core.answer_synthesis_usage import AccountedCompletionFailure
from llm.adapters.deepseek_provider import DeepSeekProvider
from llm.adapters.openai_provider import OpenAIProvider
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_models import ChatRequest

METADATA = json.loads((Path(__file__).parent / "fixtures" / "rc1-r3-safe-generation-metadata.json")
                      .read_text(encoding="utf-8"))


def minimal_source_and_candidate():
    text = "公司主要业务是茅台酒及系列酒的生产与销售"
    evidence = EvidenceSnapshot("fixture:page8", "fixture-document", {
        "text": text, "company": "贵州茅台", "page": 8,
        "source_locator": {"page": 8, "locator": "fixture:page8"}, "provenance": {"tenant_id": 1}})
    source = SynthesisInput("说明贵州茅台的主要业务", 1, AnswerType.EXPLANATION,
                            "zh-CN", (evidence,), "PARTIAL", "HYBRID", {"complete": None})
    candidate = {"claims": [{"text": text, "evidence_ids": [evidence.evidence_id],
                             "causal_strength": "UNSUPPORTED", "caveat": None}]}
    return source, candidate


def sdk_response(content, finish, usage=None):
    result = {"id": "offline-r3", "object": "chat.completion", "created": 1,
              "model": "deepseek-flash", "choices": [{"index": 0,
              "message": {"role": "assistant", "content": content}, "finish_reason": finish}]}
    if usage is not None:
        result["usage"] = usage
    return result


def offline_provider(responses):
    """Actual OpenAI SDK serializes requests, but MockTransport never opens a socket."""
    requests = []
    pending = iter(responses)
    def transport(request):
        assert request.url.host == "offline.invalid"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(pending))
    sdk = OpenAI(api_key="offline-fixture-not-a-secret", base_url="https://offline.invalid",
                 max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    provider = DeepSeekProvider(ProviderConfig(provider="deepseek", model=METADATA["model"],
        api_key="offline-fixture-not-a-secret", timeout=60, total_deadline=120,
        connect_timeout=10, read_timeout=45, max_tokens=1024))
    provider._client = sdk
    return provider, sdk, requests


def reproduce_historical_boundary():
    source, candidate = minimal_source_and_candidate()
    # This valid synthetic body is deliberately stronger than the retained live
    # evidence: even complete JSON with length must not bypass finish admission.
    body = json.dumps(candidate, ensure_ascii=False)
    provider, sdk, calls = offline_provider([
        sdk_response("", "length", METADATA["call1"]["usage"]),
        sdk_response(body, "length", METADATA["call2"]["usage"])])
    class NoReview:
        def review(self, *args, **kwargs):
            raise AssertionError("Rejected generation must not reach Reviewer")
    try:
        outcome = synthesize_narrative(source,
            generator=LocalQwenNarrativeGenerator(provider=provider, enabled=True),
            reviewer=NoReview(), enabled=True)
        return outcome, calls
    finally:
        sdk.close()


def test_actual_metadata_reproduces_generation_rejection_and_no_review():
    outcome, calls = reproduce_historical_boundary()
    assert outcome.reason == outcome.failure_class == "STRUCTURED_OUTPUT_ERROR"
    assert outcome.generation_calls == 1 and outcome.reviewer_calls == 0
    assert outcome.total_tokens == 12283 and outcome.usage_complete is True
    assert outcome.text is None and len(calls) == 2
    first, recovery = calls
    assert first["max_tokens"] == recovery["max_tokens"] == 1024
    assert first["reasoning_effort"] == "high"
    assert first["thinking"] == {"type": "enabled"}
    assert recovery["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in recovery
    assert first["messages"] == recovery["messages"]
    assert "temperature" not in first and "temperature" not in recovery
    assert "response_format" not in first and "response_format" not in recovery
    assert "stream" not in first and "stream" not in recovery


@pytest.mark.parametrize("content_kind", ["complete_json", "unclosed_json", "unfinished_field"])
def test_nonempty_length_always_rejected_even_if_json_parses(content_kind):
    source, candidate = minimal_source_and_candidate()
    body = {"complete_json": json.dumps(candidate, ensure_ascii=False),
            "unclosed_json": '{"claims":[', "unfinished_field": '{"claims":[{"text":"'}[content_kind]
    if content_kind == "complete_json":
        assert parse_narrative_json(body) == candidate
    provider, sdk, calls = offline_provider([sdk_response(body, "length", METADATA["call2"]["usage"])])
    try:
        with pytest.raises(AccountedCompletionFailure) as failure:
            LocalQwenNarrativeGenerator(provider=provider, enabled=True).generate(source)
        assert failure.value.failure_class == "STRUCTURED_OUTPUT_ERROR"
        assert str(failure.value) == "NARRATIVE_PROVIDER_RESPONSE_MISMATCH"
        assert len(calls) == 1
    finally:
        sdk.close()


def test_stop_valid_schema_is_candidate_not_verified_release():
    source, candidate = minimal_source_and_candidate()
    provider, sdk, calls = offline_provider([sdk_response(json.dumps(candidate, ensure_ascii=False), "stop")])
    try:
        generated = LocalQwenNarrativeGenerator(provider=provider, enabled=True).generate(source)
        assert generated.buffered.plan.claims[0].fact_status == "UNVERIFIED"
        assert generated.total_tokens is None and len(calls) == 1
    finally:
        sdk.close()


def test_stop_invalid_json_classified_structured_not_transport():
    source, _ = minimal_source_and_candidate()
    provider, sdk, calls = offline_provider([sdk_response('{"claims":[', "stop", METADATA["call2"]["usage"])])
    try:
        with pytest.raises(AccountedCompletionFailure) as failure:
            LocalQwenNarrativeGenerator(provider=provider, enabled=True).generate(source)
        assert failure.value.failure_class == "STRUCTURED_OUTPUT_ERROR"
        assert str(failure.value) == "LOCAL_GENERATION_CONTRACT_FAILED"
        assert len(calls) == 1
    finally:
        sdk.close()


def test_empty_length_uses_existing_recovery_and_preserves_returned_content():
    _, candidate = minimal_source_and_candidate()
    body = json.dumps(candidate, ensure_ascii=False)
    provider, sdk, calls = offline_provider([
        sdk_response("", "length", METADATA["call1"]["usage"]), sdk_response(body, "stop")])
    try:
        response = provider.chat(ChatRequest(messages=[{"role": "user", "content": "offline"}], max_tokens=1024))
        assert response.content == body and response.finish_reason == "stop"
        assert response.metadata["api_attempts"] == len(calls) == 2
        assert response.total_tokens is None  # Recovery usage absent, do not fake it.
    finally:
        sdk.close()


def test_completed_recovery_usage_would_still_exhaust_existing_workflow_budget():
    source, candidate = minimal_source_and_candidate()
    # Counterfactual: keep recorded token usage but make recovery stop with valid
    # synthetic JSON. It must still respect the existing 8192 workflow budget.
    provider, sdk, calls = offline_provider([
        sdk_response("", "length", METADATA["call1"]["usage"]),
        sdk_response(json.dumps(candidate, ensure_ascii=False), "stop", METADATA["call2"]["usage"])])
    class NoReview:
        def review(self, *args, **kwargs):
            raise AssertionError("Exhausted workflow budget must not invoke Reviewer")
    try:
        outcome = synthesize_narrative(source,
            generator=LocalQwenNarrativeGenerator(provider=provider, enabled=True),
            reviewer=NoReview(), enabled=True)
        assert outcome.reason == "TOKEN_BUDGET_EXHAUSTED"
        assert outcome.total_tokens == 12283 > 8192
        assert outcome.reviewer_calls == 0 and len(calls) == 2
    finally:
        sdk.close()


@pytest.mark.parametrize("thinking,enabled,effort", [(None, "enabled", "high"),
    (True, "enabled", "high"), (False, "disabled", None)])
def test_existing_request_reasoning_policy_mapping(thinking, enabled, effort):
    provider, sdk, calls = offline_provider([sdk_response("offline body", "stop")])
    try:
        provider.chat(ChatRequest(messages=[{"role": "user", "content": "offline"}],
                                  max_tokens=1024, thinking_enabled=thinking))
        assert calls[0]["thinking"] == {"type": enabled}
        assert calls[0].get("reasoning_effort") == effort
        assert calls[0]["max_tokens"] == 1024
        assert "max_completion_tokens" not in calls[0] and "max_output_tokens" not in calls[0]
    finally:
        sdk.close()


def test_openai_currently_ignores_thinking_false_capability_gap():
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=sdk_response("offline", "stop"))
    sdk = OpenAI(api_key="offline-fixture-not-a-secret", base_url="https://offline.invalid",
                 max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    provider = OpenAIProvider(ProviderConfig(provider="openai", model="customer-model",
        api_key="offline-fixture-not-a-secret", max_tokens=1024))
    provider._client = sdk
    try:
        provider.chat(ChatRequest(messages=[{"role": "user", "content": "offline"}],
                                  max_tokens=1024, thinking_enabled=False))
        assert requests[0]["max_completion_tokens"] == 1024
        assert requests[0]["reasoning_effort"] == "medium"
        assert "thinking" not in requests[0]
        # Existing capability does not identify support for thinking on/off.
        assert provider.get_capability().supports_reasoning_effort is True
        assert provider.get_capability().supports_thinking_control is False
    finally:
        sdk.close()
