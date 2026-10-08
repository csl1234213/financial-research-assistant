"""Revalidate frozen citation-review annotations without any model calls.

This checks source identity, exact quote spans, exact answer spans, and local
answer-claim-to-citation-marker attachment. It does not re-judge semantic
entailment or change the historical answer-grade labels.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.semantic_review import main_answer, validate_citation_annotation  # noqa: E402

DEFAULT_SOURCE = ROOT / "evaluation/results/formal_20260916"
DEFAULT_OUTPUT = ROOT / "evaluation/results/offline_citation_revalidation_20260918_v1"
PROVIDER_DISABLED = {"false", "0", "no", "off"}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def revalidate(source: Path, output: Path) -> dict[str, Any]:
    """Write a non-overwriting, provider-free citation annotation audit."""

    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in PROVIDER_DISABLED:
        raise RuntimeError("REAL_PROVIDER_MUST_BE_DISABLED")
    source = source.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError("REFUSING_TO_OVERWRITE_CITATION_AUDIT")

    rows = _jsonl(source / "evaluation_100_results.jsonl")
    reviews = _jsonl(source / "semantic_reviews.jsonl")
    review_by_id = {str(item["id"]): item for item in reviews}
    if not rows or len(rows) != len(review_by_id):
        raise ValueError("FROZEN_RESULT_AND_REVIEW_ROWS_MUST_MATCH")
    if len({str(item["id"]) for item in rows}) != len(rows):
        raise ValueError("DUPLICATE_FROZEN_RESULT_ID")

    corpus = json.loads((source / "reference_chunks.json").read_text(encoding="utf-8"))
    chunks = {
        str(chunk_id): (str(text), metadata or {})
        for chunk_id, text, metadata in zip(
            corpus["ids"], corpus["documents"], corpus["metadatas"], strict=True
        )
    }
    old_grades: Counter[str] = Counter()
    new_grades: Counter[str] = Counter()
    unsupported_reclassified: Counter[str] = Counter()
    issues: Counter[str] = Counter()
    audited: list[dict[str, Any]] = []

    for row in rows:
        row_id = str(row["id"])
        raw_citations = {int(item["rank"]): item for item in row.get("citations", [])}
        answer = main_answer(str(row.get("actual_answer", "")))
        for annotation in review_by_id[row_id].get("citations", []):
            rank = int(annotation["rank"])
            citation = raw_citations.get(rank, {})
            chunk = chunks.get(str(citation.get("chunk_id", "")))
            chunk_text, metadata = chunk if chunk else ("", {})
            source_valid = bool(
                chunk
                and metadata.get("source") == citation.get("source")
                and metadata.get("page") == citation.get("page")
            )
            result = validate_citation_annotation(
                {"rank": rank, "chunk_text": chunk_text},
                annotation,
                answer,
                source_valid=source_valid,
            )
            original_grade = str(annotation.get("grade", ""))
            grade = str(result.get("grade", ""))
            old_grades[original_grade] += 1
            new_grades[grade] += 1
            if original_grade == "VALID_BUT_NOT_SUPPORTED":
                unsupported_reclassified[grade] += 1
            issues.update(result.get("annotation_validation_issues", []))
            audited.append(
                {
                    "id": row_id,
                    "rank": rank,
                    "original_grade": original_grade,
                    "revalidated_grade": grade,
                    "source_valid": source_valid,
                    "annotation_validation_issues": result.get(
                        "annotation_validation_issues", []
                    ),
                    "answer_claim": annotation.get("answer_claim", ""),
                    "evidence_quote": annotation.get("evidence_quote", ""),
                    "reason": annotation.get("reason", ""),
                }
            )

    summary = {
        "scope": "OFFLINE_ANNOTATION_INTEGRITY_REVALIDATION_NOT_SEMANTIC_REGRADING",
        "real_provider_calls": 0,
        "evaluator_calls": 0,
        "api_cost_usd": 0,
        "frozen_answer_grade_labels_changed": False,
        "questions": len(rows),
        "citation_annotations": sum(new_grades.values()),
        "original_citation_grade_counts": dict(old_grades),
        "revalidated_citation_grade_counts": dict(new_grades),
        "original_unsupported_reclassification": dict(unsupported_reclassified),
        "annotation_integrity_issues": dict(issues),
    }
    output.mkdir(parents=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "citation_reviews.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in audited),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(revalidate(args.source, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
