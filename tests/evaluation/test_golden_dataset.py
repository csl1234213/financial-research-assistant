from evaluation.dataset import (
    GOLDEN_DATASET_SCHEMA_VERSION,
    GoldenDatasetValidationError,
    load_golden_dataset,
    parse_golden_dataset,
)
from evaluation.metrics import ranked_retrieval_metrics


def test_versioned_financial_golden_dataset_is_valid():
    dataset = load_golden_dataset("evaluation/datasets/financial_golden_v1.json")

    assert dataset.schema_version == GOLDEN_DATASET_SCHEMA_VERSION
    assert dataset.dataset_id == "financial-agent-golden-v1"
    assert len(dataset.cases) == 6
    scenarios = {case["metadata"]["scenario"] for case in dataset.cases}
    assert {
        "direct_chat",
        "single_company_rag",
        "company_comparison",
        "insufficient_evidence",
    } <= scenarios
    assert dataset.cases[1]["expected_retrieval_ids"]


def test_golden_dataset_rejects_duplicate_case_ids():
    raw = {
        "schema_version": "1.0",
        "dataset_id": "duplicate-test",
        "cases": [
            {"id": "same", "question": "First"},
            {"id": "same", "question": "Second"},
        ],
    }

    try:
        parse_golden_dataset(raw)
    except GoldenDatasetValidationError as exc:
        assert "Duplicate case id" in str(exc)
    else:
        raise AssertionError("Expected GoldenDatasetValidationError")


def test_golden_dataset_rejects_invalid_offline_contract_types():
    raw = {
        "schema_version": "1.0",
        "dataset_id": "invalid-contract",
        "cases": [
            {
                "id": "bad-boolean",
                "question": "Question",
                "expected_companies": "Tesla",
                "expected_use_retrieval": "yes",
            }
        ],
    }

    try:
        parse_golden_dataset(raw)
    except GoldenDatasetValidationError as exc:
        assert "expected_companies" in str(exc) or "expected_use_retrieval" in str(exc)
    else:
        raise AssertionError("Expected GoldenDatasetValidationError")


def test_ranked_retrieval_metrics_capture_rank_and_recall():
    metrics = ranked_retrieval_metrics(
        ["chunk_b", "chunk_a", "chunk_c"],
        ["chunk_a", "chunk_b"],
        k=3,
    )

    assert metrics["precision_at_k"] == 66.7
    assert metrics["recall_at_k"] == 100.0
    assert metrics["mrr"] == 100.0
    assert metrics["ndcg"] > 90.0
