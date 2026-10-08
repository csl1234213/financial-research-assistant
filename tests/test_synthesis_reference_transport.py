"""Short transport handles preserve immutable source and canonical claim bindings."""

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from core.answer_synthesis_narrative import assemble_narrative
from core.answer_synthesis_narrative_strategy import build_narrative_prompt
from core.answer_synthesis_reference_transport import CompactEvidenceReferences
from core.answer_synthesis_semantic_ollama import SEMANTIC_REVIEW_INPUT_MAX_BYTES, build_semantic_review_prompt
from tests.test_answer_synthesis_narrative import narrative_inputs


def test_payload_keeps_all_source_content_and_restores_claim_references():
    source, candidate = narrative_inputs()
    refs = CompactEvidenceReferences(source)
    _, original = build_narrative_prompt(source)
    encoded = json.loads(refs.encode_payload(source, original))
    prior = json.loads(original)
    for old, new in zip(prior["evidence"], encoded["evidence"], strict=True):
        if "evidence_id" in new["payload"]:
            new["payload"]["evidence_id"] = refs.decode[new["payload"]["evidence_id"]]
        assert new["payload"] == old["payload"]
        assert new["document_id"] == old["document_id"]
        assert refs.decode[new["evidence_id"]] == old["evidence_id"]
    compact = {"claims": [{**claim, "evidence_ids": [refs.encode[value]
        for value in claim["evidence_ids"]]} for claim in candidate["claims"]]}
    assert refs.decode_claims(source, compact) == candidate


@pytest.mark.parametrize("references", [["r999"], ["r1", "r1"], [True], [None]])
def test_unknown_duplicate_or_wrong_type_reference_is_rejected(references):
    source, _ = narrative_inputs()
    with pytest.raises(ValueError):
        CompactEvidenceReferences(source).decode_claims(source, {"claims": [{"evidence_ids": references}]})


def test_canonical_ids_cannot_be_mixed_with_handles():
    source, candidate = narrative_inputs()
    with pytest.raises(ValueError):
        CompactEvidenceReferences(source).decode_claims(source, candidate)


def test_handles_cannot_cross_source_instance():
    source, _ = narrative_inputs()
    refs = CompactEvidenceReferences(source)
    with pytest.raises(ValueError, match="REFERENCE_SOURCE_CHANGED"):
        refs.decode_claims(replace(source), {"claims": []})
    with pytest.raises(TypeError):
        refs.decode["r1"] = "tampered"
    with pytest.raises(FrozenInstanceError):
        refs.source = replace(source)


def test_long_hash_identifiers_are_shortened_without_truncating_evidence():
    source, _ = narrative_inputs()
    source = replace(source, evidence=tuple(replace(item,
        evidence_id="indexed-text:" + "a" * 64 + ":" + f"{index:064x}",
        payload={**item.payload, "evidence_id": "indexed-text:" + "a" * 64 + ":" + f"{index:064x}"})
        for index, item in enumerate(source.evidence, 1)))
    _, original = build_narrative_prompt(source)
    refs = CompactEvidenceReferences(source)
    compact = refs.encode_payload(source, original)
    assert len(compact.encode("utf-8")) < len(original.encode("utf-8"))
    restored = json.loads(compact)
    for item in restored["evidence"]:
        item["evidence_id"] = refs.decode[item["evidence_id"]]
        if "evidence_id" in item["payload"]:
            item["payload"]["evidence_id"] = refs.decode[item["payload"]["evidence_id"]]
    assert restored == json.loads(original)


def test_review_budget_applies_to_actual_wire_payload_not_repeated_identifiers():
    source, candidate = narrative_inputs()
    identifier = "source:" + "a" * (SEMANTIC_REVIEW_INPUT_MAX_BYTES // 2)
    item = replace(source.evidence[0], evidence_id=identifier,
                   payload={**source.evidence[0].payload, "evidence_id": identifier})
    source = replace(source, evidence=(item,))
    candidate["claims"][0]["evidence_ids"] = [identifier]
    buffered = assemble_narrative(source, candidate)
    with pytest.raises(ValueError, match="context budget"):
        build_semantic_review_prompt(source, buffered.plan, buffered.text)
    _, payload = build_semantic_review_prompt(source, buffered.plan, buffered.text,
                                              reference_transport=CompactEvidenceReferences(source))
    assert len(payload.encode("utf-8")) <= 16000
    encoded = json.loads(payload)["evidence"][0]["payload"]["evidence_id"]
    assert CompactEvidenceReferences(source).decode[encoded] == identifier


def test_compact_review_still_rejects_oversized_source_content():
    source, candidate = narrative_inputs()
    item = replace(source.evidence[0], payload={**source.evidence[0].payload,
        "text": source.evidence[0].payload["text"] + "x" * SEMANTIC_REVIEW_INPUT_MAX_BYTES})
    source = replace(source, evidence=(item,))
    buffered = assemble_narrative(source, candidate)
    with pytest.raises(ValueError, match="context budget"):
        build_semantic_review_prompt(source, buffered.plan, buffered.text,
                                    reference_transport=CompactEvidenceReferences(source))


@pytest.mark.parametrize("different_version", [False, True])
def test_shared_technical_provenance_is_lossless_and_never_folds_financial_dimensions(different_version):
    source, _ = narrative_inputs()
    first = source.evidence[0]
    items = []
    for index in (1, 2):
        identifier = f"e{index}"
        provenance = {**first.payload["provenance"], "parser_version": "shared-parser-version",
            "content_sha256": ("b" if different_version and index == 2 else "a") * 64,
            "currency": "CNY" if index == 1 else "USD", "page": index}
        items.append(replace(first, evidence_id=identifier, document_id=str(index), payload={
            **first.payload, "evidence_id": identifier, "document_id": str(index),
            "company": "Moutai" if index == 1 else "Tesla",
            "scope": "CONSOLIDATED" if index == 1 else "PARENT_COMPANY",
            "page": index, "provenance": provenance}))
    source = replace(source, evidence=tuple(items))
    _, original = build_narrative_prompt(source)
    refs = CompactEvidenceReferences(source)
    encoded = refs.encode_payload(source, original)
    data = json.loads(encoded)
    assert data["shared_provenance"]["parser_version"] == "shared-parser-version"
    assert not {"currency", "scope", "company", "page"} & data["shared_provenance"].keys()
    assert ("content_sha256" not in data["shared_provenance"]) == different_version
    assert refs.restore_payload(source, encoded) == json.loads(original)
    assert len(encoded.encode("utf-8")) < len(original.encode("utf-8"))


def test_financial_fields_cannot_be_injected_into_shared_provenance():
    source, _ = narrative_inputs()
    _, original = build_narrative_prompt(source)
    refs = CompactEvidenceReferences(source)
    data = json.loads(refs.encode_payload(source, original))
    data["shared_provenance"] = {"scope": "PARENT_COMPANY"}
    with pytest.raises(ValueError, match="INVALID_SHARED_PROVENANCE"):
        refs.restore_payload(source, json.dumps(data))


def draft_payload(source):
    text = "A fully source-bound claim with its company, period, scope and citation intact. " * 8
    _, payload = build_narrative_prompt(source)
    encoded_payload = json.loads(payload)["evidence"][0]["payload"]
    return {"evidence": [{"evidence_id": source.evidence[0].evidence_id, "payload": encoded_payload}],
            "claims": [{"semantic_content": text, "evidence_ids": [source.evidence[0].evidence_id]}],
            "draft": "- " + text + " [1]\nExtra prose must remain visible to the reviewer."}


def test_draft_projection_is_lossless_including_unclaimed_extra_prose():
    source, _ = narrative_inputs()
    original = draft_payload(source)
    refs = CompactEvidenceReferences(source)
    wire = refs.encode_payload(source, json.dumps(original))
    assert json.loads(wire)["draft"]["format"] == "claim-text-segments.v1"
    assert len(wire.encode("utf-8")) < len(json.dumps(original).encode("utf-8"))
    assert refs.restore_payload(source, wire) == original
    assert "Extra prose must remain visible" in wire


@pytest.mark.parametrize("mutation", ["boolean", "index", "literal", "hash"])
def test_corrupted_draft_projection_is_rejected(mutation):
    source, _ = narrative_inputs()
    refs = CompactEvidenceReferences(source)
    wire = json.loads(refs.encode_payload(source, json.dumps(draft_payload(source))))
    if mutation == "boolean":
        wire["draft"]["segments"][1] = {"claim_text": True}
    elif mutation == "index":
        wire["draft"]["segments"][1] = {"claim_text": 999}
    elif mutation == "literal":
        wire["draft"]["segments"].append("Altered assertion.")
    else:
        wire["draft"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="REFERENCE_DRAFT|DRAFT_DIGEST"):
        refs.restore_payload(source, json.dumps(wire))


def test_unmatched_claim_text_leaves_complete_draft_uncompressed():
    source, _ = narrative_inputs()
    original = draft_payload(source)
    original["draft"] = "Not the claim text. No content may be inferred or removed."
    refs = CompactEvidenceReferences(source)
    wire = refs.encode_payload(source, json.dumps(original))
    assert json.loads(wire)["draft"] == original["draft"]
    assert refs.restore_payload(source, wire) == original
