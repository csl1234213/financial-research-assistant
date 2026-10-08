"""Provider-free P1 quality analysis over frozen evaluation artifacts.

This module intentionally never imports an LLM client and never makes a network
request.  It compares frozen application answers, runs the production hybrid
retriever against a deterministic in-memory corpus, and applies deterministic
company/period/numeric citation checks.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from agent.planning.entity_extractor import extract_companies
from core.retrieval_tool_adapter import TenantRetrievalToolExecutor
from evaluation.retrieval_dataset import RetrievalCorpusDocument
from evaluation.retrieval_gate import (
    AdversarialInMemoryEvaluationStore,
    SeededHashEmbeddingModel,
)
from retrieval.hybrid_retriever import HybridRetriever
from retrieval.periods import matches_filter, query_filters

ROOT = Path(__file__).resolve().parents[1]
FINAL_ROOT = ROOT / "evaluation" / "results" / "formal_20260914_p0_quality_sprint1_1_final"
BASELINE_ROOT = ROOT / "evaluation" / "results" / "formal_20260914_budget8192"
RESULTS_ROOT = ROOT / "evaluation" / "results"

_NUMBER = re.compile(r"(?<![A-Za-z])\$?\d+(?:[,.]\d+)*(?:\.\d+)?%?")
_GRADE_RANK = {"FAILED": 0, "INCORRECT": 1, "PARTIAL": 2, "CORRECT": 3}

TABLE_SPECS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "Tesla",
        "Tesla_Q2_2025.pdf",
        "Q2 2025",
        (
            "revenue",
            "gross margin",
            "EPS",
            "net income",
            "cash flow",
            "services",
            "automotive",
            "energy",
            "operating income",
        ),
    ),
    (
        "NVIDIA",
        "NVIDIA_Q1_FY2027.pdf",
        "Q1 FY2027",
        (
            "revenue",
            "gross margin",
            "data center",
            "EPS",
            "net income",
            "cash flow",
            "operating income",
            "diluted",
        ),
    ),
    (
        "Apple",
        "Apple_Q2_2026.pdf",
        "Q2 2026",
        ("revenue", "gross margin", "EPS", "net income", "cash flow", "operating income", "iPhone"),
    ),
)

TABLE_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "revenues"),
    "gross margin": ("gross margin",),
    "data center": ("data center", "datacenter"),
    "EPS": ("eps", "earnings per share"),
    "net income": ("net income", "net profit"),
    "cash flow": ("cash flow", "cash provided"),
    "services": ("services and other", "services revenue"),
    "automotive": ("automotive",),
    "energy": ("energy generation", "energy", "storage"),
    "operating income": ("operating income", "income from operations", "operating margin"),
    "diluted": ("diluted",),
    "iPhone": ("iphone",),
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(name: str, value: Any) -> Path:
    path = RESULTS_ROOT / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _main_answer(report: str) -> str:
    for marker in ("## Agent Evidence Analysis", "## 智能体证据分析", "## Agent Evidence", "## 智能体分析"):
        report = report.split(marker)[0]
    return report


def _grade_map(path: Path) -> dict[str, str]:
    grades: dict[str, str] = {}
    for row in _load_jsonl(path):
        grade = str(row.get("answer_grade", "UNKNOWN_REVIEW_FAILED")).strip().upper()
        grades[row["id"]] = grade
    return grades


def _retrieval_ids(row: dict[str, Any]) -> set[str]:
    return {str(c.get("chunk_id")) for c in row.get("citations", []) if c.get("chunk_id")}


def _failure_layer(old: dict[str, Any], new: dict[str, Any], expected_sources: list[str]) -> str:
    old_ids = _retrieval_ids(old)
    new_ids = _retrieval_ids(new)
    if expected_sources and old_ids != new_ids:
        if not new_ids:
            return "RETRIEVAL_RECALL"
        return "RERANK"
    if old.get("error") != new.get("error"):
        return "ROUTING"
    if old_ids == new_ids and expected_sources:
        return "REASONING"
    return "DATASET" if not expected_sources else "QUERY_PARSING"


def failure_diff() -> dict[str, Any]:
    """Compare the frozen P0 answer set with the current P1.1 answer set."""

    old_rows = {row["id"]: row for row in _load_jsonl(BASELINE_ROOT / "evaluation_100_results.jsonl")}
    new_rows = {row["id"]: row for row in _load_jsonl(FINAL_ROOT / "evaluation_100_results.jsonl")}
    old_grades = _grade_map(BASELINE_ROOT / "semantic_reviews.jsonl")
    new_grades = _grade_map(FINAL_ROOT / "semantic_reviews.jsonl")
    dataset = {row["id"]: row for row in _load_json(FINAL_ROOT / "dataset.json")}
    counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for case_id in sorted(new_rows):
        old_grade = old_grades.get(case_id, "UNKNOWN_REVIEW_FAILED")
        new_grade = new_grades.get(case_id, "UNKNOWN_REVIEW_FAILED")
        if old_grade == new_grade:
            category = f"UNCHANGED_{new_grade}"
        elif old_grade not in _GRADE_RANK or new_grade not in _GRADE_RANK:
            category = "UNCOMPARABLE_REVIEW"
        elif _GRADE_RANK[new_grade] > _GRADE_RANK[old_grade]:
            category = "IMPROVED"
        elif _GRADE_RANK[new_grade] < _GRADE_RANK[old_grade]:
            category = "REGRESSED"
        else:
            category = "CHANGED"
        counts[category] += 1
        if category in {"IMPROVED", "REGRESSED"}:
            old = old_rows[case_id]
            new = new_rows[case_id]
            expected = list(dataset[case_id].get("expected_sources", []))
            rows.append(
                {
                    "id": case_id,
                    "language": dataset[case_id].get("language"),
                    "question": new.get("question"),
                    "expected": dataset[case_id].get("expected_answer"),
                    "old_answer": _main_answer(old.get("actual_answer", "")),
                    "new_answer": _main_answer(new.get("actual_answer", "")),
                    "old_retrieval": old.get("citations", []),
                    "new_retrieval": new.get("citations", []),
                    "old_grade": old_grade,
                    "new_grade": new_grade,
                    "suspected_failure_layer": _failure_layer(old, new, expected),
                    "category": category,
                }
            )
    report = {
        "mode": "offline_frozen_artifact_analysis",
        "provider_calls": 0,
        "baseline": BASELINE_ROOT.name,
        "current": FINAL_ROOT.name,
        "counts": dict(sorted(counts.items())),
        "english_regression_count": sum(
            1 for row in rows if row["category"] == "REGRESSED" and row["language"] == "en"
        ),
        "regressions": [row for row in rows if row["category"] == "REGRESSED"],
        "improvements": [row for row in rows if row["category"] == "IMPROVED"],
    }
    _write("p1_failure_diff.json", report)
    return report


def _build_retrieval_fixture(
    reference_root: Path = FINAL_ROOT,
) -> tuple[Any, TenantRetrievalToolExecutor, dict[str, dict[str, Any]]]:
    """Build the deterministic retrieval test double from a frozen corpus.

    The default preserves the original P1.1 fixture.  Supplying another
    frozen-artifact directory lets audits replay the exact corpus captured
    with a later answer set instead of silently testing stale chunk IDs.
    """

    chunks = _load_json(reference_root / "reference_chunks.json")
    corpus: list[RetrievalCorpusDocument] = []
    metadata_by_chunk: dict[str, dict[str, Any]] = {}
    for chunk_id, content, raw_metadata in zip(chunks["ids"], chunks["documents"], chunks["metadatas"], strict=True):
        metadata = dict(raw_metadata)
        metadata_by_chunk[chunk_id] = metadata
        safe_metadata = {
            key: value for key, value in metadata.items() if key not in {"tenant_id", "company", "source", "page"}
        }
        corpus.append(
            RetrievalCorpusDocument(
                document_id=str(metadata.get("document_id", "")),
                chunk_id=chunk_id,
                tenant_id=int(metadata.get("tenant_id", 0)),
                company=str(metadata.get("company", "")),
                source_filename=str(metadata.get("source", "")),
                page=metadata.get("page", ""),
                content=content,
                metadata=safe_metadata,
            )
        )
    model = SeededHashEmbeddingModel(seed=20260914)
    store = AdversarialInMemoryEvaluationStore(corpus, model)
    executor = TenantRetrievalToolExecutor(HybridRetriever(model))
    return store, executor, metadata_by_chunk


def _company_scope(case: dict[str, Any], question: str) -> str | None:
    companies = case.get("company") or extract_companies(question)
    return companies[0] if len(companies) == 1 else None


def retrieval_benchmark() -> dict[str, Any]:
    store, executor, _ = _build_retrieval_fixture()
    dataset = _load_json(FINAL_ROOT / "dataset.json")
    results: list[dict[str, Any]] = []
    for case in dataset:
        expected = set(case.get("expected_sources", []))
        company = _company_scope(case, case["question"])
        for top_k in (4, 8, 12):
            evidence = executor.execute(
                store=store,
                query=case["question"],
                tenant_id=0,
                company=company,
                top_k=top_k,
                include_public=False,
            )
            sources = [item.source for item in evidence]
            if not expected and case.get("category") == "direct_chat":
                status = "NOT_APPLICABLE_DIRECT_CHAT"
                source_recall = None
            elif expected:
                matched = expected & set(sources)
                source_recall = round(100 * len(matched) / len(expected), 1)
                status = "PASS" if source_recall == 100 else "FAIL"
            else:
                source_recall = None
                status = "PASS" if not sources else "FAIL_UNSUPPORTED_SOURCE"
            results.append(
                {
                    "id": case["id"],
                    "top_k": top_k,
                    "company_scope": company,
                    "expected_sources": sorted(expected),
                    "retrieved_sources": sources,
                    "source_recall": source_recall,
                    "status": status,
                }
            )
    summary: dict[str, Any] = {
        "total_cases": len(dataset),
        "metrics": {},
        "page_recall": "NOT_SCORABLE_NO_AUTHORITATIVE_PAGE_LABELS",
    }
    for top_k in (4, 8, 12):
        values = [row["source_recall"] for row in results if row["top_k"] == top_k and row["source_recall"] is not None]
        summary["metrics"][f"source_recall@{top_k}"] = round(sum(values) / len(values), 1) if values else 0.0
    summary["eligible_cases"] = sum(1 for row in results if row["top_k"] == 12 and row["source_recall"] is not None)
    summary["negative_scope_pass"] = sum(
        1 for row in results if row["top_k"] == 12 and row["status"] in {"PASS", "NOT_APPLICABLE_DIRECT_CHAT"}
    )
    summary["thresholds"] = {"source_recall@4": 80.0, "source_recall@8": 90.0, "source_recall@12": 95.0}
    summary["threshold_passed"] = all(
        summary["metrics"][f"source_recall@{k}"] >= summary["thresholds"][f"source_recall@{k}"] for k in (4, 8, 12)
    )
    report = {
        "execution_mode": "offline_seeded_production_hybrid_retriever",
        "provider_calls": 0,
        "ground_truth": "source-level only; authoritative chunk/page labels were not present in the frozen dataset",
        "summary": summary,
        "results": results,
    }
    _write("p1_retrieval_benchmark.json", report)
    return report


def _table_truth(chunks: dict[str, Any], source: str, metric: str, period: str) -> list[str]:
    aliases = TABLE_ALIASES[metric]
    period_tokens = (period, period.replace(" ", "-"), period.replace(" ", "_"))
    truth: list[str] = []
    for chunk_id, content, metadata in zip(chunks["ids"], chunks["documents"], chunks["metadatas"], strict=True):
        if metadata.get("source") != source:
            continue
        lowered = content.casefold()
        has_metric = any(alias.casefold() in lowered for alias in aliases)
        has_period = any(token.casefold() in lowered for token in period_tokens) or period.replace(" ", "_") == str(
            metadata.get("quarter", "")
        )
        if has_metric and has_period:
            truth.append(chunk_id)
    return truth


def table_benchmark() -> dict[str, Any]:
    store, executor, _ = _build_retrieval_fixture()
    chunks = _load_json(FINAL_ROOT / "reference_chunks.json")
    results: list[dict[str, Any]] = []
    for company, source, period, metrics in TABLE_SPECS:
        for metric in metrics:
            expected = _table_truth(chunks, source, metric, period)
            if not expected:
                continue
            evidence = executor.execute(
                store=store, query=f"{company} {period} {metric}", tenant_id=0, company=company, top_k=12
            )
            retrieved = [item.metadata.get("chunk_id") for item in evidence]
            hit = bool(set(retrieved) & set(expected))
            results.append(
                {
                    "id": f"{company}-{period}-{metric}",
                    "company": company,
                    "period": period,
                    "metric": metric,
                    "expected_chunk_ids": expected,
                    "retrieved_chunk_ids": retrieved,
                    "status": "PASS" if hit else "FAIL",
                }
            )
    summary = {
        "total_cases": len(results),
        "passed_cases": sum(row["status"] == "PASS" for row in results),
        "failed_cases": sum(row["status"] == "FAIL" for row in results),
    }
    summary["threshold_passed"] = summary["total_cases"] >= 20 and summary["failed_cases"] == 0
    report = {
        "execution_mode": "offline_seeded_table_retrieval",
        "provider_calls": 0,
        "summary": summary,
        "results": results,
    }
    _write("p1_table_retrieval.json", report)
    return report


def _numeric_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _NUMBER.findall(text):
        normalized = token.replace(",", "").replace("$", "").casefold()
        try:
            numeric_value = float(normalized.rstrip("%"))
        except ValueError:
            continue
        # Years and Markdown/citation list labels are not financial claims.
        if 1900 <= numeric_value <= 2100:
            continue
        if numeric_value < 10 and not any(marker in token for marker in (".", ",", "$", "%")):
            continue
        tokens.add(normalized)
    return tokens


def citation_gate() -> dict[str, Any]:
    chunks = _load_json(FINAL_ROOT / "reference_chunks.json")
    chunk_map = {
        cid: (text, metadata)
        for cid, text, metadata in zip(chunks["ids"], chunks["documents"], chunks["metadatas"], strict=True)
    }
    dataset = {row["id"]: row for row in _load_json(FINAL_ROOT / "dataset.json")}
    rows: list[dict[str, Any]] = []
    for raw in _load_jsonl(FINAL_ROOT / "evaluation_100_results.jsonl"):
        case = dataset[raw["id"]]
        expected_companies = set(case.get("company", []))
        expected_sources = set(case.get("expected_sources", []))
        citations = raw.get("citations", [])
        valid = []
        period_ok = True
        metric_ok = True
        company_ok = True
        for citation in citations:
            chunk_id = citation.get("chunk_id")
            chunk = chunk_map.get(chunk_id)
            source_ok = bool(
                chunk
                and citation.get("source") == chunk[1].get("source")
                and citation.get("source") in expected_sources
            )
            page_ok = bool(chunk and str(citation.get("page")) == str(chunk[1].get("page")))
            valid.append(source_ok and page_ok)
            if expected_companies and chunk and chunk[1].get("company") not in expected_companies:
                company_ok = False
            if expected_companies and not chunk:
                company_ok = False
            filters = query_filters(case["question"])
            if chunk and "period" in filters and not matches_filter(chunk[0], chunk[1], "period", filters["period"]):
                period_ok = False
            if chunk and "metric" in filters and not matches_filter(chunk[0], chunk[1], "metric", filters["metric"]):
                metric_ok = False
        if not expected_sources:
            company_ok = not citations
            period_ok = not citations
            metric_ok = not citations
        answer_numbers = _numeric_tokens(_main_answer(raw.get("actual_answer", "")))
        cited_text = " ".join(chunk_map[c["chunk_id"]][0] for c in citations if c.get("chunk_id") in chunk_map)
        numeric_ok = not answer_numbers or answer_numbers.issubset(_numeric_tokens(cited_text))
        rows.append(
            {
                "id": raw["id"],
                "numeric": numeric_ok,
                "period": period_ok,
                "metric": metric_ok,
                "company": company_ok,
                "valid_citations": sum(valid),
                "citations": len(citations),
            }
        )
    summary = {"total_cases": len(rows)}
    for key in ("numeric", "period", "metric", "company"):
        summary[f"{key}_passed"] = sum(row[key] for row in rows)
        summary[f"{key}_rate"] = round(100 * summary[f"{key}_passed"] / len(rows), 1)
    summary["all_passed"] = all(
        summary[f"{key}_passed"] == len(rows) for key in ("numeric", "period", "metric", "company")
    )
    report = {
        "execution_mode": "offline_deterministic_citation_validation",
        "provider_calls": 0,
        "summary": summary,
        "results": rows,
    }
    _write("p1_citation_gate.json", report)
    return report


def focused_cases(diff: dict[str, Any]) -> dict[str, Any]:
    current = {row["id"]: row for row in _load_json(FINAL_ROOT / "dataset.json")}
    ids = {row["id"] for row in diff["regressions"]}
    ids.update({"EN-007", "ZH-034", "ZH-044", "ZH-045", "ZH-046", "ZH-047", "ZH-048", "ZH-049"})
    ids.update(
        case_id
        for case_id, case in current.items()
        if case.get("expected_sources")
        and "Tesla" in " ".join(case.get("company", []))
        and any(token in case["question"] for token in ("Q2", "2025", "第二季度", "2025"))
    )
    selected = sorted(ids)
    report = {
        "execution_mode": "offline_focused_regression_inventory",
        "provider_calls": 0,
        "case_count": len(selected),
        "case_ids": selected,
        "source": "frozen P1.1 answers plus deterministic planning/retrieval/citation reports",
    }
    _write("p1_focused_cases.json", report)
    return report


def run_all() -> dict[str, Any]:
    diff = failure_diff()
    retrieval = retrieval_benchmark()
    table = table_benchmark()
    citation = citation_gate()
    focused = focused_cases(diff)
    planning_path = RESULTS_ROOT / "p1_offline_planning_baseline.json"
    planning = _load_json(planning_path) if planning_path.exists() else {}
    summary = {
        "provider_calls": 0,
        "deepseek_api_used": "NO",
        "planning_gate": planning.get("summary", {}),
        "retrieval_gate": retrieval["summary"],
        "table_gate": table["summary"],
        "citation_gate": citation["summary"],
        "focused_cases": focused["case_count"],
        "ready_for_real_api_smoke": bool(
            planning.get("summary", {}).get("threshold_passed")
            and retrieval["summary"]["threshold_passed"]
            and table["summary"]["threshold_passed"]
            and citation["summary"]["all_passed"]
        ),
    }
    _write("p1_offline_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="run every provider-free P1 analysis")
    args = parser.parse_args()
    if not args.all:
        parser.error("use --all")
    summary = run_all()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ready_for_real_api_smoke"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
