"""Run exactly one current-production EN-007 Provider canary.

The caller must opt in with ``ALLOW_REAL_PROVIDER=true`` and configure the
backend audit path.  This harness makes one authenticated HTTP request, never
retries or replaces a failed result, and persists only non-secret diagnostics.
It is intentionally narrower than the ten-question/100-question benchmarks.
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
from evaluation.live_100 import actual_cost, application_success, response_failure  # noqa: E402

CASE_ID = "EN-007"
FROZEN_DATASET = (
    ROOT
    / "evaluation"
    / "results"
    / "formal_20260914_p0_quality_sprint1_1_final"
    / "dataset.json"
)
DEFAULT_OUTPUT_NAME = "p1_3_2_real_provider_canary_20260925"
OUTPUT = ROOT / "evaluation" / "results" / os.environ.get(
    "P1_3_2_CANARY_OUTPUT_NAME", DEFAULT_OUTPUT_NAME
)
AUDIT_PATH = os.environ.get("P1_3_SMOKE_AUDIT_PATH", "").strip()


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {"error_type": "NON_JSON_HTTP_RESPONSE"}
    return value if isinstance(value, dict) else {"error_type": "UNEXPECTED_JSON_TYPE"}


def _docker_exec_python(program: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "python", "-c", program, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )


def _audit_offset() -> int:
    if not AUDIT_PATH or not AUDIT_PATH.startswith("/") or ".." in Path(AUDIT_PATH).parts:
        raise RuntimeError("AUDIT_DISABLED_OR_INVALID")
    program = (
        "from pathlib import Path; import sys; "
        "p=Path(sys.argv[1]); print(p.stat().st_size if p.is_file() else 0)"
    )
    result = _docker_exec_python(program, AUDIT_PATH)
    if result.returncode != 0:
        raise RuntimeError("AUDIT_PREFLIGHT_FAILED")
    try:
        offset = int(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("AUDIT_PREFLIGHT_INVALID") from exc
    if offset < 0:
        raise RuntimeError("AUDIT_PREFLIGHT_INVALID")
    return offset


def _copy_audit(offset: int) -> list[dict[str, Any]]:
    program = (
        "from pathlib import Path; import sys; "
        "p=Path(sys.argv[1]); o=int(sys.argv[2]); "
        "data=p.read_bytes()[o:] if p.is_file() else b''; "
        "sys.stdout.buffer.write(data)"
    )
    result = _docker_exec_python(program, AUDIT_PATH, str(offset))
    if result.returncode != 0:
        raise RuntimeError("AUDIT_COPY_FAILED")
    return [
        json.loads(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def _load_case() -> dict[str, Any]:
    source = FROZEN_DATASET.read_bytes()
    rows = json.loads(source.decode("utf-8"))
    case = next((row for row in rows if row.get("id") == CASE_ID), None)
    if not isinstance(case, dict) or not case.get("question"):
        raise RuntimeError("FROZEN_EN_007_MISSING")
    return {
        "id": CASE_ID,
        "question": str(case["question"]),
        "source_dataset_sha256": hashlib.sha256(source).hexdigest(),
        "expected_sources": list(case.get("expected_sources") or []),
    }


def _evidence(entries: Any) -> list[Evidence]:
    if not isinstance(entries, list):
        return []
    result: list[Evidence] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        result.append(
            Evidence(
                content=content,
                source=str(entry.get("source") or metadata.get("source") or ""),
                company=str(entry.get("company") or metadata.get("company") or ""),
                metadata={**metadata, "chunk_id": entry.get("chunk_id") or metadata.get("chunk_id")},
            )
        )
    return result


def _claim_counts(capture: dict[str, Any]) -> dict[str, int]:
    grounding = capture.get("grounding_result")
    claims = grounding.get("claims", []) if isinstance(grounding, dict) else []
    if not isinstance(claims, list):
        claims = []
    return {
        "raw_claims": len(claims),
        "supported_claims": sum(item.get("disposition") == "SUPPORTED" for item in claims if isinstance(item, dict)),
        "derivable_claims": sum(item.get("disposition") == "DERIVABLE" for item in claims if isinstance(item, dict)),
        "unsupported_claims": sum(
            item.get("disposition") == "UNSUPPORTED"
            for item in claims
            if isinstance(item, dict)
        ),
        "removed_claims": sum(
            item.get("disposition") == "UNSUPPORTED"
            for item in claims
            if isinstance(item, dict)
        ),
        "rewritten_claims": sum(
            item.get("disposition") == "DERIVABLE"
            for item in claims
            if isinstance(item, dict)
        ),
    }


def run() -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"1", "true", "yes"}:
        raise RuntimeError("CANARY_REQUIRES_ALLOW_REAL_PROVIDER=true")
    if OUTPUT.exists():
        raise RuntimeError(f"CANARY_OUTPUT_EXISTS:{OUTPUT.name}")
    if OUTPUT.parent.resolve() != (ROOT / "evaluation" / "results").resolve():
        raise RuntimeError("CANARY_OUTPUT_PATH_INVALID")

    case = _load_case()
    offset = _audit_offset()
    OUTPUT.mkdir(parents=True)
    email = f"p132-canary-{secrets.token_hex(8)}@example.com"
    password = secrets.token_urlsafe(24)

    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0),
    ) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "name": "P1.3.2 Canary"},
        )
        if register.status_code not in {200, 201}:
            raise RuntimeError("CANARY_REGISTRATION_FAILED")
        registration = _json_response(register)
        token = registration.get("token") or registration.get("access_token")
        if not token:
            raise RuntimeError("CANARY_TOKEN_ISSUE_FAILED")
        client.headers["Authorization"] = "Bearer " + str(token)

        started = time.perf_counter()
        requested_at = datetime.now(timezone.utc)
        thread_id = "p132-canary-" + secrets.token_hex(10)
        try:
            response = client.post(
                "/api/v1/chat",
                json={"question": case["question"], "thread_id": thread_id},
            )
            data = _json_response(response)
            status = response.status_code
            response_error = ""
        except Exception as exc:  # one attempt; never retry
            data = {"error_type": type(exc).__name__}
            status = 599
            response_error = type(exc).__name__
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    audit_failure = None
    captures: list[dict[str, Any]] = []
    try:
        captures = _copy_audit(offset)
    except Exception as exc:  # preserve HTTP result while marking audit incomplete
        audit_failure = str(exc)
    capture = next((item for item in captures if item.get("question") == case["question"]), {})

    report = str(data.get("report") or "")
    citations = data.get("citations") if isinstance(data.get("citations"), list) else []
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    failure = response_failure(status, data)
    final_answer = str(capture.get("final_sanitized_answer") or report)
    final_evidence = _evidence(capture.get("final_evidence"))
    post = sanitize_answer(case["question"], final_answer, final_evidence) if final_answer else None
    normalized = final_answer.replace(",", "").casefold()
    anchors = ("81.6" in normalized or "81615" in normalized) and (
        "75.2" in normalized or "75200" in normalized
    )
    counts = _claim_counts(capture)
    row = {
        **case,
        "http_status": status,
        "application_success": application_success(status, data),
        "provider_failure": failure,
        "empty_output": failure in {"EMPTY_REPORT", "EMPTY_MODEL_CONTENT"},
        "runtime_fallback": failure == "RUNTIME_FALLBACK",
        "provider_error": failure == "PROVIDER_ERROR",
        "response_error": response_error,
        "total_latency_ms": elapsed_ms,
        "request_deadline_seconds": 120,
        "connect_timeout_seconds": 10,
        "read_timeout_seconds": 45,
        "routing": data.get("routing"),
        "raw_llm_answer": capture.get("raw_llm_answer"),
        "final_sanitized_answer": final_answer,
        "grounding_result": capture.get("grounding_result"),
        "final_grounding_result": capture.get("final_grounding_result"),
        "retrieved_evidence": capture.get("retrieved_evidence"),
        "final_evidence": capture.get("final_evidence"),
        "final_citations": citations,
        "removed_claims": [
            item for item in (capture.get("grounding_result") or {}).get("claims", [])
            if isinstance(item, dict) and item.get("disposition") == "UNSUPPORTED"
        ],
        "rewritten_claims": [
            item for item in (capture.get("grounding_result") or {}).get("claims", [])
            if isinstance(item, dict) and item.get("disposition") == "DERIVABLE"
        ],
        **counts,
        "final_unsupported_numeric_claims": post.unsupported_count if post else "UNKNOWN",
        "critical_wrong_company": 0 if post and post.unsupported_count == 0 else "NOT_EVALUATED",
        "critical_wrong_period": 0 if post and post.unsupported_count == 0 else "NOT_EVALUATED",
        "evidence_utilization": (
            "FULL" if anchors and final_answer.strip()
            else ("PARTIAL" if final_answer.strip() else "FAILED")
        ),
        "en_007_grade": (
            "CORRECT" if anchors and post and post.unsupported_count == 0
            else ("FAILED" if not final_answer.strip() else "PARTIAL")
        ),
        "input_tokens": usage.get("input_tokens", "UNKNOWN"),
        "output_tokens": usage.get("output_tokens", "UNKNOWN"),
        "cached_tokens": usage.get("cached_tokens", "UNKNOWN"),
        "provider_calls": len(usage.get("calls", [])) if isinstance(usage.get("calls"), list) else "UNKNOWN",
        "main_query_cost": actual_cost(usage, requested_at) or "UNKNOWN",
        "evaluator_calls": 0,
        "evaluator_cost": "$0",
        "audit_failure": audit_failure,
    }
    (OUTPUT / "EN-007.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "canary_status": "PASS" if all([
            row["http_status"] == 200,
            row["application_success"],
            not row["empty_output"],
            not row["runtime_fallback"],
            not row["provider_error"],
            row["en_007_grade"] == "CORRECT",
            row["critical_wrong_company"] == 0,
            row["critical_wrong_period"] == 0,
            row["final_unsupported_numeric_claims"] == 0,
            row["evidence_utilization"] == "FULL",
            row["audit_failure"] is None,
        ]) else "FAIL",
        "real_provider_calls": row["provider_calls"],
        "http_status": row["http_status"],
        "application_success": row["application_success"],
        "total_latency_ms": row["total_latency_ms"],
        "provider_failure": row["provider_failure"],
        "empty_output": row["empty_output"],
        "runtime_fallback": row["runtime_fallback"],
        "provider_error": row["provider_error"],
        "en_007_grade": row["en_007_grade"],
        "raw_claims": row["raw_claims"],
        "supported_claims": row["supported_claims"],
        "derivable_claims": row["derivable_claims"],
        "unsupported_claims": row["unsupported_claims"],
        "removed_claims": row["removed_claims"],
        "rewritten_claims": row["rewritten_claims"],
        "final_unsupported_numeric_claims": row["final_unsupported_numeric_claims"],
        "critical_wrong_company": row["critical_wrong_company"],
        "critical_wrong_period": row["critical_wrong_period"],
        "evidence_utilization": row["evidence_utilization"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "cached_tokens": row["cached_tokens"],
        "main_query_cost": row["main_query_cost"],
        "evaluator_calls": 0,
        "evaluator_cost": "$0",
        "audit_failure": row["audit_failure"],
        "allow_real_provider_restored": False,
        "ready_for_remaining_9q_smoke": False,
    }
    summary["ready_for_remaining_9q_smoke"] = summary["canary_status"] == "PASS"
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {
        k: v for k, v in summary.items()
        if k not in {"raw_answer", "final_answer"}
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run()
