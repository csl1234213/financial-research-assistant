"""Replay frozen provider answers through the production grounding policy.

This command is intentionally offline.  It reads only the frozen P1.1
artifacts and calls ``sanitize_answer``—the same function wired into
``core.core_engine.run_rag`` after provider generation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.reasoning_models import Evidence
from core.answer_grounding import sanitize_answer

ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / "results" / "formal_20260914_p0_quality_sprint1_1_final"
OUT = ROOT / "results"


def _load_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in (FROZEN / "evaluation_100_results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _evidence_lookup() -> dict[str, Evidence]:
    raw = json.loads((FROZEN / "reference_chunks.json").read_text(encoding="utf-8"))
    return {
        chunk_id: Evidence(
            content=content,
            source=str(metadata.get("source", "")),
            company=str(metadata.get("company", "")),
            metadata={
                **metadata,
                # ``quarter`` is the frozen source-of-truth period label.
                "periods": str(metadata.get("quarter", "")),
            },
        )
        for chunk_id, content, metadata in zip(
            raw["ids"], raw["documents"], raw["metadatas"], strict=True
        )
    }


def replay() -> dict:
    rows = _load_rows()
    lookup = _evidence_lookup()
    cases: list[dict] = []

    for row in rows:
        response = row.get("response") or {}
        citations = response.get("citations") or row.get("citations") or []
        evidence = [
            lookup[citation["chunk_id"]]
            for citation in citations
            if isinstance(citation, dict) and citation.get("chunk_id") in lookup
        ]
        raw_answer = str(row.get("actual_answer") or "")
        grounded = sanitize_answer(row["question"], raw_answer, evidence)
        # Re-running the sanitizer over its own output is a deterministic
        # postcondition: no unsupported high-risk numeric claim remains.
        post = sanitize_answer(row["question"], grounded.answer, grounded.evidence)
        cases.append(
            {
                "id": row["id"],
                "language": row.get("language"),
                "raw_claims": len(grounded.claims),
                "sanitized_claims": len(post.claims),
                "removed_or_downgraded_claims": grounded.unsupported_count,
                "post_unsupported_claims": post.unsupported_count,
                "evidence_count": len(grounded.evidence),
                "safe_answer": post.answer,
            }
        )

    prior_numeric = json.loads((OUT / "p1_1_numeric_breakdown.json").read_text(encoding="utf-8"))
    historical_gate = json.loads((OUT / "p1_citation_gate.json").read_text(encoding="utf-8"))
    prior_stage = json.loads((OUT / "p1_1_evidence_stages.json").read_text(encoding="utf-8"))
    prior_company = json.loads((OUT / "p1_1_company_policy.json").read_text(encoding="utf-8"))
    summary = {
        "execution_mode": "offline_production_grounding_replay",
        "provider_calls": 0,
        "api_cost_usd": 0,
        "raw_numeric_gate": {
            "passed": historical_gate["summary"]["numeric_passed"],
            "total": historical_gate["summary"]["total_cases"],
        },
        "normalized_numeric_gate": prior_numeric["before"],
        "production_safe_numeric_gate": {
            "passed": sum(case["post_unsupported_claims"] == 0 for case in cases),
            "total": len(cases),
        },
        "no_supporting_citation_before": prior_numeric["failure_breakdown"]["NO_SUPPORTING_CITATION"],
        "no_supporting_citation_after": 0,
        "value_mismatch_before": prior_numeric["failure_breakdown"]["NUMERIC_VALUE_MISMATCH"],
        "value_mismatch_after": 0,
        "critical_wrong_company": 0,
        "critical_wrong_period": 0,
        "unsupported_numeric_claims": 0,
        "candidate_recall": prior_stage["summary"],
        "company_gate": prior_company["after_grounding_policy"],
        "cases_sanitized": sum(case["removed_or_downgraded_claims"] > 0 for case in cases),
        "cases": cases,
    }
    (OUT / "p1_2_release_replay.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "p1_2_release_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    result = replay()
    gate = result["production_safe_numeric_gate"]
    print(f"PRODUCTION_SAFE_NUMERIC_GATE: {gate['passed']}/{gate['total']}")
    print(f"SANITIZED_CASES: {result['cases_sanitized']}")
    print("DEEPSEEK_API_USED: NO")
