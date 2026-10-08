"""Versioned, local-only loading and validation for evaluation datasets.

The loader deliberately has no runtime or provider dependency.  This keeps
golden-data validation deterministic and makes it suitable for unit tests and
offline evaluation runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

GOLDEN_DATASET_SCHEMA_VERSION = "1.0"


class GoldenDatasetValidationError(ValueError):
    """Raised when a golden evaluation dataset violates its local contract."""


@dataclass(frozen=True)
class GoldenDataset:
    """A validated, versioned collection of evaluation cases."""

    schema_version: str
    dataset_id: str
    cases: list[dict[str, Any]]
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    is_legacy_format: bool = False


_LIST_FIELDS = {
    "expected_companies",
    "expected_tools",
    "expected_sources",
    "expected_retrieval_ids",
    "reference_claims",
    "criteria",
}
_STRING_FIELDS = {
    "id",
    "question",
    "expected_intent",
    "expected_task_type",
    "expected_workflow",
    "expected_strategy",
    "reference_answer",
}
_BOOLEAN_FIELDS = {
    "expected_use_retrieval",
    "expected_use_tools",
}


def load_golden_dataset(path: str | Path) -> GoldenDataset:
    """Load a versioned dataset from ``path`` and validate its structure.

    Legacy list-shaped datasets are accepted for backward compatibility, but
    are marked as ``is_legacy_format``.  New datasets must use schema version
    ``1.0`` as documented in ``datasets/golden_dataset.schema.json``.
    """

    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with dataset_path.open("r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    return parse_golden_dataset(raw_data, dataset_id=dataset_path.stem)


def parse_golden_dataset(raw_data: Any, dataset_id: str = "dataset") -> GoldenDataset:
    """Validate a decoded dataset document without performing file I/O."""

    if isinstance(raw_data, list):
        cases = _validate_cases(raw_data)
        return GoldenDataset(
            schema_version="legacy",
            dataset_id=dataset_id,
            cases=cases,
            is_legacy_format=True,
        )

    if not isinstance(raw_data, Mapping):
        raise GoldenDatasetValidationError(
            "Dataset must be a JSON object using the golden schema or a legacy list"
        )

    schema_version = raw_data.get("schema_version")
    if schema_version != GOLDEN_DATASET_SCHEMA_VERSION:
        raise GoldenDatasetValidationError(
            "Unsupported dataset schema_version "
            f"{schema_version!r}; expected {GOLDEN_DATASET_SCHEMA_VERSION!r}"
        )

    declared_dataset_id = raw_data.get("dataset_id", dataset_id)
    if not isinstance(declared_dataset_id, str) or not declared_dataset_id.strip():
        raise GoldenDatasetValidationError("dataset_id must be a non-empty string")

    description = raw_data.get("description", "")
    if not isinstance(description, str):
        raise GoldenDatasetValidationError("description must be a string")

    metadata = raw_data.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise GoldenDatasetValidationError("metadata must be an object")

    cases = _validate_cases(raw_data.get("cases"))
    return GoldenDataset(
        schema_version=schema_version,
        dataset_id=declared_dataset_id.strip(),
        cases=cases,
        description=description,
        metadata=dict(metadata),
    )


def _validate_cases(raw_cases: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
        raise GoldenDatasetValidationError("cases must be a JSON array")

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, Mapping):
            raise GoldenDatasetValidationError(f"cases[{index}] must be an object")

        case = dict(raw_case)
        _validate_case(case, index)
        case_id = case["id"].strip()
        if case_id in seen_ids:
            raise GoldenDatasetValidationError(f"Duplicate case id: {case_id}")
        seen_ids.add(case_id)
        cases.append(case)

    return cases


def _validate_case(case: dict[str, Any], index: int) -> None:
    for field_name in ("id", "question"):
        value = case.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise GoldenDatasetValidationError(
                f"cases[{index}].{field_name} must be a non-empty string"
            )

    for field_name in _STRING_FIELDS - {"id", "question"}:
        if field_name in case and not isinstance(case[field_name], str):
            raise GoldenDatasetValidationError(
                f"cases[{index}].{field_name} must be a string when supplied"
            )

    for field_name in _LIST_FIELDS:
        if field_name not in case:
            continue
        value = case[field_name]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise GoldenDatasetValidationError(
                f"cases[{index}].{field_name} must be an array of strings"
            )

    for field_name in _BOOLEAN_FIELDS:
        if field_name in case and not isinstance(case[field_name], bool):
            raise GoldenDatasetValidationError(
                f"cases[{index}].{field_name} must be a boolean when supplied"
            )

    if "metadata" in case and not isinstance(case["metadata"], Mapping):
        raise GoldenDatasetValidationError(
            f"cases[{index}].metadata must be an object when supplied"
        )
