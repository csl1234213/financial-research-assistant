"""Deterministic, network-free retrieval quality gate.

The gate deliberately exercises the production retrieval composition:

``TenantRetrievalToolExecutor -> RetrievalTool -> RuntimeRetrievalAdapter
-> HybridRetriever``.

Only the corpus, embedding double, and embedding store are evaluation
fixtures. The report does not make claims about generated answers, LLM
quality, citation faithfulness, Chroma performance, or production latency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from agent.reasoning_models import Evidence
from core.retrieval_tool_adapter import (
    RetrievalToolExecutionError,
    TenantRetrievalToolExecutor,
)
from evaluation.metrics import ranked_retrieval_metrics
from evaluation.retrieval_dataset import (
    RetrievalCorpusDocument,
    RetrievalDatasetValidationError,
    RetrievalEvaluationCase,
    RetrievalEvaluationDataset,
    load_retrieval_dataset,
)
from retrieval.bm25_retriever import tokenize
from retrieval.hybrid_retriever import HybridRetriever
from storage.embedding_store import EmbeddingStore
from storage.vector_models import SearchResult, VectorDocument

RETRIEVAL_REPORT_SCHEMA_VERSION = "1.0"
RETRIEVAL_EVALUATOR_VERSION = "seeded-hybrid-tool-v1"
DEFAULT_RETRIEVAL_DATASET_PATH = (
    Path(__file__).resolve().parent / "datasets" / "financial_retrieval_v1.json"
)
DEFAULT_EMBEDDING_DIMENSIONS = 512


class _EmbeddingVector(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class SeededHashEmbeddingModel:
    """Small deterministic token-hash embedding with no model downloads."""

    def __init__(
        self,
        *,
        seed: int,
        dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    ) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        if dimensions < 8:
            raise ValueError("embedding dimensions must be at least 8")
        self.seed = seed
        self.dimensions = dimensions

    def encode(
        self,
        text: str,
        *,
        convert_to_tensor: bool = False,
        normalize_embeddings: bool = False,
    ) -> _EmbeddingVector:
        if convert_to_tensor:
            raise ValueError("deterministic retrieval evaluation uses list embeddings")
        del normalize_embeddings

        values = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha256(
                f"{self.seed}:{token}".encode("utf-8")
            ).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            values[index] += 1.0

        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            values = [value / norm for value in values]
        return _EmbeddingVector(values)


class AdversarialInMemoryEvaluationStore(EmbeddingStore):
    """Deterministic store fixture that intentionally returns all tenants.

    Returning cross-tenant candidates is intentional: the production
    ``HybridRetriever`` must apply its explicit tenant filter before evidence
    reaches the governed ``RetrievalTool``. This makes the isolation case a
    regression gate instead of relying solely on a cooperative test store.
    """

    def __init__(
        self,
        documents: Sequence[RetrievalCorpusDocument],
        embedding_model: SeededHashEmbeddingModel,
    ) -> None:
        self._model = embedding_model
        self._documents: dict[str, VectorDocument] = {}
        self.add_documents(
            [
                VectorDocument(
                    document_id=document.document_id,
                    chunk_id=document.chunk_id,
                    company=document.company,
                    content=document.content,
                    embedding=self._model.encode(
                        f"passage: {document.content}"
                    ).tolist(),
                    metadata={
                        **document.metadata,
                        "tenant_id": document.tenant_id,
                        "company": document.company,
                        "source": document.source_filename,
                        "page": document.page,
                    },
                )
                for document in documents
            ]
        )

    def create_collection(self, collection_name: str) -> None:
        del collection_name

    def delete_collection(self, collection_name: str) -> None:
        del collection_name
        self._documents.clear()

    def list_collections(self) -> list[str]:
        return ["deterministic_retrieval_evaluation"]

    def add_documents(self, documents: list[VectorDocument]) -> None:
        for document in documents:
            self._documents[document.chunk_id] = document

    def similarity_search(
        self,
        query_embedding: Sequence[float],
        top_k: int = 5,
        tenant_id: int | None = None,
    ) -> list[SearchResult]:
        # ``tenant_id`` is deliberately not used here. See class docstring.
        del tenant_id
        ranked: list[SearchResult] = []
        for document in self._documents.values():
            score = _cosine_similarity(query_embedding, document.embedding)
            metadata = {
                **document.metadata,
                "score_semantics": "similarity",
                "similarity_score": round(max(score, 0.0), 6),
            }
            ranked.append(
                SearchResult(
                    document_id=document.document_id,
                    chunk_id=document.chunk_id,
                    score=score,
                    content=document.content,
                    metadata=metadata,
                )
            )
        ranked.sort(key=lambda item: (-item.score, item.document_id, item.chunk_id))
        return ranked[:top_k]

    def lexical_corpus(self, tenant_id: int | None = None) -> list[SearchResult]:
        # Cross-tenant candidates also exercise the lexical tenant guard.
        del tenant_id
        return [
            SearchResult(
                document_id=document.document_id,
                chunk_id=document.chunk_id,
                score=0.0,
                content=document.content,
                metadata={
                    **document.metadata,
                    "score_semantics": "similarity",
                },
            )
            for document in sorted(
                self._documents.values(),
                key=lambda item: (item.document_id, item.chunk_id),
            )
        ]

    def delete_document(
        self,
        document_id: str,
        *,
        tenant_id: int,
    ) -> None:
        self._documents = {
            chunk_id: document
            for chunk_id, document in self._documents.items()
            if not (
                document.document_id == document_id
                and document.metadata.get("tenant_id") == tenant_id
            )
        }

    def delete_by_tenant(self, tenant_id: int) -> None:
        self._documents = {
            chunk_id: document
            for chunk_id, document in self._documents.items()
            if document.metadata.get("tenant_id") != tenant_id
        }

    def count(self) -> int:
        return len(self._documents)


def run_retrieval_evaluation(
    dataset_path: str | Path = DEFAULT_RETRIEVAL_DATASET_PATH,
    *,
    threshold: float = 100.0,
) -> dict[str, Any]:
    """Run the seeded production retrieval chain and return a stable report."""

    required_gate_score = _validate_threshold(threshold)
    source_path = Path(dataset_path)
    dataset = load_retrieval_dataset(source_path)
    embedding_model = SeededHashEmbeddingModel(seed=dataset.seed)
    store = AdversarialInMemoryEvaluationStore(dataset.corpus, embedding_model)
    executor = TenantRetrievalToolExecutor(HybridRetriever(embedding_model))
    document_by_chunk = {document.chunk_id: document for document in dataset.corpus}

    results = [
        _evaluate_case(
            case=case,
            dataset=dataset,
            executor=executor,
            store=store,
            document_by_chunk=document_by_chunk,
        )
        for case in dataset.cases
    ]

    averages = {
        metric: _metric_average(results, metric)
        for metric in (
            "recall_at_k",
            "mrr",
            "ndcg",
            "citation_source_match",
        )
    }
    gate_score = round(sum(averages.values()) / len(averages), 1)
    tenant_leak_count = sum(result["tenant_isolation"]["leak_count"] for result in results)
    thresholds = dataset.thresholds
    checks = {
        "recall_at_k": averages["recall_at_k"] >= thresholds.recall_at_k,
        "mrr": averages["mrr"] >= thresholds.mrr,
        "ndcg": averages["ndcg"] >= thresholds.ndcg,
        "citation_source_match": (
            averages["citation_source_match"] >= thresholds.citation_source_match
        ),
        "tenant_isolation": tenant_leak_count <= thresholds.maximum_tenant_leaks,
        "gate_score": gate_score >= required_gate_score,
    }
    threshold_passed = bool(results) and all(checks.values())

    return {
        "schema_version": RETRIEVAL_REPORT_SCHEMA_VERSION,
        "report_type": "deterministic_rag_retrieval_gate",
        "execution_mode": "offline_seeded_deterministic",
        "evaluator_version": RETRIEVAL_EVALUATOR_VERSION,
        "dataset": {
            "id": dataset.dataset_id,
            "schema_version": dataset.schema_version,
            "filename": source_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "seed": dataset.seed,
            "corpus_count": len(dataset.corpus),
            "case_count": len(dataset.cases),
        },
        "assurance_boundary": {
            "llm_invoked": False,
            "network_required": False,
            "external_embedding_model_invoked": False,
            "model_download_required": False,
            "production_hybrid_retriever_invoked": True,
            "production_retrieval_tool_invoked": True,
            "store_backend": "adversarial_in_memory_evaluation_fixture",
            "answer_quality_claimed": False,
            "citation_faithfulness_claimed": False,
            "scored_scope": [
                "labelled_chunk_recall_at_k",
                "labelled_chunk_mrr",
                "labelled_chunk_ndcg",
                "labelled_citation_source_match",
                "tenant_isolation",
            ],
            "unmeasured_scope": [
                "generated_answer_correctness",
                "generated_answer_faithfulness",
                "llm_quality",
                "embedding_model_quality",
                "chroma_integration",
                "production_latency",
            ],
        },
        "thresholds": {
            "dataset": {
                "recall_at_k": thresholds.recall_at_k,
                "mrr": thresholds.mrr,
                "ndcg": thresholds.ndcg,
                "citation_source_match": thresholds.citation_source_match,
                "maximum_tenant_leaks": thresholds.maximum_tenant_leaks,
            },
            "minimum_gate_score": required_gate_score,
        },
        "summary": {
            "total_cases": len(results),
            "passed_cases": sum(1 for result in results if result["passed"]),
            "failed_cases": sum(1 for result in results if not result["passed"]),
            **averages,
            "tenant_leak_count": tenant_leak_count,
            "gate_score": gate_score,
            "checks": checks,
            "threshold_passed": threshold_passed,
        },
        "results": results,
    }


def save_retrieval_report(
    report: dict[str, Any],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the production HybridRetriever and governed RetrievalTool "
            "against a seeded, source-controlled corpus without network or LLM calls."
        )
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_RETRIEVAL_DATASET_PATH,
        help="Path to the versioned deterministic retrieval dataset.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Destination for the versioned JSON evaluation report.",
    )
    parser.add_argument(
        "--threshold",
        type=_threshold_argument,
        default=100.0,
        help="Minimum aggregate retrieval gate score required for exit code 0.",
    )
    args = parser.parse_args(argv)

    try:
        report = run_retrieval_evaluation(
            args.dataset,
            threshold=args.threshold,
        )
        report_path = save_retrieval_report(report, args.report)
    except (
        FileNotFoundError,
        RetrievalDatasetValidationError,
        RetrievalToolExecutionError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ) as exc:
        print(f"retrieval evaluation failed: {exc}", file=sys.stderr)
        return 2

    summary = report["summary"]
    print(
        "retrieval evaluation: "
        f"{summary['passed_cases']}/{summary['total_cases']} cases passed; "
        f"Recall@K={summary['recall_at_k']}; "
        f"MRR={summary['mrr']}; "
        f"nDCG={summary['ndcg']}; "
        f"citation/source={summary['citation_source_match']}; "
        f"tenant_leaks={summary['tenant_leak_count']}; "
        f"gate_score={summary['gate_score']}; "
        f"report={report_path}"
    )
    return 0 if summary["threshold_passed"] else 1


def _evaluate_case(
    *,
    case: RetrievalEvaluationCase,
    dataset: RetrievalEvaluationDataset,
    executor: TenantRetrievalToolExecutor,
    store: EmbeddingStore,
    document_by_chunk: dict[str, RetrievalCorpusDocument],
) -> dict[str, Any]:
    evidence = executor.execute(
        store=store,
        query=case.query,
        tenant_id=case.tenant_id,
        company=case.company,
        document_ids=list(case.document_ids),
        top_k=case.top_k,
        filters=case.filters,
        include_public=case.include_public,
    )
    retrieved_ids = [_evidence_chunk_id(item) for item in evidence]
    retrieved_sources = [item.source for item in evidence]
    ranked = ranked_retrieval_metrics(
        retrieved_ids,
        case.expected_relevant_ids,
        k=case.top_k,
    )
    source_match = _citation_source_match(
        retrieved_sources,
        case.expected_sources,
    )

    allowed_tenants = {case.tenant_id}
    if case.include_public:
        allowed_tenants.add(0)
    retrieved_tenant_ids = [
        document_by_chunk[chunk_id].tenant_id
        for chunk_id in retrieved_ids
        if chunk_id in document_by_chunk
    ]
    leaked_ids = [
        chunk_id
        for chunk_id in retrieved_ids
        if (
            chunk_id in case.forbidden_chunk_ids
            or (
                chunk_id in document_by_chunk
                and document_by_chunk[chunk_id].tenant_id not in allowed_tenants
            )
        )
    ]

    ranking_applicable = bool(case.expected_relevant_ids)
    citation_applicable = bool(case.expected_sources)
    metrics: dict[str, float | None] = {
        "precision_at_k": ranked["precision_at_k"] if ranking_applicable else None,
        "recall_at_k": ranked["recall_at_k"] if ranking_applicable else None,
        "mrr": ranked["mrr"] if ranking_applicable else None,
        "ndcg": ranked["ndcg"] if ranking_applicable else None,
        "citation_source_match": source_match,
    }
    thresholds = dataset.thresholds
    checks = {
        "recall_at_k": (
            not ranking_applicable
            or _required_metric(metrics["recall_at_k"]) >= thresholds.recall_at_k
        ),
        "mrr": (
            not ranking_applicable
            or _required_metric(metrics["mrr"]) >= thresholds.mrr
        ),
        "ndcg": (
            not ranking_applicable
            or _required_metric(metrics["ndcg"]) >= thresholds.ndcg
        ),
        "citation_source_match": (
            not citation_applicable
            or _required_metric(metrics["citation_source_match"])
            >= thresholds.citation_source_match
        ),
        "tenant_isolation": len(leaked_ids) <= thresholds.maximum_tenant_leaks,
    }
    return {
        "id": case.case_id,
        "scenario": case.scenario,
        "query": case.query,
        "tenant_id": case.tenant_id,
        "top_k": case.top_k,
        "expected": {
            "relevant_chunk_ids": list(case.expected_relevant_ids),
            "sources": list(case.expected_sources),
            "forbidden_chunk_ids": list(case.forbidden_chunk_ids),
        },
        "observed": {
            "retrieved_chunk_ids": retrieved_ids,
            "citation_sources": retrieved_sources,
            "retrieved_tenant_ids": retrieved_tenant_ids,
        },
        "metrics": metrics,
        "metric_applicability": {
            "ranked_retrieval": ranking_applicable,
            "citation_source_match": citation_applicable,
        },
        "tenant_isolation": {
            "allowed_tenant_ids": sorted(allowed_tenants),
            "leaked_chunk_ids": leaked_ids,
            "leak_count": len(leaked_ids),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def _evidence_chunk_id(evidence: Evidence) -> str:
    chunk_id = evidence.metadata.get("chunk_id")
    return chunk_id if isinstance(chunk_id, str) else ""


def _citation_source_match(
    retrieved_sources: Sequence[str],
    expected_sources: Sequence[str],
) -> float | None:
    """F1 source-label match for citations attached by RetrievalTool."""

    expected = {source.strip().casefold() for source in expected_sources if source.strip()}
    if not expected:
        # Negative isolation cases have no positive citation target; recording
        # N/A avoids inflating source quality while leakage is scored separately.
        return None

    retrieved = {
        source.strip().casefold()
        for source in retrieved_sources
        if source.strip()
    }
    matched = expected & retrieved
    if not matched:
        return 0.0
    precision = len(matched) / len(retrieved)
    recall = len(matched) / len(expected)
    return round(2 * precision * recall / (precision + recall) * 100, 1)


def _cosine_similarity(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    dot_product = sum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    return dot_product / (left_norm * right_norm)


def _average(values: Iterable[float]) -> float:
    normalized = list(values)
    return round(sum(normalized) / len(normalized), 1) if normalized else 0.0


def _metric_average(
    results: Sequence[dict[str, Any]],
    metric: str,
) -> float:
    values = [
        value
        for result in results
        if isinstance((value := result["metrics"].get(metric)), (int, float))
        and not isinstance(value, bool)
    ]
    return _average(values)


def _required_metric(value: float | None) -> float:
    if value is None:
        raise ValueError("an applicable retrieval metric was not calculated")
    return value


def _threshold_argument(value: str) -> float:
    try:
        return _validate_threshold(float(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _validate_threshold(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be numeric")
    threshold = float(value)
    if not 0.0 <= threshold <= 100.0:
        raise ValueError("threshold must be between 0 and 100")
    return threshold


if __name__ == "__main__":
    raise SystemExit(main())
