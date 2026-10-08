"""One-shot smoke diagnostics fail closed without any provider calls."""

import copy
import json
import subprocess

import pytest

from evaluation import p1_4_1_real_provider_fact_ledger_recheck as smoke


def _result(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, "private diagnostics must not be exposed")


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"error": "AUDIT_DISABLED"}, "AUDIT_DISABLED"),
        ({"path": "../../audit.jsonl", "offset": 0, "writable": True}, "AUDIT_PATH_INVALID"),
        ({"path": "/tmp/audit.jsonl", "offset": 0, "writable": False}, "AUDIT_NOT_WRITABLE"),
    ],
)
def test_preflight_reports_bounded_errors(monkeypatch, state, expected):
    results = iter([_result("abc123\n"), _result(json.dumps(state))])
    monkeypatch.setattr(smoke, "_docker", lambda _: next(results))
    with pytest.raises(smoke.AuditIntegrityError, match=f"^{expected}$"):
        smoke._preflight_audit()


def test_preflight_uses_production_audit_setting_and_offset(monkeypatch):
    monkeypatch.delenv("P1_4_RECHECK_AUDIT_PATH", raising=False)
    calls = []
    results = iter([
        _result("abc123\n"),
        _result(json.dumps({"path": "/tmp/actual-production-audit.jsonl", "offset": 426, "writable": True})),
    ])

    def docker(args):
        calls.append(args)
        return next(results)

    monkeypatch.setattr(smoke, "_docker", docker)
    captured = smoke._preflight_audit()
    assert captured == smoke.AuditCapture("abc123", "/tmp/actual-production-audit.jsonl", 426)
    assert "P1_3_SMOKE_AUDIT_PATH" in calls[1][-1]
    assert "Config.Env" not in calls[1][-1]


def test_preflight_rejects_different_explicit_path(monkeypatch):
    monkeypatch.setenv("P1_4_RECHECK_AUDIT_PATH", "/tmp/wrong.jsonl")
    results = iter([
        _result("abc123"),
        _result(json.dumps({"path": "/tmp/actual.jsonl", "offset": 0, "writable": True})),
    ])
    monkeypatch.setattr(smoke, "_docker", lambda _: next(results))
    with pytest.raises(smoke.AuditIntegrityError, match="^AUDIT_PATH_MISMATCH$"):
        smoke._preflight_audit()


def test_disabled_audit_fails_before_auth_or_chat(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "true")
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "OUTPUT", tmp_path / "evaluation/results/new-run")
    monkeypatch.setattr(smoke, "_freeze_selection", lambda: [])

    def fail_preflight():
        raise smoke.AuditIntegrityError("AUDIT_DISABLED")

    monkeypatch.setattr(smoke, "_preflight_audit", fail_preflight)
    monkeypatch.setattr(smoke.httpx, "Client", lambda **_: pytest.fail("HTTP must not start"))
    with pytest.raises(smoke.AuditIntegrityError, match="AUDIT_DISABLED"):
        smoke.run()
    assert not smoke.OUTPUT.exists()


def test_copy_preserves_only_new_audit_records(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "OUTPUT", tmp_path)
    calls = []

    def docker(args):
        calls.append(args)
        return _result('{"question":"new question"}\n')

    monkeypatch.setattr(smoke, "_docker", docker)
    assert smoke._copy_audit(smoke.AuditCapture("abc123", "/tmp/audit.jsonl", 512)) == [
        {"question": "new question"}
    ]
    assert calls[0][-2:] == ["/tmp/audit.jsonl", "512"]
    assert "handle.seek(offset)" in calls[0][-3]
    assert (tmp_path / "raw_grounding_audit.jsonl").read_text() == '{"question":"new question"}\n'


def _case_and_capture():
    answer = "NVIDIA Q1 FY2027 revenue was $81.6 billion [1]."
    metadata = {"chunk_id": "current-live-chunk-not-in-reference", "company": "NVIDIA", "quarter": "Q1_FY2027"}
    evidence = {
        "content": "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
        "metadata": metadata, "company": "NVIDIA", "source": "NVIDIA_current.pdf",
        "chunk_id": metadata["chunk_id"],
    }
    row = {
        "id": "EN-007", "question": "What was NVIDIA Q1 FY2027 revenue?",
        "final_citations": [{"source": evidence["source"], "chunk_id": metadata["chunk_id"]}],
        "planning": {
            "required_fact_plan": {"required": [
                {"company": "nvidia", "metric_id": "revenue", "period": "Q1_FY2027", "available": True}
            ]},
            "fact_ledger": [{"company": "nvidia", "metric_id": "revenue", "period": "Q1_FY2027",
                             "value": "81600000000", "unit": "billion", "fact_id": "f1"}],
        },
    }
    row["final_api_report"] = smoke.build_research_report(
        row["question"], answer, row["final_citations"], smoke.analyze_evidence(row["final_citations"]),
    )
    capture = {
        "question": row["question"], "raw_llm_answer": answer,
        "final_sanitized_answer": answer, "final_api_report": row["final_api_report"],
        "grounding_result": {"claims": [{"text": answer, "disposition": "SUPPORTED"}]},
        "final_grounding_result": {"claims": [{"text": answer, "disposition": "SUPPORTED"}]},
        "retrieved_evidence": [evidence], "final_evidence": [copy.deepcopy(evidence)],
    }
    return row, capture


def test_complete_current_evidence_is_used_without_frozen_lookup():
    row, capture = _case_and_capture()
    smoke._evaluate_rows([row], [capture])
    assert row["audit_integrity"] == "PASS"
    assert row["unsupported_numeric"] == 0
    assert row["required_fact_coverage"] == "FULL"
    assert row["raw_llm_answer"] == capture["raw_llm_answer"]
    assert row["final_context"][0]["metadata"]["quarter"] == "Q1_FY2027"
    assert row["wrong_company"] == row["wrong_period"] == row["wrong_metric"] == 0


@pytest.mark.parametrize("missing", [
    "raw_llm_answer", "grounding_result", "final_grounding_result", "final_evidence", "retrieved_evidence",
])
def test_missing_capture_never_claims_zero_grounding_errors(missing):
    row, capture = _case_and_capture()
    del capture[missing]
    smoke._evaluate_rows([row], [capture])
    assert row["audit_integrity"] == "FAIL"
    assert row["unsupported_numeric"] == smoke.NOT_EVALUATED
    assert row["wrong_company"] == row["wrong_period"] == row["wrong_metric"] == smoke.NOT_EVALUATED
    assert row["required_fact_coverage"] == smoke.NOT_EVALUATED


def test_live_citation_missing_from_evidence_is_not_an_unsupported_claim():
    row, capture = _case_and_capture()
    row["final_citations"][0]["chunk_id"] = "not-captured"
    smoke._evaluate_rows([row], [capture])
    assert row["audit_failure"] == "AUDIT_CITATION_EVIDENCE_MISSING"
    assert row["unsupported_numeric"] == smoke.NOT_EVALUATED


def test_incomplete_content_does_not_fall_back_to_preview_or_stale_reference():
    row, capture = _case_and_capture()
    capture["final_evidence"][0].pop("content")
    capture["final_evidence"][0]["preview"] = "NVIDIA revenue $81.6B"
    smoke._evaluate_rows([row], [capture])
    assert row["audit_failure"] == "AUDIT_EVIDENCE_INCOMPLETE"
    assert row["unsupported_numeric"] == smoke.NOT_EVALUATED


def test_duplicate_capture_cannot_be_silently_replaced():
    row, capture = _case_and_capture()
    smoke._evaluate_rows([row], [capture, copy.deepcopy(capture)])
    assert row["audit_failure"] == "AUDIT_RECORD_AMBIGUOUS"


def test_api_report_must_match_captured_production_output():
    row, capture = _case_and_capture()
    row["final_api_report"] += "\nUncaptured claims"
    smoke._evaluate_rows([row], [capture])
    assert row["audit_failure"] == "AUDIT_API_RESPONSE_MISMATCH"


def test_wrong_final_value_is_rejected_with_unmeasured_dimensions():
    row, capture = _case_and_capture()
    capture["final_sanitized_answer"] = "NVIDIA Q1 FY2027 revenue was $91 billion [1]."
    row["final_api_report"] = smoke.build_research_report(
        row["question"], capture["final_sanitized_answer"], row["final_citations"],
        smoke.analyze_evidence(row["final_citations"]),
    )
    capture["final_api_report"] = row["final_api_report"]
    smoke._evaluate_rows([row], [capture])
    assert row["unsupported_numeric"] > 0
    assert row["wrong_company"] == row["wrong_period"] == row["wrong_metric"] == smoke.NOT_EVALUATED


def test_captured_report_appendix_still_requires_grounding():
    row, capture = _case_and_capture()
    row["final_api_report"] += "\n## Unchecked analysis\nApple revenue was $123 billion."
    capture["final_api_report"] = row["final_api_report"]
    smoke._evaluate_rows([row], [capture])
    assert row["audit_failure"] == "AUDIT_UNGROUNDED_REPORT_CONTENT"


@pytest.mark.parametrize("dimension", ["company", "period", "metric"])
def test_incompatible_financial_evidence_never_proves_zero_errors(dimension):
    row, capture = _case_and_capture()
    if dimension == "company":
        capture["final_evidence"][0]["company"] = "Apple"
        capture["final_evidence"][0]["content"] = "Apple Q1 FY2027 revenue was $81.6 billion."
    elif dimension == "period":
        capture["final_evidence"][0]["content"] = "NVIDIA Q2 FY2027 revenue guidance was $81.6 billion."
        capture["final_evidence"][0]["metadata"]["quarter"] = "Q2_FY2027"
    else:
        capture["final_evidence"][0]["content"] = "NVIDIA Q1 FY2027 operating income was $81.6 billion."
    smoke._evaluate_rows([row], [capture])
    assert row["unsupported_numeric"] > 0
    assert row[f"wrong_{dimension}"] == smoke.NOT_EVALUATED


def test_measurement_sum_preserves_unknown():
    assert smoke._measured_sum([{"value": 0}, {"value": smoke.NOT_EVALUATED}], "value") == smoke.NOT_EVALUATED
    assert smoke._measured_sum([{"value": 2}, {"value": 3}], "value") == 5


def test_raw_http_survives_failed_postflight(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_REAL_PROVIDER", "true")
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    monkeypatch.setattr(smoke, "OUTPUT", tmp_path / "evaluation/results/run")
    case, _ = _case_and_capture()
    monkeypatch.setattr(smoke, "_freeze_selection", lambda: [{"id": case["id"], "question": case["question"]}])
    monkeypatch.setattr(smoke, "_preflight_audit", lambda: smoke.AuditCapture("abc", "/tmp/audit.jsonl", 0))
    calls = []

    class Client:
        def __init__(self, **_):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, endpoint, json):
            calls.append(endpoint)
            if endpoint.endswith("register"):
                return smoke.httpx.Response(201, json={"token": "local-test-token"})
            return smoke.httpx.Response(200, json={"report": case["final_api_report"], "citations": []})

    def missing_audit(_):
        artifact = smoke.OUTPUT / "EN-007.http.json"
        assert artifact.exists(), "HTTP attempt must be durable before postflight"
        assert "local-test-token" not in artifact.read_text(encoding="utf-8")
        raise smoke.AuditIntegrityError("AUDIT_NOT_CAPTURED")

    monkeypatch.setattr(smoke.httpx, "Client", Client)
    monkeypatch.setattr(smoke, "_copy_audit", missing_audit)
    result = smoke.run()
    assert calls == ["/api/v1/auth/register", "/api/v1/chat"]
    assert result["fact_ledger_recheck_status"] == "FAIL"
    assert result["unsupported_numeric"] == smoke.NOT_EVALUATED
    assert result["wrong_company"] == smoke.NOT_EVALUATED
    assert result["not_evaluated"] == 1
    assert (smoke.OUTPUT / "summary.json").exists()


def test_write_never_overwrites_prior_artifacts(tmp_path):
    path = tmp_path / "prior.json"
    smoke._write_json(path, {"preserved": True})
    with pytest.raises(FileExistsError):
        smoke._write_json(path, {"preserved": False})
    assert json.loads(path.read_text()) == {"preserved": True}
