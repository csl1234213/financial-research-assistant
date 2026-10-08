import json
import socket
from unittest.mock import patch

from evaluation.offline import (
    DEFAULT_DATASET_PATH,
    main,
    run_offline_golden_evaluation,
)


def test_offline_golden_evaluation_runs_real_planning_contracts_without_network():
    with patch.object(
        socket,
        "socket",
        side_effect=AssertionError("offline evaluation must not open a socket"),
    ):
        report = run_offline_golden_evaluation(DEFAULT_DATASET_PATH)

    assert report["execution_mode"] == "offline_deterministic"
    assert report["summary"] == {
        "total_cases": 6,
        "passed_cases": 6,
        "failed_cases": 0,
        "average_contract_score": 100.0,
        "threshold_passed": True,
    }
    assert report["assurance_boundary"]["llm_invoked"] is False
    assert report["assurance_boundary"]["retriever_invoked"] is False
    assert report["assurance_boundary"]["model_quality_claimed"] is False

    scenarios = {result["scenario"] for result in report["results"]}
    assert {
        "direct_chat",
        "single_company_rag",
        "company_comparison",
        "insufficient_evidence",
    } <= scenarios
    assert all(
        "model_quality" in result["evaluation"]["unmeasured_dimensions"]
        for result in report["results"]
    )


def test_offline_report_is_deterministic_and_cli_writes_json(tmp_path):
    first = run_offline_golden_evaluation(DEFAULT_DATASET_PATH)
    second = run_offline_golden_evaluation(DEFAULT_DATASET_PATH)
    assert first == second

    report_path = tmp_path / "offline-report.json"
    exit_code = main(
        [
            "--dataset",
            str(DEFAULT_DATASET_PATH),
            "--report",
            str(report_path),
            "--threshold",
            "100",
        ]
    )

    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8")) == first


def test_cli_exit_code_is_driven_by_configured_contract_threshold(tmp_path):
    dataset_path = tmp_path / "mismatch.json"
    dataset_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "dataset_id": "threshold-test",
                "cases": [
                    {
                        "id": "direct-chat-mismatch",
                        "question": "What is AI?",
                        "expected_intent": "DIRECT_CHAT",
                        "expected_companies": [],
                        "expected_task_type": "chat",
                        "expected_workflow": "rag",
                        "expected_strategy": "direct_llm",
                        "expected_tools": [],
                        "expected_use_retrieval": False,
                        "expected_use_tools": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    strict_report = tmp_path / "strict.json"
    lenient_report = tmp_path / "lenient.json"

    assert main(
        [
            "--dataset",
            str(dataset_path),
            "--report",
            str(strict_report),
            "--threshold",
            "100",
        ]
    ) == 1
    assert main(
        [
            "--dataset",
            str(dataset_path),
            "--report",
            str(lenient_report),
            "--threshold",
            "80",
        ]
    ) == 0

    strict = json.loads(strict_report.read_text(encoding="utf-8"))
    assert strict["summary"]["average_contract_score"] == 87.5
    assert strict["summary"]["threshold_passed"] is False
    assert strict["results"][0]["evaluation"]["issues"][0]["type"] == "workflow_type_contract"
