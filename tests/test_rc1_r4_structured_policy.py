"""R4 purpose negotiation, reversible references and bounded release; no live calls."""
import hashlib
import json

import pytest

from core.answer_provider_port import chat_answer
from core.answer_synthesis_narrative_ollama import LocalQwenNarrativeGenerator
from core.answer_synthesis_narrative_strategy import build_narrative_prompt
from core.answer_synthesis_narrative_workflow import synthesize_narrative
from core.answer_synthesis_reference_transport import CompactEvidenceReferences
from core.answer_synthesis_semantic_ollama import LocalQwenEntailmentReviewer, build_semantic_review_prompt
from llm.providers.provider_models import ChatResponse, ProviderCapability
from tests.test_rc1_r3_generation_truncation import (
    minimal_source_and_candidate,
    offline_provider,
    sdk_response,
)


def test_thinking_control_is_explicitly_truthful():
    assert ProviderCapability().supports_thinking_control is False


@pytest.mark.parametrize("purpose", ["STRUCTURED_GENERATION", "STRUCTURED_REVIEW"])
@pytest.mark.parametrize("supported", [True, False])
def test_purpose_negotiates_only_supported_control(purpose, supported):
    class Provider:
        provider_name = "configurable"
        model = "customer-model"

        def get_capability(self):
            return ProviderCapability(supports_system_prompt=True, supports_thinking_control=supported)

        def chat(self, request):
            self.request = request
            return ChatResponse("{}", self.provider_name, self.model, finish_reason="stop")

    provider = Provider()
    chat_answer(provider, "unchanged instruction", "{}", max_seconds=60, max_tokens=1024,
                purpose=purpose)
    assert provider.request.thinking_enabled is (False if supported else None)
    assert provider.request.max_tokens == 1024


@pytest.mark.parametrize("gen_total,review_total,expected", [
    (12283, 1000, "REVIEWED_NARRATIVE"),
    (8000, 8384, "REVIEWED_NARRATIVE"),
    (8000, 8385, "TOKEN_BUDGET_EXHAUSTED"),
])
def test_actual_ports_compact_two_phase_accounting(gen_total, review_total, expected):
    source, candidate = minimal_source_and_candidate()
    refs = CompactEvidenceReferences(source)
    canonical = source.evidence[0].evidence_id
    candidate["claims"][0]["evidence_ids"] = [refs.encode[canonical]]
    review = {"claims": [{"claim_id": "claim-1", "evidence_ids": [refs.encode[canonical]],
        "verdict": "SUPPORTED", "causal_strength": "UNSUPPORTED", "rationale": "Exact disclosure."}]}
    def usage(total):
        return {"prompt_tokens": total - 100, "completion_tokens": 100, "total_tokens": total}
    # The existing assembler owns deterministic claim IDs; never fabricate its identity.
    from core.answer_synthesis_narrative import assemble_narrative
    restored = refs.decode_claims(source, candidate)
    buffered = assemble_narrative(source, restored)
    review["claims"][0]["claim_id"] = buffered.plan.claims[0].claim_id
    provider, sdk, requests = offline_provider([
        sdk_response(json.dumps(candidate, ensure_ascii=False), "stop", usage(gen_total)),
        sdk_response(json.dumps(review), "stop", usage(review_total))])
    generator = LocalQwenNarrativeGenerator(provider=provider, enabled=True, compact_references=True,
                                           request_purpose="STRUCTURED_GENERATION")
    reviewer = LocalQwenEntailmentReviewer(provider=provider, enabled=True, compact_references=True,
                                         request_purpose="STRUCTURED_REVIEW")
    try:
        outcome = synthesize_narrative(source, generator=generator, reviewer=reviewer,
                                      enabled=True, max_total_tokens=16384)
        assert outcome.reason == expected
        assert outcome.total_tokens == gen_total + review_total
        assert len(requests) == 2 and outcome.reviewer_calls == 1
        for request in requests:
            assert request["thinking"] == {"type": "disabled"}
            assert "reasoning_effort" not in request and request["max_tokens"] == 1024
        _, raw_generation = build_narrative_prompt(source)
        assert refs.restore_payload(source, requests[0]["messages"][-1]["content"]) == json.loads(raw_generation)
        _, raw_review = build_semantic_review_prompt(source, buffered.plan, buffered.text)
        assert refs.restore_payload(source, requests[1]["messages"][-1]["content"]) == json.loads(raw_review)
        if expected == "REVIEWED_NARRATIVE":
            assert outcome.review.claims[0].evidence_ids == (canonical,)
            assert outcome.generated.buffered.citation_evidence_ids == (canonical,)
        else:
            assert outcome.text is None
    finally:
        sdk.close()


@pytest.mark.parametrize("body,finish", [("{", "stop"), ("{}", "length")])
def test_repaired_generation_admission_still_fail_closed(body, finish):
    source, _ = minimal_source_and_candidate()
    provider, sdk, calls = offline_provider([sdk_response(body, finish)])
    class NoReview:
        def review(self, *args, **kwargs):
            raise AssertionError("Failed generation cannot reach mandatory Reviewer")
    try:
        outcome = synthesize_narrative(source,
            generator=LocalQwenNarrativeGenerator(provider=provider, enabled=True,
                compact_references=True, request_purpose="STRUCTURED_GENERATION"),
            reviewer=NoReview(), enabled=True, max_total_tokens=16384)
        assert outcome.reason == "STRUCTURED_OUTPUT_ERROR" and outcome.text is None
        assert len(calls) == 1 and outcome.reviewer_calls == 0
    finally:
        sdk.close()


@pytest.mark.parametrize("body,status,kind,count", [
    ("", "NOT_APPLICABLE", None, None), ("{", "FAIL", None, None),
    ('{"claims":[]}', "PASS", "object", 0), ("[]", "PASS", "array", None),
    ('{"x":1,"x":2}', "FAIL", None, None), ("NaN", "FAIL", None, None),
    ('```json\n{}\n```', "FAIL", None, None),
])
def test_safe_diagnostics_are_observational_and_contain_no_body(body, status, kind, count):
    response = ChatResponse(body, "test", "fixture", finish_reason="length")
    safe = response.metadata["safe_response_diagnostics"]
    assert safe["visible_content_present"] is bool(body)
    assert safe["visible_char_count"] == len(body)
    assert safe["visible_utf8_bytes"] == len(body.encode())
    assert safe["visible_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert (safe["strict_json_parse"], safe["top_level_type"], safe["claim_count"]) == (status, kind, count)
    assert response.finish_reason == "length"  # Diagnostics never relax admission.
    assert "content" not in safe and "prompt" not in safe and "reasoning_text" not in safe
