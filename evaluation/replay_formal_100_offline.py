"""Replay a frozen 100Q run through today's production grounding boundary.

This is a deterministic, provider-free diagnostic. It never regenerates model
answers, mutates frozen benchmark data, contacts a provider, or overwrites an
existing result directory. Its output is a grounding/policy replay, not a new
semantic grade for the historical answers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.planning.entity_extractor import prior_user_context_for_followup  # noqa: E402
from agent.reasoning_models import Evidence  # noqa: E402
from core.answer_grounding import sanitize_answer  # noqa: E402
from core.answer_policy import finalize_grounded_answer, no_evidence_response  # noqa: E402
from core.financial_grounding import extract_normalized_numbers  # noqa: E402
from core.query_scope import QueryScope, classify_query_scope  # noqa: E402

DEFAULT_SOURCE = ROOT / "evaluation/results/formal_20260916"
DEFAULT_OUTPUT = ROOT / "evaluation/results/offline_grounding_replay_20260917"
_ANSWER_MARKER = re.compile(
    r"^## (?:Answer \(LLM Answer\)|回答（LLM 模型回答）)\s*$", re.MULTILINE
)
_EVIDENCE_MARKER = re.compile(
    r"^## (?:Agent Evidence Analysis|智能体证据分析)\s*$", re.MULTILINE
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _main_answer(report: str) -> str:
    answer = _ANSWER_MARKER.search(report)
    if answer is None:
        # Some frozen unsupported-scope cases deliberately have a terse raw
        # answer rather than the normal report wrapper.
        if report.strip():
            return report.strip()
        raise ValueError("HISTORICAL_ANSWER_BOUNDARY_MISSING")
    body = report[answer.end():]
    evidence = _EVIDENCE_MARKER.search(body)
    body = body[:evidence.start()] if evidence else body
    if not body.strip():
        raise ValueError("HISTORICAL_ANSWER_EMPTY")
    return body.strip()


def _reference_index(reference: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    return {
        chunk_id: (text, metadata or {})
        for chunk_id, text, metadata in zip(
            reference["ids"], reference["documents"], reference["metadatas"], strict=True
        )
    }


def _resolved_evidence_question(row: dict[str, Any]) -> str:
    """Use the latest turn plus the same guarded history marker as runtime.

    ``original_question`` in frozen results may concatenate multiple turns.
    Passing that raw string to scope classification lets the previous turn's
    comparison/summary intent override the current follow-up. Resolve only
    valid referential follow-ups using the production history resolver.
    """

    question = str(row.get("question") or row.get("original_question") or "")
    setup_question = str(row.get("setup_question") or "").strip()
    if not setup_question:
        return question
    context = prior_user_context_for_followup(
        question,
        [{"role": "user", "content": setup_question}],
    )
    if context is None:
        return question
    prior_question, _companies = context
    return (
        f"{question}\nRelevant prior user request for reference resolution: "
        f"{prior_question}"
    )


def _evidence_for(
    row: dict[str, Any],
    chunks: dict[str, tuple[str, dict[str, Any]]],
) -> list[Evidence]:
    evidence: list[Evidence] = []
    for citation in row.get("citations", []):
        chunk_id = str(citation.get("chunk_id", ""))
        match = chunks.get(chunk_id)
        metadata = dict(match[1]) if match else {}
        is_valid = bool(
            match
            and metadata.get("source") == citation.get("source")
            and metadata.get("page") == citation.get("page")
        )
        if not is_valid:
            metadata = {"chunk_id": chunk_id, "content_type": "unverified"}
        else:
            metadata["chunk_id"] = chunk_id
        evidence.append(
            Evidence(
                content=match[0] if is_valid and match else "",
                source=str(citation.get("source", "")),
                company=str(metadata.get("company", "")),
                metadata=metadata,
            )
        )
    return evidence


def replay_one(
    row: dict[str, Any],
    historical_review: dict[str, Any],
    chunks: dict[str, tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    raw_answer = _main_answer(str(row.get("actual_answer", "")))
    # Multi-turn benchmark cases freeze both the immediate follow-up and the
    # setup turn. The production path grounds against the runtime-resolved
    # question; replay the same available history instead of dropping it.
    evidence_question = _resolved_evidence_question(row)
    evidence = _evidence_for(row, chunks)
    if not evidence:
        # Match the production no-citation branch; do not preserve a historical
        # empty/bare refusal when there is no retrieved source at all.
        raw_answer = no_evidence_response(evidence_question)
    finalized = finalize_grounded_answer(evidence_question, raw_answer, evidence)
    # Direct-chat definitions are deliberately outside the filing citation
    # gate.  Do not turn educational examples into false unsupported
    # financial claims during an offline post-check.
    checked = (
        finalized.grounded
        if classify_query_scope(evidence_question) is QueryScope.GENERAL_CONCEPT
        else sanitize_answer(evidence_question, finalized.answer, finalized.grounded.evidence)
    )
    plan = finalized.plan.as_dict(finalized.ledger, finalized.answer)
    # Match core.core_engine._project_answer_citations(): the API exposes only
    # evidence ranks actually referenced by the final answer, not every
    # semantically eligible context chunk.
    cited_ranks = sorted({
        int(value)
        for value in re.findall(r"\[Evidence\s+(\d+)\]", finalized.answer, re.I)
        if 1 <= int(value) <= len(finalized.grounded.evidence)
    })
    retained_ids = {
        str(finalized.grounded.evidence[rank - 1].metadata.get("chunk_id", ""))
        for rank in cited_ranks
        if finalized.grounded.evidence[rank - 1].metadata.get("chunk_id")
    }
    return {
        "id": row["id"],
        "language": row.get("language"),
        "question": row["question"],
        "evidence_question": evidence_question,
        "historical_grade": historical_review.get("answer_grade", row.get("answer_grade")),
        "historical_failure_modes": historical_review.get("failure_modes", []),
        "raw_answer": raw_answer,
        "final_answer": finalized.answer,
        "raw_claim_dispositions": dict(Counter(item.disposition for item in finalized.raw_grounding.claims)),
        "final_claim_dispositions": dict(Counter(item.disposition for item in checked.claims)),
        "final_unsupported_numeric_claims": sum(
            bool(extract_normalized_numbers(claim.text))
            for claim in checked.claims
            if claim.disposition == "UNSUPPORTED"
        ),
        "required_fact_plan": plan,
        "available_required_fact_coverage": (
            sum(bool(item["answer_present"]) for item in plan["required"]) / len(plan["required"])
            if plan["required"] else None
        ),
        "original_citation_count": len(row.get("citations", [])),
        "production_policy_retained_citation_ids": sorted(retained_ids),
    }


def run(source: Path, output: Path) -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"false", "0", "no", "off"}:
        raise RuntimeError("REAL_PROVIDER_MUST_BE_DISABLED")
    source = source.resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError("REFUSING_TO_OVERWRITE_EXISTING_REPLAY_ARTIFACT")
    raw_rows = _read_jsonl(source / "evaluation_100_results.jsonl")
    reviews = {item["id"]: item for item in _read_jsonl(source / "semantic_reviews.jsonl")}
    chunks = _reference_index(json.loads((source / "reference_chunks.json").read_text(encoding="utf-8")))
    if len(raw_rows) != 100 or len({item["id"] for item in raw_rows}) != 100:
        raise ValueError("EXPECTED_EXACTLY_100_UNIQUE_FROZEN_REQUESTS")
    output.mkdir(parents=True)
    rows = [replay_one(row, reviews.get(row["id"], {}), chunks) for row in raw_rows]
    pair_rows: dict[str, dict[str, dict[str, Any]]] = {}
    for item in rows:
        language, _, suffix = str(item["id"]).partition("-")
        pair_rows.setdefault(suffix, {})[language] = item
    pair_parity = []
    for suffix, pair in sorted(pair_rows.items()):
        if set(pair) != {"EN", "ZH"}:
            continue
        def present_facts(item: dict[str, Any]) -> set[tuple[str, str, str]]:
            return {
                (str(fact.get("company", "")), str(fact.get("metric_id", "")), str(fact.get("period", "")))
                for fact in item["required_fact_plan"].get("required", [])
                if fact.get("answer_present")
            }
        en, zh = present_facts(pair["EN"]), present_facts(pair["ZH"])
        pair_parity.append({
            "pair": suffix,
            "english_only_answered_facts": sorted(en - zh),
            "chinese_only_answered_facts": sorted(zh - en),
        })
    summary = {
        "scope": "OFFLINE_PRODUCTION_GROUNDING_REPLAY_NOT_SEMANTIC_REGRADING",
        "real_provider_calls": 0,
        "evaluator_calls": 0,
        "api_cost_usd": 0,
        "historical_grade_counts_unchanged": dict(Counter(item["historical_grade"] for item in rows)),
        "replayed_requests": len(rows),
        "citations_input": sum(item["original_citation_count"] for item in rows),
        "final_unsupported_numeric_claims": sum(item["final_unsupported_numeric_claims"] for item in rows),
        "bilingual_pairs_compared": len(pair_parity),
        "pairs_with_required_fact_parity_difference": sum(
            bool(item["english_only_answered_facts"] or item["chinese_only_answered_facts"])
            for item in pair_parity
        ),
        "pair_parity_semantics": "deterministic required-fact coverage parity only; not human semantic equivalence",
        "rows": rows,
        "bilingual_required_fact_parity": pair_parity,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "replay.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = run(args.source, args.output)
    printable = {
        key: value
        for key, value in result.items()
        if key not in {"rows", "bilingual_required_fact_parity"}
    }
    print(json.dumps(printable, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
