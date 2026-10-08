"""Run the frozen Moutai 10Q once through an isolated localhost QA API.

This runner never contacts a Provider directly, never retries a question, and
never writes bearer tokens or test passwords to the result artifact.
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "evaluation/datasets/cninfo_guizhou_moutai_2025_zh_10.json"
RESULTS_DIR = ROOT / "evaluation/results/cninfo_guizhou_moutai_2025_zh_10"


def _request_json(
    url: str,
    *,
    payload: dict | None = None,
    bearer_token: str | None = None,
    timeout_seconds: float = 20,
) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    parsed = json.loads(raw.decode("utf-8")) if raw else {}
    return status, parsed if isinstance(parsed, dict) else {}


def _save_result(path: Path, result: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _case_request_payload(
    case: dict,
    run_id: str,
    *,
    frontend_contract: bool,
) -> dict:
    """Build either the historical evaluator request or the actual UI payload."""

    payload = {
        "question": case["question"],
        "thread_id": run_id if frontend_contract else f"{run_id}-{case['id']}",
        "answer_language": "zh-CN",
    }
    if not frontend_contract:
        payload["company"] = "贵州茅台"
    return payload


def run_locale_smoke(base_url: str, run_id: str, response_language: str) -> int:
    """Verify one selected UI language against a Chinese financial question."""
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("QA runner accepts only an HTTP localhost base URL")
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid run id")

    output_path = RESULTS_DIR / f"{run_id}.json"
    if output_path.exists():
        raise SystemExit("Refusing to overwrite an existing result artifact")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    root_url = base_url.rstrip("/")
    health_status, _ = _request_json(f"{root_url}/api/v1/ready", timeout_seconds=10)
    if health_status != 200:
        raise SystemExit(f"QA readiness failed: HTTP {health_status}")

    email = f"moutai-en-smoke-{uuid.uuid4().hex}@example.com"
    password = secrets.token_urlsafe(24)
    register_status, registered = _request_json(
        f"{root_url}/api/v1/auth/register",
        payload={"email": email, "password": password},
    )
    if register_status != 201 or not registered.get("token"):
        raise SystemExit(f"QA test account registration failed: HTTP {register_status}")
    token = str(registered["token"])
    identity_status, identity = _request_json(
        f"{root_url}/api/v1/auth/me", bearer_token=token,
    )
    if identity_status != 200:
        raise SystemExit(f"QA identity check failed: HTTP {identity_status}")
    knowledge_status, knowledge = _request_json(
        f"{root_url}/api/v1/knowledge", bearer_token=token,
    )
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if (
        knowledge_status != 200
        or dataset["metadata"]["source_filename"] not in knowledge.get("documents", [])
    ):
        raise SystemExit("Expected annual report is not present in the isolated QA tenant")

    question = "2025年归属于上市公司股东的净利润是多少？"
    started = time.monotonic()
    try:
        status, response = _request_json(
            f"{root_url}/api/v1/chat",
            payload={
                "question": question,
                "company": "贵州茅台",
                "thread_id": f"{run_id}-{response_language}",
                "answer_language": response_language,
            },
            bearer_token=token,
            timeout_seconds=125,
        )
    except (TimeoutError, urllib.error.URLError) as exc:
        response = {}
        status = None
        transport_error_type = type(exc).__name__
    else:
        transport_error_type = None

    report = str(response.get("report", ""))
    citations = response.get("citations", [])
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    result = {
        "run_id": run_id,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "test_type": f"separate {response_language} UI locale smoke; excluded from frozen 10Q score",
        "question": question,
        "answer_language": response_language,
        "qa_tenant_id": (identity.get("tenant") or {}).get("id"),
        "provider_policy": "Ollama-compatible local endpoint; remote Provider calls disabled",
        "real_remote_provider_calls": 0,
        "evaluator_calls": 0,
        "http_status": status,
        "application_success": status == 200 and bool(report.strip()),
        "latency_seconds": round(time.monotonic() - started, 3),
        "final_api_report": report,
        "citations": citations if isinstance(citations, list) else [],
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cached_tokens": usage.get("cached_tokens"),
        },
        "transport_error_type": transport_error_type,
    }
    _save_result(output_path, result)
    print(
        f"{response_language.upper()}_LOCALE_SMOKE: HTTP {status}; "
        f"latency={result['latency_seconds']}s; citations={len(result['citations'])}"
    )
    print(f"Artifact: {output_path.relative_to(ROOT).as_posix()}")
    return 0 if result["application_success"] else 2


def run(
    base_url: str,
    run_id: str,
    case_ids: list[str] | None = None,
    *,
    frontend_contract: bool = False,
) -> int:
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("QA runner accepts only an HTTP localhost base URL")
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid run id")

    output_path = RESULTS_DIR / f"{run_id}.json"
    if output_path.exists():
        raise SystemExit("Refusing to overwrite an existing result artifact")

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if dataset.get("dataset_id") != "cninfo_guizhou_moutai_2025_zh_10":
        raise SystemExit("Unexpected frozen dataset")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or len(cases) != 10:
        raise SystemExit("Frozen dataset must contain exactly 10 cases")
    if case_ids:
        by_id = {str(case.get("id")): case for case in cases}
        unknown_ids = sorted(set(case_ids) - set(by_id))
        if unknown_ids:
            raise SystemExit(f"Unknown frozen case id(s): {', '.join(unknown_ids)}")
        cases_by_id = {str(case.get("id")): case for case in cases}
        cases = [cases_by_id[case_id] for case_id in case_ids]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    root_url = base_url.rstrip("/")
    health_status, health = _request_json(
        f"{root_url}/api/v1/ready", timeout_seconds=10,
    )
    if health_status != 200:
        raise SystemExit(f"QA readiness failed: HTTP {health_status}")

    # A unique QA-only account and token exist only in process memory. The
    # result artifact records neither credential nor Authorization metadata.
    suffix = uuid.uuid4().hex
    account_email = f"moutai-qa-{suffix}@example.com"
    account_password = secrets.token_urlsafe(24)
    register_status, registered = _request_json(
        f"{root_url}/api/v1/auth/register",
        payload={"email": account_email, "password": account_password},
    )
    if register_status != 201 or not registered.get("token"):
        raise SystemExit(f"QA test account registration failed: HTTP {register_status}")
    bearer_token = str(registered["token"])
    me_status, identity = _request_json(
        f"{root_url}/api/v1/auth/me", bearer_token=bearer_token,
    )
    if me_status != 200:
        raise SystemExit(f"QA identity check failed: HTTP {me_status}")
    tenant = identity.get("tenant") or {}
    tenant_id = tenant.get("id") if isinstance(tenant, dict) else None

    knowledge_status, knowledge = _request_json(
        f"{root_url}/api/v1/knowledge", bearer_token=bearer_token,
    )
    expected_filename = dataset["metadata"]["source_filename"]
    filenames = knowledge.get("documents", []) if knowledge_status == 200 else []
    if knowledge_status != 200 or expected_filename not in filenames:
        raise SystemExit("Expected audited annual report is not present in isolated QA tenant")

    result = {
        "run_id": run_id,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset["metadata"]["source_sha256"],
        "qa_base_url": base_url,
        "qa_tenant_id": tenant_id,
        "provider_policy": "Ollama-compatible local endpoint; remote Provider calls disabled",
        "answer_language": "zh-CN",
        "selected_case_ids": [case["id"] for case in cases],
        "request_contract": (
            "frontend: question/thread_id/answer_language; shared thread; no company field"
            if frontend_contract
            else "evaluation: explicit company field; isolated thread per question"
        ),
        "expected_source_present": True,
        "real_remote_provider_calls": 0,
        "evaluator_calls": 0,
        "questions": [],
        "status": "RUNNING",
    }
    _save_result(output_path, result)

    for index, case in enumerate(cases, start=1):
        question_started = time.monotonic()
        request_payload = _case_request_payload(
            case,
            run_id,
            frontend_contract=frontend_contract,
        )
        try:
            status, response = _request_json(
                f"{root_url}/api/v1/chat",
                payload=request_payload,
                bearer_token=bearer_token,
                timeout_seconds=125,
            )
        except (TimeoutError, urllib.error.URLError) as exc:
            item = {
                "case_id": case["id"],
                "question": case["question"],
                "http_status": None,
                "application_success": False,
                "latency_seconds": round(time.monotonic() - question_started, 3),
                "transport_error_type": type(exc).__name__,
                "grade": "FAILED",
            }
            result["questions"].append(item)
            result["status"] = "STOPPED_TRANSPORT_FAILURE"
            _save_result(output_path, result)
            print(f"{case['id']}: TRANSPORT_FAILURE; stopped without retry")
            return 2

        report = str(response.get("report", ""))
        citations = response.get("citations", [])
        runtime_failure = any(
            report.startswith(marker)
            for marker in (
                "[Provider Disabled]",
                "[Provider Configuration Error]",
                "[Provider Error]",
                "[Agent Runtime Fallback]",
            )
        )
        application_success = status == 200 and bool(report.strip()) and not runtime_failure
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        item = {
            "case_id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "expected_answer": case.get("expected_answer"),
            "reference_claims": case.get("reference_claims", []),
            "criteria": case.get("criteria", []),
            "answer_language": request_payload["answer_language"],
            "http_status": status,
            "application_success": application_success,
            "latency_seconds": round(time.monotonic() - question_started, 3),
            "execution_time_seconds": response.get("execution_time"),
            "final_api_report": report,
            "citations": citations if isinstance(citations, list) else [],
            "reasoning": response.get("reasoning"),
            "plan": response.get("plan"),
            "planning": response.get("planning"),
            "execution": response.get("execution"),
            "workflow": response.get("workflow"),
            "usage": {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cached_tokens": usage.get("cached_tokens"),
            },
            "runtime_failure": runtime_failure,
            "grade": "PENDING_SEMANTIC_REVIEW" if application_success else "FAILED",
        }
        result["questions"].append(item)
        print(
            f"{index}/{len(cases)} {case['id']}: HTTP {status}, "
            f"{item['latency_seconds']}s, citations={len(item['citations'])}"
        )
        _save_result(output_path, result)
        if not application_success:
            result["status"] = "STOPPED_APPLICATION_FAILURE"
            _save_result(output_path, result)
            print("Stopped after first runtime failure; no question was retried or replaced.")
            return 2

    result["status"] = "COMPLETED_PENDING_SEMANTIC_REVIEW"
    result["finished_at_utc"] = datetime.now(UTC).isoformat()
    _save_result(output_path, result)
    print(f"Completed {len(cases)} selected frozen question(s); semantic grading is still required.")
    print(f"Artifact: {output_path.relative_to(ROOT).as_posix()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--case-ids",
        nargs="+",
        help="run only these frozen case IDs; omitted means the complete 10Q set",
    )
    parser.add_argument(
        "--frontend-contract",
        action="store_true",
        help=(
            "match the UI request body exactly: omit company and reuse one thread; "
            "provide case IDs in conversational order"
        ),
    )
    parser.add_argument(
        "--english-locale-smoke",
        action="store_true",
        help="run one separate English-UI locale check, not the 10Q benchmark",
    )
    parser.add_argument(
        "--locale-smoke",
        choices=("en", "zh-CN"),
        help="run one separate selected-UI-language check, not the 10Q benchmark",
    )
    args = parser.parse_args()
    if args.english_locale_smoke:
        return run_locale_smoke(args.base_url, args.run_id, "en")
    if args.locale_smoke:
        return run_locale_smoke(args.base_url, args.run_id, args.locale_smoke)
    return run(
        args.base_url,
        args.run_id,
        args.case_ids,
        frontend_contract=args.frontend_contract,
    )


if __name__ == "__main__":
    raise SystemExit(main())
