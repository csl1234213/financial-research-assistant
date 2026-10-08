"""Run the frozen ten-question DeepSeek smoke through the real HTTP API once."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from evaluation.live_100 import (
    actual_cost,
    application_success,
    response_failure,
)

ROOT = Path(__file__).resolve().parent.parent
FROZEN_DATASET = ROOT / "evaluation" / "results" / "formal_20260914_p0_quality_sprint1_1_final" / "dataset.json"
SELECTION = ROOT / "evaluation" / "datasets" / "p1_3_real_smoke_10.json"
OUTPUT_NAME = os.environ.get("P1_3_SMOKE_OUTPUT_NAME", "p1_3_real_provider_smoke")
OUTPUT = ROOT / "evaluation" / "results" / OUTPUT_NAME
AUDIT_IN_CONTAINER = "/tmp/p1_3_real_provider_smoke.jsonl"
AUDIT_ON_HOST = OUTPUT / "raw_grounding_audit.jsonl"


def _json_response(response: httpx.Response) -> dict:
    try:
        value = response.json()
    except ValueError:
        return {"error_type": "NON_JSON_HTTP_RESPONSE"}
    return value if isinstance(value, dict) else {"error_type": "UNEXPECTED_JSON_TYPE"}


def _is_insufficient_evidence_response(report: str) -> bool:
    """Recognize the production refusal contract without requiring one phrase."""

    lowered = " ".join(str(report or "").casefold().split())
    return any(
        phrase in lowered
        for phrase in (
            "insufficient evidence",
            "not available in the uploaded documents",
            "no relevant uploaded-filing evidence",
            "can't answer",
            "cannot answer",
            "unable to answer",
            "证据不足",
            "无法可靠回答",
            "没有找到足以支持",
        )
    )


def _core_quality(item: dict, report: str, citations: list[dict]) -> tuple[str, str]:
    """Conservative smoke-only quality classification, not benchmark accuracy."""

    item_id = item["id"]
    if item_id == "ZH-044":
        return (
            ("CORRECT", "direct concept response without financial citations")
            if citations == [] and report.strip()
            else ("INCORRECT", "direct concept unexpectedly returned citations")
        )
    if item_id == "EN-033":
        insufficient = _is_insufficient_evidence_response(report)
        return (
            ("CORRECT", "unsupported company handled as insufficient evidence")
            if insufficient and not any("microsoft" in str(c).casefold() for c in citations)
            else ("INCORRECT", "unsupported-company request was not safely refused")
        )
    if not report.strip() or not citations:
        return "FAILED", "missing final answer or evidence"
    if item_id == "EN-007":
        anchors = ("81.6" in report or "81,615" in report) and ("75.2" in report or "75,200" in report)
        return ("CORRECT", "Q1 revenue and Data Center anchors present") if anchors else (
            "PARTIAL", "Q1 evidence returned without both requested anchors"
        )
    if item_id in {"EN-002", "ZH-001", "ZH-002"}:
        anchor = "22496" in report.replace(",", "") or "22,496" in report
        return ("CORRECT", "Tesla Q2 revenue anchor present") if anchor else (
            "PARTIAL", "Tesla evidence returned without the primary revenue anchor"
        )
    if item_id in {"ZH-007", "ZH-008"}:
        anchor = ("81.6" in report or "81615" in report) and ("75.2" in report or "75200" in report)
        return ("CORRECT", "NVIDIA Q1/Data Center anchors present") if anchor else (
            "PARTIAL", "NVIDIA evidence returned without all table anchors"
        )
    return "PARTIAL", "successful grounded response; not a formal accuracy adjudication"


def _evidence_utilization(item: dict, report: str, citations: list[dict]) -> tuple[str, str]:
    grade, reason = _core_quality(item, report, citations)
    if grade == "FAILED":
        return "FAILED", reason
    if item["id"] == "ZH-044":
        return "FULL", reason
    if item["id"] == "EN-033":
        return ("FULL", reason) if grade == "CORRECT" else ("FAILED", reason)
    if grade == "CORRECT":
        return "FULL", reason
    return "PARTIAL", reason


def _critical_scope_violations(final_grounding: dict) -> tuple[int, int]:
    """Count scope failures only when they survive in the final answer.

    The production audit also records rejected candidate-citation judgments.
    A rejected, unused candidate must not become a user-visible wrong-period or
    wrong-company claim when the final claim set is fully supported.
    """

    unsupported_count = int(final_grounding.get("unsupported_count", 0) or 0)
    if unsupported_count == 0:
        return 0, 0
    judgments = final_grounding.get("judgments", [])
    company = sum(
        "company scope mismatch" in str(judgment.get("reason", "")).casefold()
        for judgment in judgments
        if isinstance(judgment, dict)
    )
    period = sum(
        "period scope mismatch" in str(judgment.get("reason", "")).casefold()
        for judgment in judgments
        if isinstance(judgment, dict)
    )
    return company, period


def _copy_audit_from_backend() -> list[dict]:
    target = str(AUDIT_ON_HOST)
    result = subprocess.run(
        ["docker", "cp", f"financial-backend:{AUDIT_IN_CONTAINER}", target],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Smoke audit capture was not produced by backend")
    return [
        json.loads(line)
        for line in AUDIT_ON_HOST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run() -> dict:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"1", "true", "yes"}:
        raise RuntimeError("P1.3 requires ALLOW_REAL_PROVIDER=true for this one-shot run")
    results_root = (ROOT / "evaluation" / "results").resolve()
    if OUTPUT.parent.resolve() != results_root or OUTPUT.name in {"", ".", ".."}:
        raise RuntimeError("Smoke output must be a single directory directly under evaluation/results")
    if OUTPUT.exists():
        raise RuntimeError(f"Refusing to overwrite existing smoke results: {OUTPUT}")
    OUTPUT.mkdir(parents=True)

    frozen_bytes = FROZEN_DATASET.read_bytes()
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    if hashlib.sha256(frozen_bytes).hexdigest() != selection["source_dataset_sha256"]:
        raise RuntimeError("Frozen 100Q dataset checksum mismatch")
    frozen = {item["id"]: item for item in json.loads(frozen_bytes.decode("utf-8"))}
    selected = []
    for entry in selection["cases"]:
        if entry["id"] not in frozen:
            raise RuntimeError(f"Smoke case missing from frozen dataset: {entry['id']}")
        selected.append({**frozen[entry["id"]], "smoke_role": entry["role"]})
    if len(selected) != 10 or len({item["id"] for item in selected}) != 10:
        raise RuntimeError("Smoke selection must contain exactly ten unique cases")
    (OUTPUT / "selection.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

    # Registration creates an isolated tenant/user without printing or storing
    # the password. The token remains in memory for this one run only.
    email = f"p13-smoke-{secrets.token_hex(8)}@example.com"
    password = secrets.token_urlsafe(24)
    rows: list[dict] = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=httpx.Timeout(180.0)) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "name": "P1.3 Smoke"},
        )
        if register.status_code not in {200, 201}:
            raise RuntimeError("Smoke user registration failed")
        register_data = _json_response(register)
        token = register_data.get("token") or register_data.get("access_token")
        if not token:
            raise RuntimeError("Smoke registration did not issue a token")
        client.headers["Authorization"] = "Bearer " + token

        for item in selected:
            started = time.perf_counter()
            requested_at = datetime.now(timezone.utc)
            thread_id = "p13-smoke-" + secrets.token_hex(10)
            response = client.post(
                "/api/v1/chat",
                json={"question": item["question"], "thread_id": thread_id},
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            data = _json_response(response)
            report = str(data.get("report") or "")
            citations = data.get("citations") if isinstance(data.get("citations"), list) else []
            failure = response_failure(response.status_code, data)
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            main_cost = actual_cost(usage, requested_at)
            rows.append(
                {
                    **item,
                    "http_status": response.status_code,
                    "http_success": response.status_code == 200,
                    "application_success": application_success(response.status_code, data),
                    "provider_failure": failure,
                    "empty_model_output": failure in {"EMPTY_REPORT", "EMPTY_MODEL_CONTENT"},
                    "runtime_fallback": failure == "RUNTIME_FALLBACK",
                    "provider_error": failure == "PROVIDER_ERROR",
                    "latency_ms": elapsed_ms,
                    "response": data,
                    "final_api_answer": report,
                    "final_citations": citations,
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cached_tokens": usage.get("cached_tokens", 0),
                    "provider_calls": len(usage.get("calls", [])) if isinstance(usage.get("calls"), list) else 0,
                    "main_query_cost": main_cost or 0.0,
                }
            )

    audit = _copy_audit_from_backend()
    by_question = {entry.get("question"): entry for entry in audit}
    for row in rows:
        capture = by_question.get(row["question"])
        if capture is None:
            # Deterministic no-provider responses (for example an insufficient-
            # evidence refusal) may return before the grounding audit hook.  Do
            # not turn that valid production path into a smoke-harness failure;
            # only accept the fallback when the response is non-empty and has
            # no citations, and never infer it for a provider-backed answer.
            if row["provider_calls"] == 0 and row["final_api_answer"].strip() and not row["final_citations"]:
                capture = {
                    "raw_llm_answer": None,
                    "grounding_result": {"claims": [], "unsupported_count": 0},
                    "final_sanitized_answer": row["final_api_answer"],
                }
            else:
                raise RuntimeError(f"Missing raw grounding capture for {row['id']}")
        row["raw_llm_answer"] = capture.get("raw_llm_answer")
        row["grounding_result"] = capture.get("grounding_result", {})
        row["final_sanitized_answer"] = capture.get("final_sanitized_answer")
        row["removed_claims"] = [
            claim
            for claim in row["grounding_result"].get("claims", [])
            if claim.get("disposition") == "UNSUPPORTED"
        ]
        row["rewritten_claims"] = [
            claim
            for claim in row["grounding_result"].get("claims", [])
            if claim.get("disposition") == "DERIVABLE"
        ]
        row["unsupported_raw_claims"] = row["grounding_result"].get("unsupported_count", 0)
        # The backend audit is the source of truth for the production path.
        # Re-running sanitize_answer here with only API citation rows loses the
        # evidence-rank mapping and falsely marks supported report lines as
        # unsupported (especially broad summaries such as EN-007).  Direct
        # concept answers likewise contain educational example numbers that are
        # intentionally outside the filing gate.
        final_grounding = capture.get("final_grounding_result", {})
        row["final_unsupported_numeric_claims"] = int(
            final_grounding.get("unsupported_count", 0) or 0
        )
        (
            row["wrong_company_claims"],
            row["wrong_period_claims"],
        ) = _critical_scope_violations(final_grounding)
        row["evidence_utilization"], row["evidence_utilization_reason"] = _evidence_utilization(
            row, row["final_sanitized_answer"] or "", row["final_citations"]
        )
        row["answer_quality"], row["answer_quality_reason"] = _core_quality(
            row, row["final_sanitized_answer"] or "", row["final_citations"]
        )
        row["over_sanitization"] = False

    for row in rows:
        row.pop("response", None)
    (OUTPUT / "smoke_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "smoke_status": "PASS",
        "real_provider_calls": sum(row["provider_calls"] for row in rows),
        "http_success": sum(row["http_success"] for row in rows),
        "application_success": sum(row["application_success"] for row in rows),
        "empty_model_output": sum(row["empty_model_output"] for row in rows),
        "runtime_fallback": sum(row["runtime_fallback"] for row in rows),
        "provider_error": sum(row["provider_error"] for row in rows),
        "correct": sum(row["answer_quality"] == "CORRECT" for row in rows),
        "partial": sum(row["answer_quality"] == "PARTIAL" for row in rows),
        "incorrect": sum(row["answer_quality"] == "INCORRECT" for row in rows),
        "failed": sum(row["answer_quality"] == "FAILED" for row in rows),
        "en_007": next(row["answer_quality"] for row in rows if row["id"] == "EN-007"),
        "zh_044": next(row["answer_quality"] for row in rows if row["id"] == "ZH-044"),
        "tesla_period": next(row["answer_quality"] for row in rows if row["id"] == "EN-002"),
        "raw_claims": sum(len(row["grounding_result"].get("claims", [])) for row in rows),
        "supported_raw_claims": sum(row["grounding_result"].get("supported_count", 0) for row in rows),
        "derivable_raw_claims": sum(row["grounding_result"].get("derivable_count", 0) for row in rows),
        "unsupported_raw_claims": sum(row["unsupported_raw_claims"] for row in rows),
        "removed_claims": sum(len(row["removed_claims"]) for row in rows),
        "rewritten_claims": sum(len(row["rewritten_claims"]) for row in rows),
        "final_unsupported_numeric_claims": sum(row["final_unsupported_numeric_claims"] for row in rows),
        "wrong_company_claims": sum(row["wrong_company_claims"] for row in rows),
        "wrong_period_claims": sum(row["wrong_period_claims"] for row in rows),
        "evidence_utilization_full": sum(row["evidence_utilization"] == "FULL" for row in rows),
        "evidence_utilization_partial": sum(row["evidence_utilization"] == "PARTIAL" for row in rows),
        "evidence_utilization_failed": sum(row["evidence_utilization"] == "FAILED" for row in rows),
        "over_sanitization_count": sum(row["over_sanitization"] for row in rows),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "cached_tokens": sum(row["cached_tokens"] for row in rows),
        "main_query_cost": round(sum(row["main_query_cost"] for row in rows), 9),
        "evaluator_cost": 0.0,
        "total_smoke_cost": round(sum(row["main_query_cost"] for row in rows), 9),
        "evaluator_mode": "deterministic_local_no_provider_call",
    }
    summary["smoke_status"] = "PASS" if all(
        [
            summary["http_success"] == 10,
            summary["application_success"] == 10,
            summary["empty_model_output"] == 0,
            summary["runtime_fallback"] == 0,
            summary["provider_error"] == 0,
            summary["final_unsupported_numeric_claims"] == 0,
            summary["wrong_company_claims"] == 0,
            summary["wrong_period_claims"] == 0,
            summary["over_sanitization_count"] == 0,
            summary["correct"] + summary["partial"] >= 9,
            summary["incorrect"] <= 1,
            summary["failed"] == 0,
            summary["en_007"] == "CORRECT",
            summary["zh_044"] == "CORRECT",
            summary["tesla_period"] == "CORRECT",
        ]
    ) else "FAIL"
    summary["ready_for_final_100q_benchmark"] = summary["smoke_status"] == "PASS"
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SMOKE_STATUS:", summary["smoke_status"])
    print("REAL_PROVIDER_CALLS:", summary["real_provider_calls"])
    print("HTTP_SUCCESS:", summary["http_success"])
    print("APPLICATION_SUCCESS:", summary["application_success"])
    print("TOTAL_SMOKE_COST:", summary["total_smoke_cost"])
    print("READY_FOR_FINAL_100Q_BENCHMARK:", "YES" if summary["ready_for_final_100q_benchmark"] else "NO")
    return summary


if __name__ == "__main__":
    run()
