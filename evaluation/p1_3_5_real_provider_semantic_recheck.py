"""Run the frozen P1.3.5 five-question semantic recheck once.

This harness intentionally makes one application request per frozen question and
does not retry or replace a failed answer.  It is only enabled when the caller
explicitly sets ``ALLOW_REAL_PROVIDER=true``; the caller is responsible for
restoring the runtime guard after the process exits.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.reasoning_models import Evidence  # noqa: E402
from core.answer_grounding import sanitize_answer  # noqa: E402
from core.financial_grounding import extract_normalized_numbers  # noqa: E402
from evaluation.live_100 import actual_cost, application_success, response_failure  # noqa: E402

FROZEN_DATASET = ROOT / "evaluation" / "results" / "formal_20260914_p0_quality_sprint1_1_final" / "dataset.json"
SELECTION = ROOT / "evaluation" / "datasets" / "p1_3_5_semantic_recheck_5.json"
REFERENCE = ROOT / "evaluation" / "results" / "formal_20260914_p0_quality_sprint1_1_final" / "reference_chunks.json"
OUTPUT = ROOT / "evaluation" / "results" / "p1_3_5_real_provider_semantic_recheck"
AUDIT_IN_CONTAINER = "/tmp/p1_3_5_real_provider_semantic_recheck.jsonl"
AUDIT_ON_HOST = OUTPUT / "raw_grounding_audit.jsonl"
CASE_IDS = ("ZH-013", "EN-016", "EN-019", "ZH-019", "ZH-008")


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {"error_type": "NON_JSON_HTTP_RESPONSE"}
    return value if isinstance(value, dict) else {"error_type": "UNEXPECTED_JSON_TYPE"}


def _reference_lookup() -> dict[str, Evidence]:
    raw = json.loads(REFERENCE.read_text(encoding="utf-8"))
    return {
        chunk_id: Evidence(
            content=content,
            source=str(metadata.get("source", "")),
            company=str(metadata.get("company", "")),
            metadata={**metadata, "periods": str(metadata.get("quarter", "")), "chunk_id": chunk_id},
        )
        for chunk_id, content, metadata in zip(
            raw["ids"], raw["documents"], raw["metadatas"], strict=True
        )
    }


def _freeze_selection() -> list[dict[str, Any]]:
    source_bytes = FROZEN_DATASET.read_bytes()
    source = json.loads(source_bytes.decode("utf-8"))
    by_id = {item["id"]: item for item in source}
    if set(CASE_IDS) - set(by_id):
        raise RuntimeError("P1.3.5 frozen case is missing from the source benchmark")
    selected = [{**by_id[case_id], "semantic_recheck_role": case_id} for case_id in CASE_IDS]
    if SELECTION.exists():
        existing = json.loads(SELECTION.read_text(encoding="utf-8"))
        if existing.get("source_dataset_sha256") != hashlib.sha256(source_bytes).hexdigest():
            raise RuntimeError("P1.3.5 selection already exists with a different source checksum")
        if [item.get("id") for item in existing.get("cases", [])] != list(CASE_IDS):
            raise RuntimeError("P1.3.5 selection already exists with different frozen cases")
        return existing["cases"]
    SELECTION.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_dataset": str(FROZEN_DATASET.relative_to(ROOT)).replace("\\", "/"),
        "source_dataset_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "selection_frozen_before_requests": True,
        "cases": selected,
    }
    SELECTION.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return selected


def _copy_audit() -> list[dict[str, Any]]:
    result = subprocess.run(
        ["docker", "cp", f"financial-backend:{AUDIT_IN_CONTAINER}", str(AUDIT_ON_HOST)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not AUDIT_ON_HOST.exists():
        return []
    return [
        json.loads(line)
        for line in AUDIT_ON_HOST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _required_facts(case_id: str) -> list[dict[str, Any]]:
    facts: dict[str, list[dict[str, Any]]] = {
        "ZH-013": [
            {"name": "Apple Q2 period", "need": ["q2", "第二季度", "2026"]},
            {"name": "net sales", "need": ["111,184", "111184"]},
            {"name": "net income", "need": ["29,578", "29578"]},
            {"name": "six-month operating cash flow", "need": ["82,627", "82627"]},
        ],
        "EN-016": [
            {"name": "six-month operating cash flow", "need": ["82,627", "82627"]},
            {"name": "operating cash-flow label", "need": ["operating cash", "cash flow from operations"]},
            {"name": "Apple Q2 period", "need": ["q2", "2026"]},
        ],
        "EN-019": [
            {"name": "Tesla Q2 revenue", "need": ["22,496", "22496"]},
            {"name": "NVIDIA Q1 revenue", "need": ["81.6", "81,600", "81600"]},
            {"name": "Tesla evidence", "need": ["tesla"]},
            {"name": "NVIDIA evidence", "need": ["nvidia"]},
        ],
        "ZH-019": [
            {"name": "Tesla Q2 revenue", "need": ["22,496", "22496"]},
            {"name": "NVIDIA Q1 revenue", "need": ["81.6", "81,600", "81600"]},
            {"name": "Tesla evidence", "need": ["tesla", "特斯拉"]},
            {"name": "NVIDIA evidence", "need": ["nvidia", "英伟达"]},
        ],
        "ZH-008": [
            {"name": "NVIDIA Q1 period", "need": ["q1", "第一季度", "2027"]},
            {"name": "Data Center revenue", "need": ["75.2", "75,200", "75200", "数据中心"]},
            {"name": "NVIDIA company", "need": ["nvidia", "英伟达"]},
        ],
    }
    return facts[case_id]


def _contains_fact(text: str, alternatives: list[str]) -> bool:
    normalized = text.casefold().replace(",", "")
    if any(option.casefold().replace(",", "") in normalized for option in alternatives):
        return True

    # The production answer policy may render the same filing value in a
    # different financial scale (82.627 billion == 82,627 million).  Compare
    # numeric meaning rather than requiring one display spelling.  The
    # benchmark alternatives remain unchanged; the conversion is only an
    # evaluator-side equivalence check.
    answer_values = extract_normalized_numbers(text)
    for option in alternatives:
        expected_values = extract_normalized_numbers(option)
        for expected in expected_values:
            if expected.kind != "amount":
                continue
            candidates = {
                expected.value,
                expected.value * 1_000,
                expected.value * 1_000_000,
                expected.value * 1_000_000_000,
            }
            for actual in answer_values:
                if actual.kind == "amount" and actual.value in candidates:
                    return True
    return False


def _source_names(citations: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("source", "")) for item in citations if isinstance(item, dict)}


def _build_evidence(entries: list[dict[str, Any]], lookup: dict[str, Evidence]) -> list[dict[str, Any]]:
    output = []
    for entry in entries:
        chunk_id = entry.get("chunk_id")
        evidence = lookup.get(chunk_id)
        output.append({**entry, "content": evidence.content if evidence else None})
    return output


def _grade_case(
    case: dict[str, Any], report: str, citations: list[dict[str, Any]], lookup: dict[str, Evidence]
) -> dict[str, Any]:
    case_id = case["id"]
    lowered = report.casefold()
    required = _required_facts(case_id)
    missing = [fact["name"] for fact in required if not _contains_fact(lowered, fact["need"])]
    expected_sources = set(case.get("expected_sources", []))
    actual_sources = _source_names(citations)
    unexpected_sources = sorted(actual_sources - expected_sources)
    evidence = [
        lookup[item["chunk_id"]]
        for item in citations
        if isinstance(item, dict) and item.get("chunk_id") in lookup
    ]
    post = sanitize_answer(case["question"], report, evidence)
    wrong_period = 0
    if case_id in {"EN-016", "ZH-013"} and not _contains_fact(lowered, ["q2", "第二季度"]):
        wrong_period = 1
    if case_id in {"EN-019", "ZH-019"}:
        if _contains_fact(lowered, ["22,496", "22496"]) and not _contains_fact(lowered, ["q2", "q2-2025", "第二季度"]):
            wrong_period = 1
        if _contains_fact(lowered, ["81.6", "81,600", "81600"]) and not _contains_fact(
            lowered, ["q1", "q1 fy2027", "第一季度"]
        ):
            wrong_period = 1
    if case_id == "ZH-008" and not _contains_fact(lowered, ["q1", "第一季度"]):
        wrong_period = 1
    coverage = "FULL" if not missing else ("PARTIAL" if report.strip() else "FAILED")
    quality = (
        "CORRECT"
        if coverage == "FULL" and not unexpected_sources and wrong_period == 0
        else ("FAILED" if not report.strip() else "PARTIAL")
    )
    context_text = "\n".join(e.content for e in evidence)
    context_has_required = not [fact["name"] for fact in required if not _contains_fact(context_text, fact["need"])]
    over_sanitization = bool(context_has_required and missing)
    return {
        "required_facts": required,
        "preserved_required_facts": [fact["name"] for fact in required if fact["name"] not in missing],
        "missing_required_facts": missing,
        "required_fact_coverage": coverage,
        "answer_quality": quality,
        "wrong_company": int(bool(unexpected_sources)),
        "wrong_period": wrong_period,
        "unsupported_numeric": post.unsupported_count,
        "over_sanitization": over_sanitization,
        "evidence_utilization": "FULL" if coverage == "FULL" else ("PARTIAL" if report.strip() else "FAILED"),
        "evidence_context_has_required_facts": context_has_required,
        "unexpected_citation_sources": unexpected_sources,
    }


def run() -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"1", "true", "yes"}:
        raise RuntimeError("P1.3.5 requires ALLOW_REAL_PROVIDER=true for this one-shot run")
    if OUTPUT.exists():
        raise RuntimeError(f"Refusing to overwrite existing P1.3.5 results: {OUTPUT}")
    selected = _freeze_selection()
    OUTPUT.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    email = f"p135-smoke-{secrets.token_hex(8)}@example.com"
    password = secrets.token_urlsafe(24)
    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0),
    ) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "name": "P1.3.5 Smoke"},
        )
        if register.status_code not in {200, 201}:
            raise RuntimeError("P1.3.5 smoke user registration failed")
        token_data = _json_response(register)
        token = token_data.get("token") or token_data.get("access_token")
        if not token:
            raise RuntimeError("P1.3.5 registration did not issue a token")
        client.headers["Authorization"] = "Bearer " + str(token)
        for case in selected:
            started = time.perf_counter()
            requested_at = datetime.now(timezone.utc)
            response_error = ""
            try:
                response = client.post(
                    "/api/v1/chat",
                    json={"question": case["question"], "thread_id": "p135-smoke-" + secrets.token_hex(10)},
                )
                data = _json_response(response)
                status = response.status_code
            except Exception as exc:  # one request failed; do not retry or continue
                response = None
                data = {"error_type": type(exc).__name__}
                status = 599
                response_error = type(exc).__name__
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            report = str(data.get("report") or "")
            citations = data.get("citations") if isinstance(data.get("citations"), list) else []
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            failure = response_failure(status, data)
            row = {
                **case,
                "http_status": status,
                "http_success": status == 200,
                "application_success": application_success(status, data),
                "provider_failure": failure,
                "response_error": response_error,
                "empty_output": failure in {"EMPTY_REPORT", "EMPTY_MODEL_CONTENT"},
                "runtime_fallback": failure == "RUNTIME_FALLBACK",
                "provider_error": failure == "PROVIDER_ERROR",
                "total_latency_ms": elapsed_ms,
                "routing_latency": "NOT_OBSERVABLE",
                "planning_latency": "NOT_OBSERVABLE",
                "retrieval_latency": "NOT_OBSERVABLE",
                "rerank_latency": "NOT_OBSERVABLE",
                "context_latency": "NOT_OBSERVABLE",
                "provider_latency": "NOT_OBSERVABLE",
                "grounding_latency": "NOT_OBSERVABLE",
                "sanitizer_latency": "NOT_OBSERVABLE",
                "final_answer": report,
                "final_citations": citations,
                "input_tokens": usage.get("input_tokens", "UNKNOWN"),
                "output_tokens": usage.get("output_tokens", "UNKNOWN"),
                "cached_tokens": usage.get("cached_tokens", "UNKNOWN"),
                "provider_calls": len(usage.get("calls", [])) if isinstance(usage.get("calls"), list) else "UNKNOWN",
                "main_query_cost": actual_cost(usage, requested_at) or "UNKNOWN",
                "evaluator_calls": 0,
                "evaluator_cost": "$0",
            }
            rows.append(row)
            if not row["http_success"] or not row["application_success"] or failure is not None:
                break
    audit = _copy_audit()
    by_question = {entry.get("question"): entry for entry in audit}
    lookup = _reference_lookup()
    for row in rows:
        capture = by_question.get(row["question"], {})
        grounding = capture.get("grounding_result", {})
        raw_answer = capture.get("raw_llm_answer")
        final_answer = capture.get("final_sanitized_answer") or row["final_answer"]
        claims = grounding.get("claims", []) if isinstance(grounding, dict) else []
        row.update(
            {
                "raw_llm_answer": raw_answer,
                "final_sanitized_answer": final_answer,
                "retrieved_evidence": _build_evidence(capture.get("retrieved_evidence", []), lookup),
                "final_context": _build_evidence(capture.get("final_evidence", []), lookup),
                "raw_citations": row["final_citations"],
                "supported_claims": [claim for claim in claims if claim.get("disposition") == "SUPPORTED"],
                "derivable_claims": [claim for claim in claims if claim.get("disposition") == "DERIVABLE"],
                "uncertain_claims": [claim for claim in claims if claim.get("disposition") == "UNCERTAIN"],
                "unsupported_claims": [claim for claim in claims if claim.get("disposition") == "UNSUPPORTED"],
                "removed_claims": [claim for claim in claims if claim.get("disposition") == "UNSUPPORTED"],
                "rewritten_claims": [claim for claim in claims if claim.get("disposition") == "DERIVABLE"],
            }
        )
        # Grade the user-visible sanitized answer and its final evidence.  The
        # API report also contains an audit appendix (source coverage and
        # diagnostics); scoring that wrapper creates false unsupported claims
        # and false source mismatches.
        final_citations = [
            {
                "rank": index,
                "source": item.get("source", ""),
                "chunk_id": item.get("chunk_id") or item.get("metadata", {}).get("chunk_id", ""),
            }
            for index, item in enumerate(capture.get("final_evidence", []), 1)
            if isinstance(item, dict)
        ] or row["final_citations"]
        row.update(_grade_case(row, final_answer or "", final_citations, lookup))
    summary = {
        "semantic_recheck_status": "FAIL",
        "real_provider_calls": sum(row["provider_calls"] for row in rows if isinstance(row["provider_calls"], int)),
        "http_success": sum(row["http_success"] for row in rows),
        "application_success": sum(row["application_success"] for row in rows),
        "correct": sum(row.get("answer_quality") == "CORRECT" for row in rows),
        "partial": sum(row.get("answer_quality") == "PARTIAL" for row in rows),
        "incorrect": sum(row.get("answer_quality") == "INCORRECT" for row in rows),
        "failed": sum(row.get("answer_quality") == "FAILED" for row in rows),
        "required_fact_full": sum(row.get("required_fact_coverage") == "FULL" for row in rows),
        "required_fact_partial": sum(row.get("required_fact_coverage") == "PARTIAL" for row in rows),
        "required_fact_failed": sum(row.get("required_fact_coverage") == "FAILED" for row in rows),
        "evidence_utilization_full": sum(row.get("evidence_utilization") == "FULL" for row in rows),
        "evidence_utilization_partial": sum(row.get("evidence_utilization") == "PARTIAL" for row in rows),
        "evidence_utilization_failed": sum(row.get("evidence_utilization") == "FAILED" for row in rows),
        "wrong_company": sum(row.get("wrong_company", 0) for row in rows),
        "wrong_period": sum(row.get("wrong_period", 0) for row in rows),
        "unsupported_numeric": sum(row.get("unsupported_numeric", 0) for row in rows),
        "over_sanitization": sum(bool(row.get("over_sanitization")) for row in rows),
        "empty_output": sum(row.get("empty_output", False) for row in rows),
        "runtime_fallback": sum(row.get("runtime_fallback", False) for row in rows),
        "provider_error": sum(row.get("provider_error", False) for row in rows),
        "input_tokens": sum(row["input_tokens"] for row in rows if isinstance(row["input_tokens"], int)),
        "output_tokens": sum(row["output_tokens"] for row in rows if isinstance(row["output_tokens"], int)),
        "cached_tokens": sum(row["cached_tokens"] for row in rows if isinstance(row["cached_tokens"], int)),
        "main_query_cost": (
            "UNKNOWN"
            if any(row["main_query_cost"] == "UNKNOWN" for row in rows)
            else round(sum(row["main_query_cost"] for row in rows), 9)
        ),
        "evaluator_calls": 0,
        "evaluator_cost": "$0",
        "latency_p50_ms": None,
        "latency_max_ms": max((row["total_latency_ms"] for row in rows), default=None),
        "allow_real_provider_restored": False,
        "cases_completed": len(rows),
        "cases_expected": len(CASE_IDS),
    }
    latencies = sorted(row["total_latency_ms"] for row in rows)
    if latencies:
        summary["latency_p50_ms"] = latencies[(len(latencies) - 1) // 2]
    summary["semantic_recheck_status"] = "PASS" if all(
        [
            summary["http_success"] == 5,
            summary["application_success"] == 5,
            summary["correct"] == 5,
            summary["required_fact_full"] == 5,
            summary["evidence_utilization_full"] == 5,
            summary["wrong_company"] == 0,
            summary["wrong_period"] == 0,
            summary["unsupported_numeric"] == 0,
            summary["over_sanitization"] == 0,
            summary["empty_output"] == 0,
            summary["runtime_fallback"] == 0,
            summary["provider_error"] == 0,
        ]
    ) else "FAIL"
    for row in rows:
        (OUTPUT / f"{row['id']}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("SEMANTIC_RECHECK_STATUS:", summary["semantic_recheck_status"])
    print("REAL_PROVIDER_CALLS:", summary["real_provider_calls"])
    print("HTTP_SUCCESS:", f"{summary['http_success']}/5")
    print("APPLICATION_SUCCESS:", f"{summary['application_success']}/5")
    print("CORRECT:", f"{summary['correct']}/5")
    print("REQUIRED_FACT_FULL:", f"{summary['required_fact_full']}/5")
    print("EVIDENCE_UTILIZATION_FULL:", f"{summary['evidence_utilization_full']}/5")
    print("READY_FOR_FINAL_10Q_RELEASE_SMOKE:", "YES" if summary["semantic_recheck_status"] == "PASS" else "NO")
    return summary


if __name__ == "__main__":
    run()
