"""Reversible request-local evidence handles; canonical citations never change."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from core.answer_synthesis_contracts import SynthesisInput
from core.answer_synthesis_narrative_strategy import parse_narrative_json

TECHNICAL_PROVENANCE_KEYS = frozenset({
    "source_sha256", "content_sha256", "document_version", "parser_version",
    "chunker_version", "embedding_identity", "collection", "tenant_id",
    "document_id", "source_format",
})
REFERENCE_TRANSPORT_VERSION = "request-local-v2"
REFERENCE_TRANSPORT_INSTRUCTION = (
    " Evidence reference handles are request-local: use the outer evidence_id in responses. "
    "If shared_provenance is present, its technical source fields apply to every evidence "
    "payload.provenance, alongside each item's remaining provenance fields. "
    "If draft uses claim-text-segments.v1, reconstruct it by concatenating literal segments "
    "and claims[index].semantic_content (zero-based) for each claim_text reference; "
    "audit the entire reconstructed draft."
)


def _encode_draft(data):
    draft, claims = data.get("draft"), data.get("claims")
    if draft is None:
        return
    if not isinstance(draft, str):
        raise ValueError("INVALID_REFERENCE_DRAFT")
    if not isinstance(claims, list) or not claims:
        return
    segments, position = [], 0
    for index, claim in enumerate(claims):
        text = claim.get("semantic_content")
        if not isinstance(text, str) or not text:
            return
        found = draft.find(text, position)
        if found < 0:
            return
        if found > position:
            segments.append(draft[position:found])
        segments.append({"claim_text": index})
        position = found + len(text)
    if position < len(draft):
        segments.append(draft[position:])
    encoded = {"format": "claim-text-segments.v1", "segments": segments,
               "sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest()}
    encoded_size = len(json.dumps(encoded, ensure_ascii=False).encode("utf-8"))
    if encoded_size < len(json.dumps(draft, ensure_ascii=False).encode("utf-8")):
        data["draft"] = encoded


def _restore_draft(data):
    draft = data.get("draft")
    if not isinstance(draft, dict):
        return
    if (set(draft) != {"format", "segments", "sha256"}
            or draft["format"] != "claim-text-segments.v1" or not isinstance(draft["segments"], list)):
        raise ValueError("INVALID_REFERENCE_DRAFT")
    pieces = []
    for segment in draft["segments"]:
        if isinstance(segment, str):
            pieces.append(segment)
        elif (isinstance(segment, dict) and set(segment) == {"claim_text"}
              and type(segment["claim_text"]) is int and 0 <= segment["claim_text"] < len(data.get("claims", []))):
            text = data["claims"][segment["claim_text"]].get("semantic_content")
            if not isinstance(text, str):
                raise ValueError("INVALID_REFERENCE_DRAFT")
            pieces.append(text)
        else:
            raise ValueError("INVALID_REFERENCE_DRAFT")
    restored = "".join(pieces)
    if hashlib.sha256(restored.encode("utf-8")).hexdigest() != draft["sha256"]:
        raise ValueError("REFERENCE_DRAFT_DIGEST_CHANGED")
    data["draft"] = restored


@dataclass(frozen=True)
class CompactEvidenceReferences:
    source: SynthesisInput
    encode: Mapping[str, str] = field(init=False)
    decode: Mapping[str, str] = field(init=False)

    def __post_init__(self):
        identifiers = tuple(item.evidence_id for item in self.source.evidence)
        if not identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("UNIQUE_EVIDENCE_REFERENCES_REQUIRED")
        object.__setattr__(self, "encode", MappingProxyType({
            value: f"r{index}" for index, value in enumerate(identifiers, 1)}))
        object.__setattr__(self, "decode", MappingProxyType({value: key for key, value in self.encode.items()}))

    def encode_payload(self, source, payload):
        if source is not self.source:
            raise ValueError("REFERENCE_SOURCE_CHANGED")
        data = parse_narrative_json(payload)
        for evidence in data["evidence"]:
            original = evidence["evidence_id"]
            evidence["evidence_id"] = self.encode[original]
            nested = evidence.get("payload", {})
            if "evidence_id" in nested:
                if nested["evidence_id"] != original:
                    raise ValueError("REFERENCE_PAYLOAD_IDENTITY_CHANGED")
                nested["evidence_id"] = self.encode[original]
        for claim in data.get("claims", []):
            claim["evidence_ids"] = [self.encode[identifier] for identifier in claim["evidence_ids"]]
        if "shared_provenance" in data:
            raise ValueError("RESERVED_REFERENCE_TRANSPORT_FIELD")
        provenance = [item.get("payload", {}).get("provenance", {}) for item in data["evidence"]]
        if len(provenance) > 1:
            shared = {key: provenance[0][key] for key in TECHNICAL_PROVENANCE_KEYS
                if key in provenance[0] and type(provenance[0][key]) in (str, int)
                and all(key in row and type(row[key]) is type(provenance[0][key])
                        and row[key] == provenance[0][key] for row in provenance[1:])}
            if shared:
                data["shared_provenance"] = dict(sorted(shared.items()))
                for row in provenance:
                    for key in shared:
                        del row[key]
        _encode_draft(data)
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def restore_payload(self, source, payload):
        """Audit-only lossless inverse; not a model-answer release path."""
        if source is not self.source:
            raise ValueError("REFERENCE_SOURCE_CHANGED")
        data = parse_narrative_json(payload)
        shared = data.pop("shared_provenance", {})
        if not isinstance(shared, dict) or not set(shared) <= TECHNICAL_PROVENANCE_KEYS:
            raise ValueError("INVALID_SHARED_PROVENANCE")
        for item in data["evidence"]:
            item["evidence_id"] = self.decode[item["evidence_id"]]
            nested = item.get("payload", {})
            if "evidence_id" in nested:
                nested["evidence_id"] = self.decode[nested["evidence_id"]]
            if shared:
                individual = nested.setdefault("provenance", {})
                if set(individual) & set(shared):
                    raise ValueError("CONFLICTING_SHARED_PROVENANCE")
                individual.update(shared)
        for claim in data.get("claims", []):
            claim["evidence_ids"] = [self.decode[value] for value in claim["evidence_ids"]]
        _restore_draft(data)
        return data

    def decode_claims(self, source, candidate):
        if source is not self.source:
            raise ValueError("REFERENCE_SOURCE_CHANGED")
        if not isinstance(candidate, dict) or not isinstance(candidate.get("claims"), list):
            raise ValueError("INVALID_REFERENCE_RESPONSE")
        claims = []
        for claim in candidate["claims"]:
            if not isinstance(claim, dict) or not isinstance(claim.get("evidence_ids"), list):
                raise ValueError("INVALID_REFERENCE_RESPONSE")
            references = claim["evidence_ids"]
            if (any(not isinstance(value, str) or value not in self.decode for value in references)
                    or len(set(references)) != len(references)):
                raise ValueError("UNKNOWN_OR_DUPLICATE_EVIDENCE_REFERENCE")
            claims.append({**claim, "evidence_ids": [self.decode[value] for value in references]})
        return {**candidate, "claims": claims}
