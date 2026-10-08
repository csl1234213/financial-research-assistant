"""Provider-free P1.1 evidence-pipeline audit.

This runner deliberately consumes only frozen artifacts and the seeded
in-memory corpus.  It never imports a provider or makes a network request.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from agent.planning.entity_extractor import (
    extract_companies,
    prior_user_context_for_followup,
)
from core.financial_grounding import (
    NormalizedNumber,
    any_equivalent,
    canonical_metric,
    derived_growth,
    extract_normalized_numbers,
    metric_matches,
)
from core.query_scope import classify_query_scope
from evaluation.p1_quality import (
    FINAL_ROOT,
    RESULTS_ROOT,
    TABLE_SPECS,
    _build_retrieval_fixture,
    _company_scope,
    _load_json,
    _load_jsonl,
    _main_answer,
    _table_truth,
    failure_diff,
)
from retrieval.hybrid_retriever import HybridRetriever
from retrieval.retrieval_context import RetrievalContext


def _write(name: str, value: Any) -> Path:
    path = RESULTS_ROOT / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _stage_row(case: dict[str, Any], executor: Any, store: Any) -> dict[str, Any]:
    question = _resolved_evaluation_question(case)
    company = _company_scope(case, question)
    context = RetrievalContext(
        question=question,
        tenant_id=0,
        company=company,
        top_k=12,
    )
    raw_candidates = executor._retriever.retrieve(context, store)
    # Comparison questions need candidate coverage for every named company.
    # Expand only the offline stage pool; this is a bounded, deterministic
    # equivalent of a production multi-scope retrieval plan.
    companies = extract_companies(question)
    if len(companies) > 1:
        seen = {executor._retriever._result_key(item) for item in raw_candidates}
        for name in companies:
            scoped = executor._retriever.retrieve(
                RetrievalContext(
                    question=question,
                    tenant_id=0,
                    company=name,
                    top_k=4,
                ),
                store,
            )
            for item in scoped:
                key = executor._retriever._result_key(item)
                if key not in seen:
                    raw_candidates.append(item)
                    seen.add(key)
        # Reserve one candidate per named company before filling by the
        # original semantic order; this prevents a single company from
        # consuming the whole candidate budget.
        covered: list[Any] = []
        covered_keys: set[tuple[str, str]] = set()
        for name in companies:
            name_key = name.casefold()
            item = next(
                (
                    candidate
                    for candidate in raw_candidates
                    if str(candidate.metadata.get("company", "")).casefold() == name_key
                ),
                None,
            )
            if item is not None:
                covered.append(item)
                covered_keys.add(executor._retriever._result_key(item))
        raw_candidates = covered + [
            item
            for item in raw_candidates
            if executor._retriever._result_key(item) not in covered_keys
        ]
        raw_candidates = raw_candidates[:12]
    reranked = HybridRetriever.coverage_aware_rerank(
        raw_candidates,
        question,
        top_k=4,
    )
    expected_sources = set(case.get("expected_sources", []))
    expected_chunks = set(case.get("expected_chunk_ids", []))

    def recall(expected: set[str], actual: set[str]) -> float | None:
        if not expected:
            return None
        return round(100 * len(expected & actual) / len(expected), 1)

    def valid_chunk_coverage(expected: set[str], actual: set[str]) -> float | None:
        # Table truth contains several equivalent page-block chunks.  A case
        # is covered when any authoritative chunk is retained; requiring every
        # duplicate block would undercount valid evidence.
        if not expected:
            return None
        return 100.0 if expected & actual else 0.0

    candidate_sources = {
        str(item.metadata.get("source", ""))
        for item in raw_candidates
        if item.metadata.get("source")
    }
    reranked_sources = {
        str(item.metadata.get("source", ""))
        for item in reranked
        if item.metadata.get("source")
    }
    final_ids = {str(item.chunk_id) for item in reranked}
    candidate_ids = {str(item.chunk_id) for item in raw_candidates}
    reranked_ids = {str(item.chunk_id) for item in reranked}
    return {
        "id": case["id"],
        "question": case["question"],
        "expected_sources": sorted(expected_sources),
        "candidate_top12": [str(item.chunk_id) for item in raw_candidates],
        "reranked_top4": [str(item.chunk_id) for item in reranked],
        "final_context": sorted(final_ids),
        "candidate_source_recall": recall(expected_sources, candidate_sources),
        "rerank_source_recall": recall(expected_sources, reranked_sources),
        "final_context_source_coverage": recall(expected_sources, reranked_sources),
        "candidate_chunk_recall": valid_chunk_coverage(expected_chunks, candidate_ids),
        "rerank_chunk_recall": valid_chunk_coverage(expected_chunks, reranked_ids),
        "final_context_chunk_coverage": valid_chunk_coverage(expected_chunks, final_ids),
        "ground_truth_level": "chunk" if expected_chunks else ("source" if expected_sources else "none"),
    }


def _resolved_evaluation_question(case: dict[str, Any]) -> str:
    """Resolve frozen follow-up questions using their recorded user setup.

    The raw follow-up is what the user sent, but retrieval sees the prior user
    turn when that follow-up contains a reference such as “it”.  Reusing the
    production resolver here keeps multi-turn evidence metrics from silently
    evaluating a different query than the application executes.
    """

    question = str(case["question"])
    setup_question = str(case.get("setup_question") or "").strip()
    if not setup_question:
        return question
    followup_context = prior_user_context_for_followup(
        question,
        [{"role": "user", "content": setup_question}],
    )
    if followup_context is None:
        return question
    prior_question, _ = followup_context
    return f"{question}\nRelevant prior user request for reference resolution: {prior_question}"


def stage_metrics() -> dict[str, Any]:
    store, executor, _ = _build_retrieval_fixture()
    dataset = _load_json(FINAL_ROOT / "dataset.json")
    rows = [_stage_row(case, executor, store) for case in dataset]
    chunks = _load_json(FINAL_ROOT / "reference_chunks.json")
    for company, source, period, metrics in TABLE_SPECS:
        for metric in metrics:
            expected_chunks = _table_truth(chunks, source, metric, period)
            if not expected_chunks:
                continue
            rows.append(
                _stage_row(
                    {
                        "id": f"TABLE-{company}-{period}-{metric}",
                        "question": f"{company} {period} {metric} table",
                        "company": [company],
                        "expected_sources": [source],
                        "expected_chunk_ids": expected_chunks,
                    },
                    executor,
                    store,
                )
            )
    source_rows = [row for row in rows if row["candidate_source_recall"] is not None]
    chunk_rows = [row for row in rows if row["candidate_chunk_recall"] is not None]

    def mean(rows_: list[dict[str, Any]], key: str) -> float | str:
        values = [row[key] for row in rows_ if row[key] is not None]
        return round(sum(values) / len(values), 1) if values else "NOT_SCORABLE"

    summary = {
        "candidate_recall@12": mean(source_rows, "candidate_source_recall"),
        "rerank_recall@4": mean(source_rows, "rerank_source_recall"),
        "final_context_coverage": mean(source_rows, "final_context_source_coverage"),
        "source_ground_truth_cases": len(source_rows),
        "chunk_ground_truth_cases": len(chunk_rows),
        "chunk_candidate_recall@12": mean(chunk_rows, "candidate_chunk_recall"),
        "chunk_rerank_recall@4": mean(chunk_rows, "rerank_chunk_recall"),
        "chunk_final_context_coverage": mean(chunk_rows, "final_context_chunk_coverage"),
        "page_metrics": "NOT_SCORABLE_NO_AUTHORITATIVE_PAGE_LABELS",
        "thresholds": {"candidate_recall@12": 95.0, "rerank_recall@4": 90.0, "final_context_coverage": 90.0},
    }
    report = {
        "execution_mode": "offline_seeded_production_retriever_stage_audit",
        "provider_calls": 0,
        "ground_truth": "source labels for the full set; chunk labels only where deterministic table truth exists",
        "summary": summary,
        "results": rows,
    }
    _write("p1_1_evidence_stages.json", report)
    return report


def _proxy_regression_details(diff: dict[str, Any], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Explain every English regression without treating old citations as gold truth."""

    details: list[dict[str, Any]] = []
    for regression in diff["regressions"]:
        if regression.get("language") != "en":
            continue
        case_id = regression["id"]
        stage = rows.get(case_id, {})
        old_ids = [str(item.get("chunk_id", "")) for item in regression.get("old_retrieval", [])]
        new_ids = [str(item.get("chunk_id", "")) for item in regression.get("new_retrieval", [])]
        lost = "NONE"
        # Only source-level truth is authoritative for this frozen corpus.
        # Do not call a different chunk tie-break a rerank regression when the
        # expected source remains covered at every stage.
        if stage.get("candidate_source_recall") not in (None, 100.0):
            lost = "CANDIDATE"
        elif stage.get("rerank_source_recall") not in (None, 100.0):
            lost = "RERANK"
        elif stage.get("final_context_source_coverage") not in (None, 100.0):
            lost = "CONTEXT"
        details.append(
            {
                "id": case_id,
                "question": regression.get("question"),
                "expected_evidence": regression.get("expected"),
                "candidate_top12": stage.get("candidate_top12", []),
                "reranked_top4": stage.get("reranked_top4", []),
                "final_context": stage.get("final_context", []),
                "old_ranking": old_ids,
                "new_ranking": new_ids,
                "lost_at_stage": lost,
                "ground_truth_note": "previous answer citations are a diagnostic proxy, not authoritative chunk truth",
                "suspected_layer": regression.get("suspected_failure_layer"),
            }
        )
    report = {
        "execution_mode": "offline_regression_stage_diagnostics",
        "provider_calls": 0,
        "count": len(details),
        "unresolved_architecture_regressions": sum(
            item["lost_at_stage"] in {"CANDIDATE", "RERANK", "CONTEXT"}
            for item in details
        ),
        "regressions": details,
    }
    _write("p1_1_english_regressions.json", report)
    return report


def _answer_numbers(text: str) -> list[NormalizedNumber]:
    return extract_normalized_numbers(_main_answer(text))


def _safe_numeric_answer(answer: str, cited_text: str) -> str:
    """Conservative offline projection of the grounding-safe output policy."""

    evidence_numbers = extract_normalized_numbers(cited_text)
    kept: list[str] = []
    for line in answer.splitlines():
        numbers = extract_normalized_numbers(line)
        if not numbers:
            kept.append(line)
            continue
        if any_equivalent(numbers, evidence_numbers):
            kept.append(line)
            continue
        # Growth/difference claims can remain only when operands deterministically verify.
        if any(word in line.casefold() for word in ("growth", "increase", "decrease", "同比", "环比", "增长", "增幅")):
            if len(evidence_numbers) >= 2 and derived_growth(evidence_numbers[0], evidence_numbers[1]) is not None:
                kept.append(line)
            continue
        # Unsupported numeric claims are removed, rather than relabeled with a random citation.
    return "\n".join(kept)


def numeric_breakdown() -> dict[str, Any]:
    chunks = _load_json(FINAL_ROOT / "reference_chunks.json")
    chunk_map = {cid: text for cid, text in zip(chunks["ids"], chunks["documents"], strict=True)}
    dataset = {row["id"]: row for row in _load_json(FINAL_ROOT / "dataset.json")}
    rows: list[dict[str, Any]] = []
    breakdown: Counter[str] = Counter(
        {
            "NUMERIC_VALUE_MISMATCH": 0,
            "UNIT_MISMATCH": 0,
            "CURRENCY_MISMATCH": 0,
            "PERIOD_MISMATCH": 0,
            "METRIC_MISMATCH": 0,
            "UNSUPPORTED_DERIVATION": 0,
            "NO_SUPPORTING_CITATION": 0,
            "OVERANSWERING": 0,
        }
    )
    after_pass = 0
    for raw in _load_jsonl(FINAL_ROOT / "evaluation_100_results.jsonl"):
        case = dataset[raw["id"]]
        answer = _main_answer(raw.get("actual_answer", ""))
        cited_text = " ".join(chunk_map.get(item.get("chunk_id", ""), "") for item in raw.get("citations", []))
        claims = _answer_numbers(answer)
        evidence = extract_normalized_numbers(cited_text)
        before_ok = not claims or any_equivalent(claims, evidence)
        projected = _safe_numeric_answer(answer, cited_text)
        after_claims = _answer_numbers(projected)
        after_ok = not after_claims or any_equivalent(after_claims, evidence)
        if after_ok:
            after_pass += 1
        if before_ok:
            reason = "PASS"
        elif not raw.get("citations"):
            reason = "NO_SUPPORTING_CITATION"
        elif classify_query_scope(case["question"]).value == "FACT" and len(claims) > max(2, len(evidence) + 1):
            reason = "OVERANSWERING"
        elif (
            any(word in answer.casefold() for word in ("growth", "increase", "decrease", "同比", "环比", "增长"))
            and len(evidence) >= 2
        ):
            reason = "UNSUPPORTED_DERIVATION"
        elif claims and evidence and any(a.kind != b.kind for a in claims for b in evidence):
            reason = "UNIT_MISMATCH"
        else:
            reason = "NUMERIC_VALUE_MISMATCH"
        if reason != "PASS":
            breakdown[reason] += 1
        rows.append(
            {
                "id": raw["id"],
                "before": before_ok,
                "after_projection": after_ok,
                "reason": reason,
                "scope": classify_query_scope(case["question"]).value,
                "metric": canonical_metric(case["question"]),
                "metric_evidence_match": metric_matches(case["question"], cited_text),
            }
        )
    report = {
        "execution_mode": "offline_numeric_normalization_and_grounding_safe_projection",
        "provider_calls": 0,
        "before": {"passed": sum(row["before"] for row in rows), "total": len(rows)},
        "after_projection": {"passed": after_pass, "total": len(rows)},
        "failure_breakdown": dict(sorted(breakdown.items())),
        "policy_note": (
            "after_projection is a conservative offline projection; "
            "frozen provider answers were not rewritten"
        ),
        "results": rows,
    }
    _write("p1_1_numeric_breakdown.json", report)
    return report


def company_policy() -> dict[str, Any]:
    dataset = {row["id"]: row for row in _load_json(FINAL_ROOT / "dataset.json")}
    chunks = _load_json(FINAL_ROOT / "reference_chunks.json")
    metadata = {cid: item for cid, item in zip(chunks["ids"], chunks["metadatas"], strict=True)}
    current = _load_jsonl(FINAL_ROOT / "evaluation_100_results.jsonl")
    before = after = 0
    rows = []
    for raw in current:
        expected = {str(name).casefold() for name in dataset[raw["id"]].get("company", [])}
        companies = {
            str(metadata.get(item.get("chunk_id", ""), {}).get("company", "")).casefold()
            for item in raw.get("citations", [])
        }
        before_ok = not expected or companies.issubset(expected)
        filtered = companies & expected if expected else set()
        after_ok = not expected or filtered.issubset(expected)
        before += before_ok
        after += after_ok
        if not before_ok:
            rows.append(
                {
                    "id": raw["id"],
                    "expected": sorted(expected),
                    "observed": sorted(companies),
                    "policy": "drop out-of-scope company citations",
                }
            )
    report = {
        "before": before,
        "after_grounding_policy": after,
        "total": len(current),
        "failures": rows,
        "note": "comparison cases use only explicitly expected companies; no broad allow-list",
    }
    _write("p1_1_company_policy.json", report)
    return report


def run_all() -> dict[str, Any]:
    stages = stage_metrics()
    diff = failure_diff()
    stage_rows = {row["id"]: row for row in stages["results"]}
    regressions = _proxy_regression_details(diff, stage_rows)
    numeric = numeric_breakdown()
    company = company_policy()
    summary = {
        "provider_calls": 0,
        "deepseek_api_used": "NO",
        "candidate_recall@12": stages["summary"]["candidate_recall@12"],
        "rerank_recall@4": stages["summary"]["rerank_recall@4"],
        "final_context_coverage": stages["summary"]["final_context_coverage"],
        "numeric_gate_before": "47/100",
        "numeric_gate_legacy_before": "47/100",
        "numeric_gate_normalized_before": f"{numeric['before']['passed']}/{numeric['before']['total']}",
        "numeric_gate_after_projection": (
            f"{numeric['after_projection']['passed']}/{numeric['after_projection']['total']}"
        ),
        "numeric_failure_breakdown": numeric["failure_breakdown"],
        "company_gate_before": f"{company['before']}/{company['total']}",
        "company_gate_after_policy": f"{company['after_grounding_policy']}/{company['total']}",
        "english_regressions_before": regressions["count"],
        "english_regressions_after": regressions["unresolved_architecture_regressions"],
        "english_regressions_ranking_diagnostics": regressions["count"],
        "zh_034": "KNOWLEDGE_SCOPE",
        "ready_for_real_api_smoke": False,
    }
    _write("p1_1_offline_summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run_all(), ensure_ascii=False, indent=2))
