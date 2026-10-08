import json

import pytest

from evaluation.revalidate_semantic_reviews_offline import revalidate


def _write_fixture(source):
    answer = (
        "Tesla Q2 revenue was $22 billion [Evidence 1]. "
        "NVIDIA Q1 revenue was $81.6 billion [Evidence 2]."
    )
    row = {
        "id": "EN-001",
        "actual_answer": answer,
        "citations": [
            {"rank": 1, "chunk_id": "tesla", "source": "Tesla.pdf", "page": 1},
            {"rank": 2, "chunk_id": "nvidia", "source": "NVIDIA.pdf", "page": 2},
        ],
    }
    tesla_quote = "Tesla Q2 revenue was $22 billion in the filing."
    review = {
        "id": "EN-001",
        "citations": [
            {
                "rank": 1,
                "grade": "VALID_BUT_NOT_SUPPORTED",
                "query_relevance": "DIRECT",
                "answer_claim": "NVIDIA Q1 revenue was $81.6 billion",
                "evidence_quote": tesla_quote,
                "reason": "The claim belongs to another issuer.",
            },
            {
                "rank": 2,
                "grade": "VALID_SUPPORTED",
                "query_relevance": "DIRECT",
                "answer_claim": "NVIDIA Q1 revenue was $81.6 billion",
                "evidence_quote": "NVIDIA Q1 revenue was $81.6 billion in the filing.",
                "reason": "Exact company and value.",
            },
        ],
    }
    corpus = {
        "ids": ["tesla", "nvidia"],
        "documents": [
            tesla_quote,
            "NVIDIA Q1 revenue was $81.6 billion in the filing.",
        ],
        "metadatas": [
            {"source": "Tesla.pdf", "page": 1},
            {"source": "NVIDIA.pdf", "page": 2},
        ],
    }
    (source / "evaluation_100_results.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )
    (source / "semantic_reviews.jsonl").write_text(
        json.dumps(review) + "\n", encoding="utf-8"
    )
    (source / "reference_chunks.json").write_text(
        json.dumps(corpus), encoding="utf-8"
    )


def test_offline_revalidation_does_not_accept_a_marker_from_another_claim(tmp_path, monkeypatch):
    source = tmp_path / "source"
    output = tmp_path / "audit"
    source.mkdir()
    _write_fixture(source)
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "false")

    summary = revalidate(source, output)

    assert summary["real_provider_calls"] == 0
    assert summary["frozen_answer_grade_labels_changed"] is False
    assert summary["original_unsupported_reclassification"] == {
        "REVIEW_INDETERMINATE": 1
    }
    records = [
        json.loads(line)
        for line in (output / "citation_reviews.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["revalidated_grade"] == "REVIEW_INDETERMINATE"
    assert records[0]["annotation_validation_issues"] == [
        "answer_claim_not_attached_to_citation_rank"
    ]
    assert records[1]["revalidated_grade"] == "VALID_SUPPORTED"


def test_offline_revalidation_refuses_when_provider_flag_is_enabled(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _write_fixture(source)
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "true")

    with pytest.raises(RuntimeError, match="REAL_PROVIDER_MUST_BE_DISABLED"):
        revalidate(source, tmp_path / "audit")


def test_offline_revalidation_refuses_to_overwrite_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "source"
    output = tmp_path / "audit"
    source.mkdir()
    output.mkdir()
    _write_fixture(source)
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "false")

    with pytest.raises(FileExistsError, match="REFUSING_TO_OVERWRITE_CITATION_AUDIT"):
        revalidate(source, output)
