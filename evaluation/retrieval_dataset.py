"""Versioned dataset contract for deterministic RAG retrieval evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RETRIEVAL_DATASET_SCHEMA_VERSION = "1.0"


class RetrievalDatasetValidationError(ValueError):
    """Raised when a retrieval evaluation dataset violates its contract."""


@dataclass(frozen=True, slots=True)
class RetrievalCorpusDocument:
    document_id: str
    chunk_id: str
    tenant_id: int
    company: str
    source_filename: str
    page: int | str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationCase:
    case_id: str
    query: str
    tenant_id: int
    top_k: int
    expected_relevant_ids: tuple[str, ...]
    expected_sources: tuple[str, ...]
    company: str | None = None
    document_ids: tuple[str, ...] = ()
    filters: dict[str, str] = field(default_factory=dict)
    include_public: bool = False
    forbidden_chunk_ids: tuple[str, ...] = ()
    scenario: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalGateThresholds:
    recall_at_k: float
    mrr: float
    ndcg: float
    citation_source_match: float
    maximum_tenant_leaks: int


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationDataset:
    schema_version: str
    dataset_id: str
    seed: int
    description: str
    thresholds: RetrievalGateThresholds
    corpus: tuple[RetrievalCorpusDocument, ...]
    cases: tuple[RetrievalEvaluationCase, ...]


def load_retrieval_dataset(path: str | Path) -> RetrievalEvaluationDataset:
    """Load and validate a source-controlled retrieval evaluation dataset."""

    source_path = Path(path)
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RetrievalDatasetValidationError("dataset root must be an object")

    schema_version = _required_string(raw, "schema_version", "dataset")
    if schema_version != RETRIEVAL_DATASET_SCHEMA_VERSION:
        raise RetrievalDatasetValidationError(
            "unsupported retrieval dataset schema_version "
            f"{schema_version!r}; expected {RETRIEVAL_DATASET_SCHEMA_VERSION!r}"
        )

    dataset_id = _required_string(raw, "dataset_id", "dataset")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise RetrievalDatasetValidationError("dataset.description must be a string")

    seed = raw.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise RetrievalDatasetValidationError("dataset.seed must be a non-negative integer")

    thresholds = _parse_thresholds(raw.get("thresholds"))
    corpus = _parse_corpus(raw.get("corpus"))
    cases = _parse_cases(raw.get("cases"))
    _validate_references(corpus, cases)

    return RetrievalEvaluationDataset(
        schema_version=schema_version,
        dataset_id=dataset_id,
        seed=seed,
        description=description,
        thresholds=thresholds,
        corpus=corpus,
        cases=cases,
    )


def _parse_thresholds(value: Any) -> RetrievalGateThresholds:
    if not isinstance(value, dict):
        raise RetrievalDatasetValidationError("dataset.thresholds must be an object")
    return RetrievalGateThresholds(
        recall_at_k=_percentage(value, "recall_at_k"),
        mrr=_percentage(value, "mrr"),
        ndcg=_percentage(value, "ndcg"),
        citation_source_match=_percentage(value, "citation_source_match"),
        maximum_tenant_leaks=_non_negative_integer(value, "maximum_tenant_leaks"),
    )


def _parse_corpus(value: Any) -> tuple[RetrievalCorpusDocument, ...]:
    if not isinstance(value, list) or not value:
        raise RetrievalDatasetValidationError("dataset.corpus must be a non-empty array")

    documents: list[RetrievalCorpusDocument] = []
    seen_chunks: set[str] = set()
    for index, item in enumerate(value):
        location = f"corpus[{index}]"
        if not isinstance(item, dict):
            raise RetrievalDatasetValidationError(f"{location} must be an object")

        chunk_id = _required_string(item, "chunk_id", location)
        if chunk_id in seen_chunks:
            raise RetrievalDatasetValidationError(f"duplicate corpus chunk_id: {chunk_id}")
        seen_chunks.add(chunk_id)

        tenant_id = _non_negative_integer(item, "tenant_id", location)
        page = item.get("page")
        if isinstance(page, bool) or not isinstance(page, (int, str)):
            raise RetrievalDatasetValidationError(
                f"{location}.page must be an integer or string"
            )

        documents.append(
            RetrievalCorpusDocument(
                document_id=_required_string(item, "document_id", location),
                chunk_id=chunk_id,
                tenant_id=tenant_id,
                company=_required_string(item, "company", location),
                source_filename=_required_string(item, "source_filename", location),
                page=page,
                content=_required_string(item, "content", location),
                metadata=_string_mapping(item.get("metadata", {}), f"{location}.metadata"),
            )
        )
    return tuple(documents)


def _parse_cases(value: Any) -> tuple[RetrievalEvaluationCase, ...]:
    if not isinstance(value, list) or not value:
        raise RetrievalDatasetValidationError("dataset.cases must be a non-empty array")

    cases: list[RetrievalEvaluationCase] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        location = f"cases[{index}]"
        if not isinstance(item, dict):
            raise RetrievalDatasetValidationError(f"{location} must be an object")

        case_id = _required_string(item, "id", location)
        if case_id in seen_ids:
            raise RetrievalDatasetValidationError(f"duplicate evaluation case id: {case_id}")
        seen_ids.add(case_id)

        top_k = _positive_integer(item, "top_k", location)
        if top_k > 20:
            raise RetrievalDatasetValidationError(
                f"{location}.top_k must not exceed the RetrievalTool limit of 20"
            )
        include_public = item.get("include_public", False)
        if not isinstance(include_public, bool):
            raise RetrievalDatasetValidationError(
                f"{location}.include_public must be a boolean"
            )
        company = item.get("company")
        if company is not None and (not isinstance(company, str) or not company.strip()):
            raise RetrievalDatasetValidationError(
                f"{location}.company must be a non-empty string when provided"
            )
        scenario = item.get("scenario")
        if scenario is not None and (not isinstance(scenario, str) or not scenario.strip()):
            raise RetrievalDatasetValidationError(
                f"{location}.scenario must be a non-empty string when provided"
            )

        cases.append(
            RetrievalEvaluationCase(
                case_id=case_id,
                query=_required_string(item, "query", location),
                tenant_id=_non_negative_integer(item, "tenant_id", location),
                top_k=top_k,
                expected_relevant_ids=_string_sequence(
                    item.get("expected_relevant_ids"),
                    f"{location}.expected_relevant_ids",
                ),
                expected_sources=_string_sequence(
                    item.get("expected_sources"),
                    f"{location}.expected_sources",
                ),
                company=company.strip() if isinstance(company, str) else None,
                document_ids=_string_sequence(
                    item.get("document_ids", []),
                    f"{location}.document_ids",
                ),
                filters=_string_mapping(item.get("filters", {}), f"{location}.filters"),
                include_public=include_public,
                forbidden_chunk_ids=_string_sequence(
                    item.get("forbidden_chunk_ids", []),
                    f"{location}.forbidden_chunk_ids",
                ),
                scenario=scenario.strip() if isinstance(scenario, str) else None,
            )
        )
    return tuple(cases)


def _validate_references(
    corpus: tuple[RetrievalCorpusDocument, ...],
    cases: tuple[RetrievalEvaluationCase, ...],
) -> None:
    chunk_ids = {document.chunk_id for document in corpus}
    document_ids = {document.document_id for document in corpus}
    sources = {document.source_filename.casefold() for document in corpus}

    for case in cases:
        unknown_relevant = set(case.expected_relevant_ids) - chunk_ids
        if unknown_relevant:
            raise RetrievalDatasetValidationError(
                f"case {case.case_id!r} references unknown relevant chunks: "
                f"{sorted(unknown_relevant)}"
            )
        unknown_forbidden = set(case.forbidden_chunk_ids) - chunk_ids
        if unknown_forbidden:
            raise RetrievalDatasetValidationError(
                f"case {case.case_id!r} references unknown forbidden chunks: "
                f"{sorted(unknown_forbidden)}"
            )
        unknown_documents = set(case.document_ids) - document_ids
        if unknown_documents:
            raise RetrievalDatasetValidationError(
                f"case {case.case_id!r} references unknown document_ids: "
                f"{sorted(unknown_documents)}"
            )
        unknown_sources = {
            source for source in case.expected_sources if source.casefold() not in sources
        }
        if unknown_sources:
            raise RetrievalDatasetValidationError(
                f"case {case.case_id!r} references unknown sources: "
                f"{sorted(unknown_sources)}"
            )


def _required_string(value: dict[str, Any], key: str, location: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise RetrievalDatasetValidationError(
            f"{location}.{key} must be a non-empty string"
        )
    return item.strip()


def _string_sequence(value: Any, location: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RetrievalDatasetValidationError(f"{location} must be an array")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RetrievalDatasetValidationError(
                f"{location} must contain non-empty strings"
            )
        normalized.append(item.strip())
    if len(normalized) != len(set(normalized)):
        raise RetrievalDatasetValidationError(f"{location} must not contain duplicates")
    return tuple(normalized)


def _string_mapping(value: Any, location: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RetrievalDatasetValidationError(f"{location} must be an object")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise RetrievalDatasetValidationError(
                f"{location} keys must be non-empty strings"
            )
        if not isinstance(item, str):
            raise RetrievalDatasetValidationError(
                f"{location}.{key} must be a string"
            )
        normalized[key.strip()] = item
    return normalized


def _percentage(value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, (int, float)):
        raise RetrievalDatasetValidationError(
            f"dataset.thresholds.{key} must be numeric"
        )
    percentage = float(item)
    if not 0.0 <= percentage <= 100.0:
        raise RetrievalDatasetValidationError(
            f"dataset.thresholds.{key} must be between 0 and 100"
        )
    return percentage


def _positive_integer(value: dict[str, Any], key: str, location: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 1:
        raise RetrievalDatasetValidationError(
            f"{location}.{key} must be a positive integer"
        )
    return item


def _non_negative_integer(
    value: dict[str, Any],
    key: str,
    location: str = "dataset.thresholds",
) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise RetrievalDatasetValidationError(
            f"{location}.{key} must be a non-negative integer"
        )
    return item
