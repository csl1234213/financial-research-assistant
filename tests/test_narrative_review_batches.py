"""Budget partitioning preserves original evidence and complete draft coverage."""

import json
from dataclasses import replace

import pytest

from core.answer_synthesis_contracts import AnswerType
from core.answer_synthesis_narrative import assemble_narrative
from core.answer_synthesis_reference_transport import CompactEvidenceReferences
from core.answer_synthesis_review_batches import plan_narrative_review_batches
from core.answer_synthesis_semantic_ollama import SEMANTIC_REVIEW_INPUT_MAX_BYTES
from tests.test_answer_synthesis_narrative import narrative_inputs


def prepared(count=18):
    source, candidate = narrative_inputs()
    row = candidate["claims"][0]
    row = {**row, "text": row["text"] + "支持业务的明确说明。" * 170}
    source = replace(source, evidence=tuple(replace(item,
        payload={**item.payload, "text": item.payload["text"] + "来源完整证据。" * 80})
        for item in source.evidence))
    buffered = assemble_narrative(source, {"claims": [row.copy() for _ in range(count)]})
    return source, buffered


def test_partition_preserves_all_claims_draft_and_evidence():
    source, buffered = prepared()
    batches = plan_narrative_review_batches(source, buffered.plan, buffered.text)
    assert 1 < len(batches) <= 4
    assert "\n".join(batch.draft for batch in batches) == buffered.text
    assert tuple(claim for batch in batches for claim in batch.plan.claims) == buffered.plan.claims
    refs = CompactEvidenceReferences(source)
    for batch in batches:
        assert batch.wire_bytes <= SEMANTIC_REVIEW_INPUT_MAX_BYTES
        restored = refs.restore_payload(source, batch.payload)
        assert restored["draft"] == batch.draft
        assert len(restored["evidence"]) == len(source.evidence)
        for original, encoded in zip(source.evidence, restored["evidence"], strict=True):
            assert encoded["payload"]["text"] == original.payload["text"]
        assert json.loads(batch.payload)["claims"]


@pytest.mark.parametrize("suffix", ["\n未经核实的额外结论。", " "])
def test_unclaimed_extra_prose_is_rejected_before_calls(suffix):
    source, buffered = prepared(1)
    with pytest.raises(ValueError, match="PROJECTION_CHANGED"):
        plan_narrative_review_batches(source, buffered.plan, buffered.text + suffix)


def test_batch_limit_never_drops_remaining_claims():
    source, buffered = prepared()
    with pytest.raises(ValueError, match="BATCH_LIMIT_EXCEEDED"):
        plan_narrative_review_batches(source, buffered.plan, buffered.text, max_batches=1)


def test_oversize_evidence_is_not_trimmed():
    source, buffered = prepared(1)
    source = replace(source, evidence=tuple(replace(item,
        payload={**item.payload, "text": item.payload["text"] + "完整来源" * 4000})
        for item in source.evidence))
    with pytest.raises(ValueError, match="SINGLE_CLAIM_EXCEEDS"):
        plan_narrative_review_batches(source, buffered.plan, buffered.text)


def test_incomplete_coverage_disclosure_is_preserved_not_duplicated():
    source, buffered = prepared()
    source = replace(source, answer_type=AnswerType.EXHAUSTIVE_LIST)
    buffered = assemble_narrative(source, {"claims": [
        {"text": claim.semantic_content, "evidence_ids": list(claim.evidence_ids),
         "causal_strength": claim.causal_strength.value, "caveat": claim.caveat}
        for claim in buffered.plan.claims]})
    batches = plan_narrative_review_batches(source, buffered.plan, buffered.text)
    disclosure = buffered.text.splitlines()[0]
    assert not disclosure.startswith("- ")
    assert sum(batch.draft.count(disclosure) for batch in batches) == 1
    assert all(batch.plan.caveats == buffered.plan.caveats for batch in batches)


@pytest.mark.parametrize("limit", [True, 0, 5, None])
def test_invalid_batch_limit_rejected(limit):
    source, buffered = prepared(1)
    with pytest.raises(ValueError, match="INVALID_REVIEW_BATCH_LIMIT"):
        plan_narrative_review_batches(source, buffered.plan, buffered.text, max_batches=limit)
