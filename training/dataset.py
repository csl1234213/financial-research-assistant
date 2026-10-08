"""Strict, local validation for supervised fine-tuning data.

The online Financial Agent Runtime must never consume this data directly.
This module is intentionally standard-library only, which lets CI validate the
training corpus without installing GPU, model, or provider dependencies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

SUPERVISED_DATASET_SCHEMA_VERSION = "1.0"

_ALLOWED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "dataset_id",
    "description",
    "license",
    "metadata",
    "records",
}
_ALLOWED_RECORD_FIELDS = {"id", "messages", "metadata"}
_ALLOWED_MESSAGE_FIELDS = {"role", "content"}
_ALLOWED_ROLES = ("system", "user", "assistant")
_ALLOWED_SPLITS = {"train", "validation", "test"}
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_US_SSN_PATTERN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CN_ID_PATTERN = re.compile(r"(?<![0-9A-Za-z])[1-9]\d{16}[\dXx](?![0-9A-Za-z])")
_CN_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_INTERNATIONAL_PHONE_PATTERN = re.compile(r"(?<!\w)\+\d{1,3}[ .-]?\d{3,4}[ .-]?\d{3,4}[ .-]?\d{3,4}(?!\w)")
_CARD_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("cloud access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    (
        "credential assignment",
        re.compile(
            r"\b(?:api[_-]?key|secret|password|access[_-]?token|auth[_-]?token)\b"
            r"\s*[:=]\s*[^\s<][^\s]{5,}",
            re.IGNORECASE,
        ),
    ),
    ("authorization header", re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{12,}\b", re.IGNORECASE)),
)


class TrainingDatasetValidationError(ValueError):
    """Raised when supervised data is malformed or contains sensitive data."""


@dataclass(frozen=True)
class TrainingMessage:
    """One safe, role-labelled instruction-tuning message."""

    role: str
    content: str


@dataclass(frozen=True)
class TrainingExample:
    """A validated conversation that terminates in an assistant target."""

    id: str
    messages: tuple[TrainingMessage, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def target(self) -> str:
        """Return the final assistant response used as the SFT target."""

        return self.messages[-1].content

    def format_for_causal_lm(self) -> str:
        """Use a transparent, model-agnostic chat serialization.

        Model-specific chat templates may be applied by a future training job,
        but this deterministic fallback keeps the corpus inspectable.
        """

        return "\n\n".join(
            f"<|{message.role}|>\n{message.content}" for message in self.messages
        ) + "\n<|end|>"


@dataclass(frozen=True)
class SupervisedDataset:
    """A versioned supervised training corpus, validated before any training."""

    schema_version: str
    dataset_id: str
    records: tuple[TrainingExample, ...]
    description: str = ""
    license: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def split(self, name: str) -> tuple[TrainingExample, ...]:
        """Return records explicitly assigned to a named split."""

        return tuple(record for record in self.records if record.metadata.get("split") == name)


def load_supervised_dataset(path: str | Path) -> SupervisedDataset:
    """Load and validate a source-controlled JSON supervised dataset."""

    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Training dataset not found: {dataset_path}")

    with dataset_path.open("r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    return parse_supervised_dataset(raw_data, dataset_id_hint=dataset_path.stem)


def parse_supervised_dataset(raw_data: Any, dataset_id_hint: str = "dataset") -> SupervisedDataset:
    """Validate a decoded dataset document without performing file I/O."""

    if not isinstance(raw_data, Mapping):
        raise TrainingDatasetValidationError("Training dataset must be a JSON object")

    _reject_unknown_fields(raw_data, _ALLOWED_TOP_LEVEL_FIELDS, "dataset")
    schema_version = raw_data.get("schema_version")
    if schema_version != SUPERVISED_DATASET_SCHEMA_VERSION:
        raise TrainingDatasetValidationError(
            "Unsupported training dataset schema_version "
            f"{schema_version!r}; expected {SUPERVISED_DATASET_SCHEMA_VERSION!r}"
        )

    dataset_id = _require_identifier(raw_data.get("dataset_id", dataset_id_hint), "dataset_id")
    description = _optional_text(raw_data.get("description", ""), "description")
    license_name = _optional_text(raw_data.get("license", ""), "license")
    metadata = _validate_metadata(raw_data.get("metadata", {}), "metadata")

    raw_records = raw_data.get("records")
    if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
        raise TrainingDatasetValidationError("records must be a JSON array")
    if not raw_records:
        raise TrainingDatasetValidationError("records must contain at least one example")
    if len(raw_records) > 100_000:
        raise TrainingDatasetValidationError("records exceeds the supported maximum of 100000")

    records: list[TrainingExample] = []
    seen_ids: set[str] = set()
    for index, raw_record in enumerate(raw_records):
        record = _parse_record(raw_record, index)
        if record.id in seen_ids:
            raise TrainingDatasetValidationError(f"Duplicate record id: {record.id}")
        seen_ids.add(record.id)
        records.append(record)

    _scan_sensitive_text(description, "description")
    _scan_sensitive_text(license_name, "license")
    _scan_metadata_for_sensitive_values(metadata, "metadata")

    return SupervisedDataset(
        schema_version=schema_version,
        dataset_id=dataset_id,
        records=tuple(records),
        description=description,
        license=license_name,
        metadata=metadata,
    )


def _parse_record(raw_record: Any, index: int) -> TrainingExample:
    path = f"records[{index}]"
    if not isinstance(raw_record, Mapping):
        raise TrainingDatasetValidationError(f"{path} must be an object")
    _reject_unknown_fields(raw_record, _ALLOWED_RECORD_FIELDS, path)

    record_id = _require_identifier(raw_record.get("id"), f"{path}.id")
    metadata = _validate_metadata(raw_record.get("metadata", {}), f"{path}.metadata")
    split = metadata.get("split", "train")
    if split not in _ALLOWED_SPLITS:
        raise TrainingDatasetValidationError(
            f"{path}.metadata.split must be one of {sorted(_ALLOWED_SPLITS)}"
        )

    raw_messages = raw_record.get("messages")
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes)):
        raise TrainingDatasetValidationError(f"{path}.messages must be an array")
    if not 2 <= len(raw_messages) <= 32:
        raise TrainingDatasetValidationError(f"{path}.messages must contain between 2 and 32 messages")

    messages: list[TrainingMessage] = []
    for message_index, raw_message in enumerate(raw_messages):
        message_path = f"{path}.messages[{message_index}]"
        if not isinstance(raw_message, Mapping):
            raise TrainingDatasetValidationError(f"{message_path} must be an object")
        _reject_unknown_fields(raw_message, _ALLOWED_MESSAGE_FIELDS, message_path)
        role = raw_message.get("role")
        if role not in _ALLOWED_ROLES:
            raise TrainingDatasetValidationError(
                f"{message_path}.role must be one of {list(_ALLOWED_ROLES)}"
            )
        content = raw_message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise TrainingDatasetValidationError(f"{message_path}.content must be a non-empty string")
        if len(content) > 16_000:
            raise TrainingDatasetValidationError(f"{message_path}.content exceeds 16000 characters")
        _scan_sensitive_text(content, message_path)
        messages.append(TrainingMessage(role=role, content=content))

    _validate_conversation_shape(messages, path)
    _scan_metadata_for_sensitive_values(metadata, f"{path}.metadata")
    return TrainingExample(id=record_id, messages=tuple(messages), metadata=metadata)


def _validate_conversation_shape(messages: Sequence[TrainingMessage], path: str) -> None:
    first_non_system = 1 if messages[0].role == "system" else 0
    if any(message.role == "system" for message in messages[first_non_system:]):
        raise TrainingDatasetValidationError(f"{path}.messages may contain a system message only at position 0")
    if len(messages) - first_non_system < 2:
        raise TrainingDatasetValidationError(f"{path}.messages must include a user request and assistant target")

    expected_role = "user"
    for message in messages[first_non_system:]:
        if message.role != expected_role:
            raise TrainingDatasetValidationError(
                f"{path}.messages must alternate user and assistant messages and end with assistant"
            )
        expected_role = "assistant" if expected_role == "user" else "user"

    if messages[-1].role != "assistant":
        raise TrainingDatasetValidationError(f"{path}.messages must end with an assistant target")


def _require_identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value.strip()):
        raise TrainingDatasetValidationError(
            f"{path} must match {_IDENTIFIER_PATTERN.pattern!r}"
        )
    return value.strip()


def _optional_text(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise TrainingDatasetValidationError(f"{path} must be a string")
    if len(value) > 16_000:
        raise TrainingDatasetValidationError(f"{path} exceeds 16000 characters")
    return value


def _validate_metadata(raw_metadata: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw_metadata, Mapping):
        raise TrainingDatasetValidationError(f"{path} must be an object")

    metadata: dict[str, Any] = {}
    for key, value in raw_metadata.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise TrainingDatasetValidationError(f"{path} keys must be non-empty strings up to 64 characters")
        metadata[key] = _validate_json_scalar_or_string_list(value, f"{path}.{key}")
    return metadata


def _validate_json_scalar_or_string_list(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 4_000:
            raise TrainingDatasetValidationError(f"{path} exceeds 4000 characters")
        return value
    if isinstance(value, list) and all(isinstance(item, str) and len(item) <= 1_000 for item in value):
        return list(value)
    raise TrainingDatasetValidationError(
        f"{path} must be a JSON scalar or an array of short strings"
    )


def _reject_unknown_fields(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TrainingDatasetValidationError(f"{path} contains unsupported fields: {', '.join(unknown)}")


def _scan_metadata_for_sensitive_values(metadata: Mapping[str, Any], path: str) -> None:
    for key, value in metadata.items():
        value_path = f"{path}.{key}"
        if isinstance(value, str):
            _scan_sensitive_text(value, value_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                _scan_sensitive_text(item, f"{value_path}[{index}]")


def _scan_sensitive_text(value: str, path: str) -> None:
    if not value:
        return
    for label, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(value):
            raise TrainingDatasetValidationError(
                f"{path} contains prohibited {label}; redact it before training"
            )
    if _EMAIL_PATTERN.search(value):
        raise TrainingDatasetValidationError(f"{path} contains an email address; redact it before training")
    if _US_SSN_PATTERN.search(value) or _CN_ID_PATTERN.search(value):
        raise TrainingDatasetValidationError(
            f"{path} contains a government identifier; redact it before training"
        )
    if _CN_PHONE_PATTERN.search(value) or _INTERNATIONAL_PHONE_PATTERN.search(value):
        raise TrainingDatasetValidationError(f"{path} contains a phone number; redact it before training")
    if any(_passes_luhn(_digits(candidate)) for candidate in _CARD_CANDIDATE_PATTERN.findall(value)):
        raise TrainingDatasetValidationError(f"{path} contains a payment card number; redact it before training")


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _passes_luhn(value: str) -> bool:
    if not 13 <= len(value) <= 19:
        return False
    checksum = 0
    for index, digit in enumerate(reversed(value)):
        number = int(digit)
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        checksum += number
    return checksum % 10 == 0
