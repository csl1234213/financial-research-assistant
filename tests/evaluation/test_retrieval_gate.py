from __future__ import annotations

import json
import socket
from copy import deepcopy
from unittest.mock import patch

from evaluation.retrieval_dataset import load_retrieval_dataset
from evaluation.retrieval_gate import (
    DEFAULT_RETRIEVAL_DATASET_PATH,
    AdversarialInMemoryEvaluationStore,
    SeededHashEmbeddingModel,
    main,
    run_retrieval_evaluation,
    save_retrieval_report,
)


def test_seeded_retrieval_gate_runs_production_chain_without_network():
    with patch.object(
        socket,
        "socket",
        side_effect=AssertionError("retrieval evaluation must not open a socket"),
    ):
        report = run_retrieval_evaluation(DEFAULT_RETRIEVAL_DATASET_PATH)

    assert report["summary"] == {
        "total_cases": 5,
        "passed_cases": 5,
        "failed_cases": 0,
        "recall_at_k": 100.0,
        "mrr": 100.0,
        "ndcg": 100.0,
        "citation_source_match": 100.0,
        "tenant_leak_count": 0,
        "gate_score": 100.0,
        "checks": {
            "recall_at_k": True,
            "mrr": True,
            "ndcg": True,
            "citation_source_match": True,
            "tenant_isolation": True,
            "gate_score": True,
        },
        "threshold_passed": True,
    }
    boundary = report["assurance_boundary"]
    assert boundary["llm_invoked"] is False
    assert boundary["network_required"] is False
    assert boundary["external_embedding_model_invoked"] is False
    assert boundary["production_hybrid_retriever_invoked"] is True
    assert boundary["production_retrieval_tool_invoked"] is True
    assert boundary["answer_quality_claimed"] is False
    assert boundary["citation_faithfulness_claimed"] is False


def test_adversarial_store_exposes_foreign_candidates_but_main_chain_leaks_zero():
    dataset = load_retrieval_dataset(DEFAULT_RETRIEVAL_DATASET_PATH)
    model = SeededHashEmbeddingModel(seed=dataset.seed)
    store = AdversarialInMemoryEvaluationStore(dataset.corpus, model)
    query_embedding = model.encode(
        "Project Nebula covenant breach code ZETA confidential evidence"
    )

    raw_candidates = store.similarity_search(
        query_embedding=query_embedding,
        top_k=20,
        tenant_id=7,
    )
    assert "foreign-nebula-zeta" in {
        candidate.chunk_id for candidate in raw_candidates
    }

    report = run_retrieval_evaluation(DEFAULT_RETRIEVAL_DATASET_PATH)
    isolation_case = next(
        result
        for result in report["results"]
        if result["scenario"] == "tenant_isolation_negative"
    )
    assert isolation_case["tenant_isolation"] == {
        "allowed_tenant_ids": [7],
        "leaked_chunk_ids": [],
        "leak_count": 0,
    }
    assert isolation_case["metric_applicability"] == {
        "ranked_retrieval": False,
        "citation_source_match": False,
    }
    assert isolation_case["metrics"]["recall_at_k"] is None
    assert isolation_case["metrics"]["citation_source_match"] is None
    assert 99 not in isolation_case["observed"]["retrieved_tenant_ids"]


def test_report_is_deterministic_and_matches_versioned_contract(tmp_path):
    first = run_retrieval_evaluation(DEFAULT_RETRIEVAL_DATASET_PATH)
    second = run_retrieval_evaluation(DEFAULT_RETRIEVAL_DATASET_PATH)
    assert first == second

    report_path = save_retrieval_report(first, tmp_path / "retrieval-report.json")
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (
            DEFAULT_RETRIEVAL_DATASET_PATH.parent.parent
            / "reports"
            / "retrieval_report.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert persisted == first
    assert persisted["schema_version"] == "1.0"
    assert persisted["report_type"] == "deterministic_rag_retrieval_gate"
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert schema["properties"]["report_type"]["const"] == persisted["report_type"]


def test_cli_writes_report_and_returns_nonzero_when_retrieval_gate_fails(
    tmp_path,
):
    raw_dataset = json.loads(
        DEFAULT_RETRIEVAL_DATASET_PATH.read_text(encoding="utf-8")
    )
    failing_dataset = deepcopy(raw_dataset)
    failing_dataset["dataset_id"] = "retrieval-threshold-failure"
    failing_dataset["cases"][0]["expected_relevant_ids"].append(
        "tesla-q2-2025-margin"
    )
    dataset_path = tmp_path / "failing-retrieval-dataset.json"
    dataset_path.write_text(
        json.dumps(failing_dataset),
        encoding="utf-8",
    )
    report_path = tmp_path / "failed-retrieval-report.json"

    exit_code = main(
        [
            "--dataset",
            str(dataset_path),
            "--report",
            str(report_path),
            "--threshold",
            "100",
        ]
    )

    assert exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["threshold_passed"] is False
    assert report["summary"]["recall_at_k"] < 100.0
    assert report["summary"]["tenant_leak_count"] == 0
