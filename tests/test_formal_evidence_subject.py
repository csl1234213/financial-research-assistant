"""Subject authority and hostile-reviewer regressions; no model or live transport."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.grounded_answers import build_grounded_answer_router
from auth.dependencies import get_current_user
from core.answer_synthesis_contracts import AnswerType, EvidenceSnapshot, SynthesisInput, _freeze
from core.answer_synthesis_narrative import BufferedNarrative, assemble_narrative
from core.answer_synthesis_narrative_ollama import GeneratedNarrative
from core.answer_synthesis_narrative_strategy import build_narrative_payload
from core.answer_synthesis_semantic import EntailmentVerdict, SemanticClaimReview, SemanticReview, semantic_input_digest
from document_compatibility.evidence_subject import (
    EvidenceSubject,
    SubjectRelation,
    entity_id,
    project_subjects,
    subject_from_metadata,
)


def authority(relation, page):
    issuer, parent = "贵州茅台酒股份有限公司", "示例控股主体有限公司"
    name = issuer if relation == "ISSUER" else parent if relation == "CONTROLLING_SHAREHOLDER" else None
    return EvidenceSubject(entity_id(name), name, "ORGANIZATION" if name else "UNKNOWN", relation,
        "canonical-title-and-explicit-name.v1" if name else "UNKNOWN", "native-anchor" if name else None,
        entity_id(issuer), "a" * 64, "b" * 64, "c" * 64, page, ("explicit structural section",))


def snapshot(relation, page):
    subject = authority(relation, page)
    payload = {"company": "贵州茅台酒股份有限公司", "text": "公司主要业务是茅台酒生产与销售。房地产开发及租赁。",
               "page": page, "source_kind": "ready_indexed_text", "source": "original.pdf",
               "source_locator": {"page": page, "locator": f"native:{page}"},
               "provenance": {"tenant_id": 1, "source_sha256": "a" * 64, "content_sha256": "a" * 64,
                   "document_version": "a" * 64, "page": page, "evidence_subject_schema": subject.schema,
                   "evidence_subject": subject.serialize(), "subject_provenance_digest": subject.digest}}
    return EvidenceSnapshot(f"evidence:{page}", "1", _freeze(payload))


def source():
    return SynthesisInput("说明贵州茅台的主要业务", 1, AnswerType.EXPLANATION, "zh-CN",
        (snapshot("ISSUER", 8), snapshot("CONTROLLING_SHAREHOLDER", 50), snapshot("UNKNOWN", 120)),
        "PARTIAL", "HYBRID", {"complete": None})


def candidate(text, ids):
    return {"claims": [{"text": text, "evidence_ids": ids, "causal_strength": "UNSUPPORTED", "caveat": None}]}


@pytest.mark.parametrize("relation", list(SubjectRelation))
def test_subject_roundtrip_and_digest(relation):
    value = authority(relation.value, 5)
    assert EvidenceSubject.deserialize(value.serialize()) == value
    assert hashlib.sha256(value.serialize().encode()).hexdigest() == value.digest


def test_subject_digest_tamper_is_rejected():
    metadata = dict(snapshot("ISSUER", 8).payload["provenance"])
    metadata["page"] = 50
    with pytest.raises(ValueError, match="PROVENANCE_CHANGED"):
        subject_from_metadata(metadata)


@pytest.mark.parametrize("text,ids,allowed,expected", [
    ("公司主要业务是茅台酒生产与销售。", ["evidence:8"], True, "ISSUER"),
    ("贵州茅台主营包含房地产开发及租赁。", ["evidence:50"], False, None),
    ("控股股东集团从事房地产开发及租赁。", ["evidence:50"], True, "CONTROLLING_SHAREHOLDER"),
    ("控股股东集团涉及房地产等业务。", ["evidence:50"], True, "CONTROLLING_SHAREHOLDER"),
    ("公司主要业务是茅台酒生产与销售。", ["evidence:120"], False, None),
    ("控股股东集团从事茅台酒生产与销售。", ["evidence:8"], False, None),
    ("贵州茅台主营包含房地产开发及租赁。", ["evidence:8", "evidence:50"], False, None),
])
def test_compatibility_matrix(text, ids, allowed, expected):
    if allowed:
        buffered = assemble_narrative(source(), candidate(text, ids))
        assert buffered.plan.claims[0].claim_subject["relation"] == expected
    else:
        with pytest.raises(ValueError, match="NARRATIVE_(?:SUBJECT|CLAIM)"):
            assemble_narrative(source(), candidate(text, ids))


@pytest.mark.parametrize("text,ids", [
    ("另一家公司从事茅台酒生产与销售。", ["evidence:8"]),
    ("苹果公司主要业务是茅台酒生产与销售。", ["evidence:8"]),
    ("控股股东集团从事房地产开发，上市公司也从事房地产开发。", ["evidence:50"]),
    ("控股股东集团从事房地产开发，贵州茅台也从事房地产开发。", ["evidence:50"]),
    ("控股股东集团从事房地产开发，公司也从事房地产开发。", ["evidence:50"]),
    ("贵州茅台集团主要业务是茅台酒生产与销售。", ["evidence:8"]),
])
def test_native_claim_subject_is_not_inferred_from_query_alone(text, ids):
    with pytest.raises(ValueError, match="NARRATIVE_CLAIM"):
        assemble_narrative(source(), candidate(text, ids))


def test_old_index_cannot_supply_issuer_authority():
    src = source()
    first = src.evidence[0]
    metadata = dict(first.payload["provenance"])
    for key in ("evidence_subject_schema", "evidence_subject", "subject_provenance_digest"):
        metadata.pop(key)
    stale = replace(first, payload=_freeze({**first.payload, "provenance": metadata}))
    assert subject_from_metadata(metadata) is None
    with pytest.raises(ValueError, match="SUBJECT_UNQUALIFIED"):
        assemble_narrative(replace(src, evidence=(stale,)), candidate("公司主要业务是茅台酒生产与销售。", [first.evidence_id]))


def test_bundle_serialization_preserves_subject_without_rewriting():
    src = source()
    payload = json.loads(build_narrative_payload(src))
    for serialized, original in zip(payload["evidence"], src.evidence):
        assert serialized["payload"]["provenance"]["evidence_subject"] == original.payload["provenance"]["evidence_subject"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("bad_text,bad_ids,bad_caveat", [
    ("公司主要业务是茅台酒生产与销售。", ("evidence:120",), None),
    ("贵州茅台主营包含房地产开发及租赁。", ("evidence:50",), None),
    ("苹果公司主要业务是茅台酒生产与销售。", ("evidence:8",), None),
    ("控股股东集团从事房地产开发，上市公司也从事房地产开发。", ("evidence:50",), None),
    ("控股股东集团从事房地产开发，公司也从事房地产开发。", ("evidence:50",), None),
    ("控股股东集团从事房地产开发。", ("evidence:50",), "上市公司也从事房地产开发。"),
])
def test_hostile_supported_review_cannot_release_wrong_subject(stream, bad_text, bad_ids, bad_caveat):
    src = source()
    # Construct the retained hostile plan as if an injected generator skipped
    # initial admission. The final verifier must still independently rebuild it.
    safe = assemble_narrative(src, candidate("公司主要业务是茅台酒生产与销售。", ["evidence:8"]))
    bad = replace(safe.plan.claims[0], semantic_content=bad_text, evidence_ids=bad_ids, caveat=bad_caveat)
    plan = replace(safe.plan, claims=(bad,))
    text = "- " + bad_text + (" (" + bad_caveat + ")" if bad_caveat else "") + " [1]"
    buffered = BufferedNarrative(plan, text, bad_ids)
    generated = GeneratedNarrative(buffered, "deterministic-test-port", None, None, None)
    review = SemanticReview("hostile-supported-test", (SemanticClaimReview(bad.claim_id, bad.evidence_ids,
        EntailmentVerdict.SUPPORTED, bad.causal_strength, "Simulated erroneous SUPPORTED"),),
        semantic_input_digest(src, plan, text))
    generator, reviewer, ledger = Mock(), Mock(), Mock()
    generator.generate.return_value, reviewer.review.return_value = generated, review
    ledger.ready_index.return_value = {"document_id": 1, "source_sha256": "a" * 64}
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(tenant_id=1, id=2)
    app.include_router(build_grounded_answer_router(ledger, source_resolver=lambda **_: src,
        narrative_generator=generator, semantic_reviewer=reviewer, narrative_enabled=True))
    with TestClient(app) as client:
        response = client.post("/grounded-chat", json={"ingestion_job_id": "ready",
            "question": src.query, "answer_language": "zh-CN", "stream": stream})
    assert response.status_code == 409
    assert "房地产" not in response.text and "event: delta" not in response.text


def test_real_canonical_artifact_subject_authority():
    root = os.environ.get("P2D_SOURCE_ARTIFACT_ROOT")
    if not root:
        pytest.skip("real canonical artifacts explicitly supplied by qualification operator")
    root = Path(root)
    parse_sha = "1bd7a11a8baec69068d7cae506e8f19084cf6c28b658e2d0c006875495926058"
    quality_sha = "69357ec04d69bf75dc1bba40e5fc1b2d2c8a7c13273810dc22efc32be79a9fc2"
    parsed, quality = (json.loads((root / digest).read_bytes()) for digest in (parse_sha, quality_sha))
    values = project_subjects(parsed, quality, parse_sha=parse_sha, quality_sha=quality_sha)
    assert values[221].subject_relation_to_issuer == "CONTROLLING_SHAREHOLDER"
    assert values[221].subject_name == "中国贵州茅台酒厂（集团）有限责任公司"
    assert values[221].subject_source_block_id == "32d40fd5ffe31e88b69aeb8aab4e00d0"
    issuer = [v for c, v in zip(parsed["chunks"], values) if c["page"] == 8 and "公司主要业务是" in c["text"]]
    assert len(issuer) == 1 and issuer[0].subject_relation_to_issuer == "ISSUER"
