"""Run the fixed P1.4.1 five-question provider recheck once.

This is deliberately a one-shot live harness: exactly one production HTTP
request per frozen question, no evaluator calls, and no retry/replace logic.
The caller enables the provider only for this process and must restore the
container guard immediately afterwards.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.reasoning_models import Evidence  # noqa: E402
from core.answer_grounding import sanitize_answer  # noqa: E402
from core.report_builder import build_research_report  # noqa: E402
from core.research_analyzer import analyze_evidence  # noqa: E402
from evaluation.live_100 import actual_cost, application_success, response_failure  # noqa: E402

SELECTION = ROOT / "evaluation" / "datasets" / "p1_3_5_semantic_recheck_5.json"
FROZEN_DATASET = ROOT / "evaluation" / "results" / "formal_20260914_p0_quality_sprint1_1_final" / "dataset.json"
OUTPUT_NAME = os.environ.get(
    "P1_4_RECHECK_OUTPUT_NAME", "p1_4_1_real_provider_fact_ledger_recheck"
)
OUTPUT = ROOT / "evaluation" / "results" / OUTPUT_NAME
CASE_IDS = ("ZH-013", "EN-016", "EN-019", "ZH-019", "ZH-008")
NOT_EVALUATED = "NOT_EVALUATED"


class AuditIntegrityError(RuntimeError):
    """A bounded diagnostic code, never raw Docker output or credentials."""


@dataclass(frozen=True)
class AuditCapture:
    container_id: str
    path: str
    offset: int


def _docker(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["docker", *args], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AuditIntegrityError("AUDIT_DOCKER_UNAVAILABLE") from None


def _preflight_audit() -> AuditCapture:
    """Resolve the production audit setting before any authentication/chat write.

    The byte offset excludes all earlier runs. Only the configured audit path
    and its size are returned from the container, never its environment.
    """
    result = _docker(["compose", "ps", "-q", "backend"])
    container = result.stdout.strip()
    if result.returncode or not container or any(c not in "0123456789abcdef" for c in container):
        raise AuditIntegrityError("AUDIT_BACKEND_NOT_FOUND")
    program = """import json, os
from pathlib import Path
target = os.environ.get('P1_3_SMOKE_AUDIT_PATH', '').strip()
if not target:
    print(json.dumps({'error': 'AUDIT_DISABLED'}))
else:
    path = Path(target)
    writable = (path.is_file() and os.access(path, os.W_OK)) if path.exists() else (
        path.parent.is_dir() and os.access(path.parent, os.W_OK))
    print(json.dumps({'path': target, 'offset': path.stat().st_size if path.is_file() else 0,
                      'writable': writable}))
"""
    inspected = _docker(["exec", container, "python", "-c", program])
    if inspected.returncode:
        raise AuditIntegrityError("AUDIT_PREFLIGHT_FAILED")
    try:
        state = json.loads(inspected.stdout)
        target = state.get("path", "")
        path = PurePosixPath(target)
        offset = state.get("offset")
    except (ValueError, TypeError, AttributeError):
        raise AuditIntegrityError("AUDIT_PREFLIGHT_INVALID") from None
    if state.get("error") == "AUDIT_DISABLED":
        raise AuditIntegrityError("AUDIT_DISABLED")
    if not path.is_absolute() or ".." in path.parts or path.suffix != ".jsonl" or "\n" in target:
        raise AuditIntegrityError("AUDIT_PATH_INVALID")
    expected = os.environ.get("P1_4_RECHECK_AUDIT_PATH")
    if expected and expected != target:
        raise AuditIntegrityError("AUDIT_PATH_MISMATCH")
    if not state.get("writable") or not isinstance(offset, int) or offset < 0:
        raise AuditIntegrityError("AUDIT_NOT_WRITABLE")
    return AuditCapture(container, target, offset)


def _write_json(path: Path, value: Any) -> None:
    # Every output is immutable within a run; interrupted artifacts are kept.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {"error_type": "NON_JSON_HTTP_RESPONSE"}
    return value if isinstance(value, dict) else {"error_type": "UNEXPECTED_JSON_TYPE"}


def _freeze_selection() -> list[dict[str, Any]]:
    source_bytes = FROZEN_DATASET.read_bytes()
    source = json.loads(source_bytes.decode("utf-8"))
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    selected = json.loads(SELECTION.read_text(encoding="utf-8"))
    if selected.get("source_dataset_sha256") != source_sha:
        raise RuntimeError("frozen selection checksum does not match source benchmark")
    cases = selected.get("cases", [])
    if [item.get("id") for item in cases] != list(CASE_IDS):
        raise RuntimeError("frozen selection does not contain the required five cases")
    by_id = {item.get("id"): item for item in source}
    for item in cases:
        source_item = by_id.get(item.get("id"))
        if not source_item or item.get("question") != source_item.get("question"):
            raise RuntimeError("frozen question differs from the source benchmark")
    return cases


def _copy_audit(capture: AuditCapture) -> list[dict[str, Any]]:
    program = """import sys
from pathlib import Path
path, offset = Path(sys.argv[1]), int(sys.argv[2])
if not path.is_file() or path.stat().st_size < offset:
    sys.exit(2)
with path.open('rb') as handle:
    handle.seek(offset)
    sys.stdout.buffer.write(handle.read())
"""
    result = _docker(["exec", capture.container_id, "python", "-c", program, capture.path, str(capture.offset)])
    if result.returncode or not result.stdout.strip():
        raise AuditIntegrityError("AUDIT_NOT_CAPTURED")
    # Preserve diagnostic bytes even if parsing or later validation fails.
    with (OUTPUT / "raw_grounding_audit.jsonl").open("x", encoding="utf-8") as handle:
        handle.write(result.stdout)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        entries = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except ValueError:
        raise AuditIntegrityError("AUDIT_INVALID_JSON") from None
    if not entries or any(not isinstance(entry, dict) for entry in entries):
        raise AuditIntegrityError("AUDIT_INVALID_RECORD")
    return entries


def _build_evidence(entries: Any) -> list[Evidence]:
    """Use captured live chunks; stale reference snapshots cannot fill gaps."""
    if not isinstance(entries, list) or not entries:
        raise AuditIntegrityError("AUDIT_EVIDENCE_MISSING")
    output: list[Evidence] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise AuditIntegrityError("AUDIT_EVIDENCE_INVALID")
        content, metadata = entry.get("content"), entry.get("metadata")
        if not isinstance(content, str) or not content.strip() or not isinstance(metadata, dict):
            raise AuditIntegrityError("AUDIT_EVIDENCE_INCOMPLETE")
        chunk_id = entry.get("chunk_id") or metadata.get("chunk_id")
        if not chunk_id:
            raise AuditIntegrityError("AUDIT_CHUNK_ID_MISSING")
        output.append(Evidence(
            content=content,
            source=str(entry.get("source") or metadata.get("source") or ""),
            company=str(entry.get("company") or metadata.get("company") or ""),
            metadata={**metadata, "chunk_id": chunk_id},
        ))
    return output


def _mark_not_evaluated(row: dict[str, Any], reason: str) -> None:
    row.update({
        "audit_integrity": "FAIL", "audit_failure": reason,
        "answer_grade": NOT_EVALUATED,
        "raw_llm_answer": None, "grounding_result": None,
        "final_sanitized_answer": None, "retrieved_evidence": None, "final_context": None,
        "raw_claims": None, "removed_claims": None, "rewritten_claims": None,
        "required_fact_coverage": NOT_EVALUATED, "missing_required_facts": None,
        "fact_ledger": _planning_ledger(row.get("planning")),
        "deterministic_completions": (row.get("planning") or {}).get("fact_ledger_added_ids", []),
        "evidence_utilization": NOT_EVALUATED,
        **{key: NOT_EVALUATED for key in (
            "grounding_supported_claims", "grounding_supported_claims_kept", "grounding_unsupported_claims",
            "grounding_unsupported_claims_rejected", "unsupported_numeric", "wrong_company", "wrong_period",
            "wrong_metric", "over_sanitization",
        )},
    })


def _evaluate_row(row: dict[str, Any], capture: dict[str, Any]) -> None:
    raw, final_answer = capture.get("raw_llm_answer"), capture.get("final_sanitized_answer")
    if not isinstance(raw, str) or not raw.strip():
        raise AuditIntegrityError("AUDIT_RAW_ANSWER_MISSING")
    if not isinstance(final_answer, str) or not final_answer.strip():
        raise AuditIntegrityError("AUDIT_FINAL_ANSWER_MISSING")
    if capture.get("final_api_report") != row["final_api_report"]:
        raise AuditIntegrityError("AUDIT_API_RESPONSE_MISMATCH")
    expected_report = build_research_report(
        row["question"], final_answer, row["final_citations"], analyze_evidence(row["final_citations"]),
    )
    if row["final_api_report"] != expected_report:
        raise AuditIntegrityError("AUDIT_UNGROUNDED_REPORT_CONTENT")
    grounding = capture.get("grounding_result")
    if not isinstance(grounding, dict) or not isinstance(grounding.get("claims"), list):
        raise AuditIntegrityError("AUDIT_GROUNDING_MISSING")
    claims = grounding["claims"]
    if any(
        not isinstance(claim, dict) or not isinstance(claim.get("text"), str)
        or claim.get("disposition") not in {"SUPPORTED", "DERIVABLE", "UNCERTAIN", "UNSUPPORTED", "NON_NUMERIC"}
        for claim in claims
    ):
        raise AuditIntegrityError("AUDIT_GROUNDING_INVALID")
    final_grounding = capture.get("final_grounding_result")
    if not isinstance(final_grounding, dict) or not isinstance(final_grounding.get("claims"), list):
        raise AuditIntegrityError("AUDIT_FINAL_GROUNDING_MISSING")
    retrieved = _build_evidence(capture.get("retrieved_evidence"))
    final_evidence = _build_evidence(capture.get("final_evidence"))
    by_id = {item.metadata["chunk_id"]: item for item in final_evidence}
    cited_evidence: list[Evidence] = []
    for citation in row["final_citations"]:
        item = by_id.get(citation.get("chunk_id"))
        if item is None or citation.get("source") != item.source:
            raise AuditIntegrityError("AUDIT_CITATION_EVIDENCE_MISSING")
        cited_evidence.append(item)
    if not cited_evidence:
        raise AuditIntegrityError("AUDIT_FINAL_CITATIONS_MISSING")
    post = sanitize_answer(row["question"], final_answer, cited_evidence)
    ledger = _planning_ledger(row.get("planning"))
    coverage, required, missing = _required_coverage(final_answer, row.get("planning"))
    unsupported = post.unsupported_count + post.uncertain_count
    # A complete successful company/period/metric-scoped replay proves zero
    # critical numeric claims. A rejection does not identify its dimension;
    # report that dimension as unmeasured instead of inventing zero counts.
    dimensions = 0 if unsupported == 0 else NOT_EVALUATED
    supported_raw = [claim for claim in claims if claim.get("disposition") == "SUPPORTED"]
    kept = sum(str(claim.get("text", "")).strip() in final_answer for claim in supported_raw)
    row.update({
        "audit_integrity": "PASS", "audit_failure": None,
        "answer_grade": (
            "INCORRECT" if unsupported else ("CORRECT" if coverage == "FULL" else coverage)
        ),
        "raw_llm_answer": raw, "final_sanitized_answer": final_answer,
        "grounding_result": grounding, "final_grounding_result": capture.get("final_grounding_result"),
        "fact_ledger": ledger, "required_fact_plan": (row.get("planning") or {}).get("required_fact_plan"),
        "retrieved_evidence": capture["retrieved_evidence"], "final_context": capture["final_evidence"],
        "captured_retrieved_chunks": len(retrieved), "captured_final_chunks": len(final_evidence),
        "raw_claims": claims, "claim_to_fact_bindings": _bindings(claims, ledger),
        "deterministic_completions": (row.get("planning") or {}).get("fact_ledger_added_ids", []),
        "removed_claims": [claim for claim in claims if claim.get("disposition") == "UNSUPPORTED"],
        "rewritten_claims": capture.get("rewritten_claims", []),
        "required_fact_coverage": coverage, "required_facts": required, "missing_required_facts": missing,
        "grounding_supported_claims": len(supported_raw), "grounding_supported_claims_kept": kept,
        "grounding_unsupported_claims": sum(claim.get("disposition") == "UNSUPPORTED" for claim in claims),
        "grounding_unsupported_claims_rejected": sum(
            claim.get("disposition") == "UNSUPPORTED" and str(claim.get("text", "")).strip() not in final_answer
            for claim in claims
        ),
        "unsupported_numeric": unsupported, "evidence_utilization": coverage,
        "wrong_company": dimensions, "wrong_period": dimensions, "wrong_metric": dimensions,
        "dimension_validation": "SCOPED_PRODUCTION_SANITIZER_REPLAY",
        "over_sanitization": bool(missing and all(item.get("available") for item in required)),
    })


def _evaluate_rows(rows: list[dict[str, Any]], audit: list[dict[str, Any]], failure: str | None = None) -> None:
    for row in rows:
        captures = [entry for entry in audit if entry.get("question") == row["question"]]
        if failure or len(captures) != 1:
            _mark_not_evaluated(row, failure or ("AUDIT_RECORD_MISSING" if not captures else "AUDIT_RECORD_AMBIGUOUS"))
            continue
        try:
            _evaluate_row(row, captures[0])
        except AuditIntegrityError as exc:
            _mark_not_evaluated(row, str(exc))


def _measured_sum(rows: list[dict[str, Any]], key: str) -> int | str:
    values = [row.get(key) for row in rows]
    return sum(values) if values and all(isinstance(value, int) for value in values) else NOT_EVALUATED


def _planning_ledger(planning: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(planning, dict):
        return []
    ledger = planning.get("fact_ledger")
    return ledger if isinstance(ledger, list) else []


def _fact_matches_answer(answer: str, spec: dict[str, Any], ledger: list[dict[str, Any]]) -> bool:
    company = str(spec.get("company") or "").casefold()
    metric = str(spec.get("metric_id") or "")
    period = str(spec.get("period") or "").replace("_FY", "_").casefold()
    candidates = [
        fact for fact in ledger
        if str(fact.get("company", "")).casefold() == company
        and str(fact.get("metric_id", "")) == metric
        and (not period or period in str(fact.get("period", "")).replace("_FY", "_").casefold())
    ]
    if not candidates:
        return False
    normalized = str(answer or "").casefold().replace(",", "")
    aliases = {
        "operating_cash_flow": ("operating cash", "cash generated by operating", "经营活动现金流"),
        "data_center_revenue": ("data center", "datacenter", "数据中心"),
        "net_income": ("net income", "net profit", "净利润"),
        "revenue": ("revenue", "revenues", "net sales", "营收", "收入"),
        "eps": ("eps", "earnings per share", "每股收益"),
        "gross_margin": ("gross margin", "毛利率"),
    }
    labels = aliases.get(metric, (metric,))
    for line in normalized.splitlines():
        if not any(label in line for label in labels):
            continue
        for fact in candidates:
            raw_value = str(fact.get("value", "")).replace(",", "")
            if raw_value and (raw_value in line or _display_value_in_line(raw_value, line, fact.get("unit"))):
                return True
    return False


def _display_value_in_line(raw_value: str, line: str, unit: Any) -> bool:
    try:
        value = float(raw_value)
    except ValueError:
        return False
    scales = {"billion": (1_000_000_000, "billion"), "million": (1_000_000, "million")}
    scale, label = scales.get(str(unit), (1, ""))
    shown = value / scale
    candidates = {f"{shown:g}", f"{shown:.1f}", f"{shown:.3f}"}
    if str(unit) == "billion":
        # Chinese financial answers commonly render USD billions as 亿美元.
        candidates.update({f"{shown * 10:g}", f"{shown * 10:.1f}"})
        # Filing tables commonly present the same billion-scale fact as
        # integer millions (e.g. ``82,627 million``).  Accept that exact
        # display form without weakening the underlying normalized-value
        # comparison.
        candidates.update({f"{shown * 1000:g}", f"{shown * 1000:,.0f}"})
    if str(unit) == "million":
        candidates.update({f"{shown / 1000:g}", f"{shown / 1000:.3f}"})
    return any(
        candidate in line and (not label or label in line or "亿" in line or "million" in line)
        for candidate in candidates
    )


def _required_coverage(answer: str, planning: dict[str, Any] | None) -> tuple[str, list[dict[str, Any]], list[str]]:
    if not isinstance(planning, dict):
        return "FAILED", [], []
    plan = planning.get("required_fact_plan")
    ledger = _planning_ledger(planning)
    required = plan.get("required", []) if isinstance(plan, dict) else []
    missing = [
        f"{item.get('company')}:{item.get('metric_id')}:{item.get('period')}"
        for item in required
        if not _fact_matches_answer(answer, item, ledger)
    ]
    coverage = (
        NOT_EVALUATED if not required else "FULL" if not missing
        else "PARTIAL" if len(missing) < len(required) else "FAILED"
    )
    return coverage, required, missing


def _bindings(claims: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for claim in claims:
        text = str(claim.get("text", ""))
        if claim.get("disposition") not in {"SUPPORTED", "DERIVABLE"}:
            continue
        values = text.replace(",", "").split()
        matched = []
        for fact in ledger:
            raw = str(fact.get("value", "")).replace(",", "")
            if raw and any(raw in token for token in values):
                matched.append(fact.get("fact_id"))
        bindings.append({"claim": text, "fact_ids": [item for item in matched if item]})
    return bindings


def run() -> dict[str, Any]:
    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() not in {"1", "true", "yes"}:
        raise RuntimeError("P1.4.1 requires ALLOW_REAL_PROVIDER=true")
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite existing results: {OUTPUT}")
    if OUTPUT.parent.resolve() != (ROOT / "evaluation" / "results").resolve():
        raise RuntimeError("output name must be one directory name inside evaluation/results")
    selected = _freeze_selection()
    audit_capture = _preflight_audit()
    OUTPUT.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    email = f"p141-smoke-{secrets.token_hex(8)}@example.com"
    password = secrets.token_urlsafe(24)
    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0),
    ) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "name": "P1.4.1 Smoke"},
        )
        if register.status_code not in {200, 201}:
            raise RuntimeError("P1.4.1 smoke user registration failed")
        token_data = _json_response(register)
        token = token_data.get("token") or token_data.get("access_token")
        if not token:
            raise RuntimeError("P1.4.1 registration did not issue a token")
        client.headers["Authorization"] = "Bearer " + str(token)
        for case in selected:
            started = time.perf_counter()
            requested_at = datetime.now(timezone.utc)
            thread_id = "p141-smoke-" + secrets.token_hex(10)
            try:
                response = client.post(
                    "/api/v1/chat",
                    json={"question": case["question"], "thread_id": thread_id},
                )
                data = _json_response(response)
                status = response.status_code
                response_error = ""
            except Exception as exc:  # one failed request is final; never retry
                data = {"error_type": type(exc).__name__}
                status = 599
                response_error = type(exc).__name__
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            failure = response_failure(status, data)
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            rows.append({
                **case,
                "requested_at": requested_at.isoformat(),
                "thread_id": thread_id,
                "http_status": status,
                "http_success": status == 200,
                "application_success": application_success(status, data),
                "provider_failure": failure,
                "response_error": response_error,
                "empty_output": failure in {"EMPTY_REPORT", "EMPTY_MODEL_CONTENT"},
                "runtime_fallback": failure == "RUNTIME_FALLBACK",
                "provider_error": failure == "PROVIDER_ERROR",
                "total_latency_ms": elapsed_ms,
                "request_deadline_seconds": 120,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 45,
                "final_api_report": str(data.get("report") or ""),
                "final_citations": data.get("citations") if isinstance(data.get("citations"), list) else [],
                "planning": data.get("planning") if isinstance(data.get("planning"), dict) else None,
                "input_tokens": usage.get("input_tokens", "UNKNOWN"),
                "output_tokens": usage.get("output_tokens", "UNKNOWN"),
                "cached_tokens": usage.get("cached_tokens", "UNKNOWN"),
                "provider_calls": len(usage.get("calls", [])) if isinstance(usage.get("calls"), list) else "UNKNOWN",
                "main_query_cost": actual_cost(usage, requested_at) or "UNKNOWN",
                "evaluator_calls": 0,
                "evaluator_cost": "$0",
            })
            # Persist every completed HTTP attempt before audit copying or
            # quality evaluation can fail. Never store the auth response or
            # request headers alongside these diagnostic artifacts.
            _write_json(OUTPUT / f"{case['id']}.http.json", {"measurement": rows[-1], "response_body": data})
            if status != 200 or not rows[-1]["application_success"] or failure is not None:
                break
    audit_failure = None
    try:
        audit = _copy_audit(audit_capture)
    except AuditIntegrityError as exc:
        audit, audit_failure = [], str(exc)
    _evaluate_rows(rows, audit, audit_failure)
    summary: dict[str, Any] = {
        "fact_ledger_recheck_status": "FAIL",
        "audit_integrity": "PASS" if rows and all(row["audit_integrity"] == "PASS" for row in rows) else "FAIL",
        "audit_failures": sorted({row["audit_failure"] for row in rows if row.get("audit_failure")}),
        "not_evaluated": sum(row.get("evidence_utilization") == NOT_EVALUATED for row in rows),
        "real_provider_calls": _measured_sum(rows, "provider_calls"),
        "http_success": sum(row["http_success"] for row in rows),
        "application_success": sum(row["application_success"] for row in rows),
        "correct": sum(
            row.get("answer_grade") == "CORRECT"
            and not row.get("provider_failure")
            for row in rows
        ),
        "partial": sum(row.get("answer_grade") == "PARTIAL" for row in rows),
        "incorrect": sum(row.get("answer_grade") == "INCORRECT" for row in rows),
        "failed": sum(row.get("answer_grade") == "FAILED" or bool(row.get("provider_failure")) for row in rows),
        "fact_ledger_facts": sum(len(row.get("fact_ledger", [])) for row in rows),
        "required_fact_full": sum(row.get("required_fact_coverage") == "FULL" for row in rows),
        "supported_claims": _measured_sum(rows, "grounding_supported_claims"),
        "supported_claims_kept": _measured_sum(rows, "grounding_supported_claims_kept"),
        "unsupported_claims": _measured_sum(rows, "grounding_unsupported_claims"),
        "unsupported_claims_rejected": _measured_sum(rows, "grounding_unsupported_claims_rejected"),
        "grounding_keep_rate": None,
        "grounding_rejection_rate": None,
        "evidence_utilization_full": sum(row.get("evidence_utilization") == "FULL" for row in rows),
        "wrong_company": _measured_sum(rows, "wrong_company"),
        "wrong_period": _measured_sum(rows, "wrong_period"),
        "wrong_metric": _measured_sum(rows, "wrong_metric"),
        "unsupported_numeric": _measured_sum(rows, "unsupported_numeric"),
        "deterministic_completions": sum(len(row.get("deterministic_completions", [])) for row in rows),
        "over_sanitization": _measured_sum(rows, "over_sanitization"),
        "empty_output": sum(row.get("empty_output", False) for row in rows),
        "runtime_fallback": sum(row.get("runtime_fallback", False) for row in rows),
        "provider_error": sum(row.get("provider_error", False) for row in rows),
        "input_tokens": _measured_sum(rows, "input_tokens"),
        "output_tokens": _measured_sum(rows, "output_tokens"),
        "cached_tokens": _measured_sum(rows, "cached_tokens"),
        "main_query_cost": (
            "UNKNOWN"
            if any(row["main_query_cost"] == "UNKNOWN" for row in rows)
            else round(sum(row["main_query_cost"] for row in rows), 9)
        ),
        "evaluator_cost": "$0",
        "latency_p50_ms": None,
        "latency_max_ms": max((row["total_latency_ms"] for row in rows), default=None),
        "allow_real_provider_restored": False,
        "cases_completed": len(rows),
        "cases_expected": len(CASE_IDS),
    }
    if isinstance(summary["supported_claims"], int) and summary["supported_claims"]:
        summary["grounding_keep_rate"] = round(summary["supported_claims_kept"] / summary["supported_claims"], 4)
    if isinstance(summary["unsupported_claims"], int) and summary["unsupported_claims"]:
        summary["grounding_rejection_rate"] = round(
            summary["unsupported_claims_rejected"] / summary["unsupported_claims"], 4
        )
    latencies = sorted(row["total_latency_ms"] for row in rows)
    if latencies:
        summary["latency_p50_ms"] = latencies[(len(latencies) - 1) // 2]
    summary["fact_ledger_recheck_status"] = "PASS" if all([
        summary["audit_integrity"] == "PASS",
        summary["cases_completed"] == 5,
        summary["http_success"] == 5,
        summary["application_success"] == 5,
        summary["correct"] == 5,
        summary["required_fact_full"] == 5,
        summary["evidence_utilization_full"] == 5,
        summary["wrong_company"] == 0,
        summary["wrong_period"] == 0,
        summary["wrong_metric"] == 0,
        summary["unsupported_numeric"] == 0,
        summary["over_sanitization"] == 0,
        summary["empty_output"] == 0,
        summary["runtime_fallback"] == 0,
        summary["provider_error"] == 0,
    ]) else "FAIL"
    for row in rows:
        _write_json(OUTPUT / f"{row['id']}.json", row)
    _write_json(OUTPUT / "summary.json", summary)
    print("FACT_LEDGER_RECHECK_STATUS:", summary["fact_ledger_recheck_status"])
    print("REAL_PROVIDER_CALLS:", summary["real_provider_calls"])
    print("HTTP_SUCCESS:", f"{summary['http_success']}/5")
    print("APPLICATION_SUCCESS:", f"{summary['application_success']}/5")
    print("CORRECT:", f"{summary['correct']}/5")
    print("REQUIRED_FACT_FULL:", f"{summary['required_fact_full']}/5")
    print("EVIDENCE_UTILIZATION_FULL:", f"{summary['evidence_utilization_full']}/5")
    return summary


if __name__ == "__main__":
    run()
