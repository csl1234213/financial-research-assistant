import json

import pytest

from evaluation.finalize_100 import finalize, metrics, percentile, unused_context_count_text


def test_percentiles_use_linear_interpolation():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([1, 2, 3, 4], 95) == 3.85


def test_historical_citation_ledger_does_not_claim_zero_unused_context():
    assert unused_context_count_text({"VALID_SUPPORTED": 4}) == "未按新口径单独统计"
    assert unused_context_count_text({"UNUSED_RETRIEVED_CONTEXT": 0}) == "0"


def test_failed_answers_remain_in_strict_denominator():
    rows = [
        {"answer_grade": "CORRECT", "latency_ms": 100, "status_code": 200},
        {"answer_grade": "FAILED", "latency_ms": 5, "status_code": 200},
    ]
    result = metrics(rows)
    assert result["http_200"] == 2
    assert result["valid_completed"] == 1
    assert result["accuracy_valid_completed"] == 1
    assert result["strict_correct_over_requested"] == 0.5


def test_all_failed_answers_have_unknown_valid_accuracy():
    result = metrics([{"answer_grade": "FAILED", "latency_ms": 5, "status_code": 200}])
    assert result["accuracy_valid_completed"] is None
    assert result["strict_correct_over_requested"] == 0


def test_incomplete_execution_cannot_generate_complete_report(tmp_path):
    (tmp_path / "evaluation_100_results.jsonl").write_text("")
    (tmp_path / "dataset.json").write_text("[]")
    (tmp_path / "dataset_freeze.json").write_text(json.dumps({"sha256": "invalid"}))
    with pytest.raises(ValueError, match="100 real requests"):
        finalize(tmp_path)
    assert not (tmp_path / "report.md").exists()
