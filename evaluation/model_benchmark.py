"""Reproducible, provider-agnostic model benchmark protocol.

The benchmark is deliberately offline by default.  Passing a provider alone
does not call it; an operator must opt in with ``execute_provider=True``.  This
keeps contract tests deterministic and prevents hidden network/model costs in
CI while retaining one auditable code path for live model comparisons.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

MODEL_BENCHMARK_SCHEMA_VERSION = "1.0"
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_SAFE_ERROR_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "[redacted-api-key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"), "[redacted-token]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~-]{8,}"), r"\1[redacted-token]"),
    (
        re.compile(r"(?i)((?:api[_-]?key|secret|password|token)\s*[:=]\s*)\S+"),
        r"\1[redacted]",
    ),
)


class ModelBenchmarkValidationError(ValueError):
    """Raised when an on-disk benchmark protocol violates its contract."""


class ModelBenchmarkExecutionError(RuntimeError):
    """Raised when a live execution is requested without a callable provider."""


ProviderCallable = Callable[[str], str | Mapping[str, Any]]
QualityScorer = Callable[["BenchmarkCase", str], float]


@dataclass(frozen=True)
class BenchmarkCase:
    """A single fixed prompt and deterministic quality expectation."""

    id: str
    prompt: str
    expected_terms: tuple[str, ...] = ()
    reference_answer: str | None = None
    prompt_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "case.id")
        _validate_text(self.prompt, "case.prompt", max_length=32_000)
        if self.reference_answer is not None:
            _validate_text(self.reference_answer, "case.reference_answer", max_length=32_000)
        if self.prompt_version is not None:
            _validate_short_text(self.prompt_version, "case.prompt_version")
        if not all(isinstance(term, str) and term.strip() for term in self.expected_terms):
            raise ModelBenchmarkValidationError("case.expected_terms must contain non-empty strings")
        if not isinstance(self.metadata, Mapping):
            raise ModelBenchmarkValidationError("case.metadata must be an object")


@dataclass(frozen=True)
class BenchmarkProtocol:
    """A versioned, source-controlled benchmark contract for one model route."""

    protocol_id: str
    model_id: str
    prompt_version: str
    cases: tuple[BenchmarkCase, ...]
    schema_version: str = MODEL_BENCHMARK_SCHEMA_VERSION
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_BENCHMARK_SCHEMA_VERSION:
            raise ModelBenchmarkValidationError(
                f"Unsupported schema_version {self.schema_version!r}; "
                f"expected {MODEL_BENCHMARK_SCHEMA_VERSION!r}"
            )
        _validate_identifier(self.protocol_id, "protocol_id")
        _validate_short_text(self.model_id, "model_id")
        _validate_short_text(self.prompt_version, "prompt_version")
        _validate_text(self.description, "description", max_length=16_000, allow_empty=True)
        if not self.cases:
            raise ModelBenchmarkValidationError("protocol must contain at least one case")
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ModelBenchmarkValidationError("protocol case ids must be unique")
        if not isinstance(self.metadata, Mapping):
            raise ModelBenchmarkValidationError("protocol.metadata must be an object")


@dataclass(frozen=True)
class BenchmarkCaseResult:
    """A case-level outcome with reproducibility and privacy-oriented fields."""

    case_id: str
    model_id: str
    prompt_version: str
    execution_mode: str
    latency_ms: float | None
    quality_score: float | None
    error: str | None
    response_sha256: str | None
    response_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelBenchmarkReport:
    """An immutable benchmark report; offline reports omit non-deterministic time."""

    protocol_id: str
    model_id: str
    prompt_version: str
    schema_version: str
    execution_mode: str
    results: tuple[BenchmarkCaseResult, ...]
    generated_at: str | None

    @property
    def summary(self) -> dict[str, Any]:
        scored = [result.quality_score for result in self.results if result.quality_score is not None]
        latencies = [result.latency_ms for result in self.results if result.latency_ms is not None]
        return {
            "total_cases": len(self.results),
            "successful_cases": sum(
                1
                for result in self.results
                if result.error is None and result.quality_score is not None
            ),
            "failed_cases": sum(1 for result in self.results if result.error is not None),
            "average_quality_score": round(sum(scored) / len(scored), 2) if scored else None,
            "average_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_id": self.protocol_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "execution_mode": self.execution_mode,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "results": [result.to_dict() for result in self.results],
        }


def load_benchmark_protocol(path: str | Path) -> BenchmarkProtocol:
    """Load a versioned JSON benchmark protocol without contacting a provider."""

    protocol_path = Path(path)
    if not protocol_path.exists():
        raise FileNotFoundError(f"Benchmark protocol not found: {protocol_path}")
    with protocol_path.open("r", encoding="utf-8") as handle:
        return parse_benchmark_protocol(json.load(handle))


def parse_benchmark_protocol(raw_data: Any) -> BenchmarkProtocol:
    """Parse a decoded protocol document into its immutable data model."""

    if not isinstance(raw_data, Mapping):
        raise ModelBenchmarkValidationError("Benchmark protocol must be a JSON object")
    allowed_top_level = {
        "schema_version",
        "protocol_id",
        "model_id",
        "prompt_version",
        "description",
        "metadata",
        "cases",
    }
    _reject_unknown_fields(raw_data, allowed_top_level, "protocol")

    raw_cases = raw_data.get("cases")
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
        raise ModelBenchmarkValidationError("protocol.cases must be an array")
    cases = tuple(_parse_case(raw_case, index) for index, raw_case in enumerate(raw_cases))
    return BenchmarkProtocol(
        schema_version=raw_data.get("schema_version", ""),
        protocol_id=raw_data.get("protocol_id", ""),
        model_id=raw_data.get("model_id", ""),
        prompt_version=raw_data.get("prompt_version", ""),
        description=raw_data.get("description", ""),
        metadata=_parse_metadata(raw_data.get("metadata", {}), "protocol.metadata"),
        cases=cases,
    )


def run_model_benchmark(
    protocol: BenchmarkProtocol,
    provider: ProviderCallable | None = None,
    *,
    execute_provider: bool = False,
    capture_response_text: bool = False,
    quality_scorer: QualityScorer | None = None,
    clock: Callable[[], float] = perf_counter,
) -> ModelBenchmarkReport:
    """Run an offline contract report or an explicitly opted-in provider test.

    The default mode is deterministic and never invokes ``provider``.  A live
    run requires both a callable provider and ``execute_provider=True``.
    ``capture_response_text`` is false by default to avoid persisting model
    output accidentally; a SHA-256 digest is always available for audit.
    """

    if execute_provider and provider is None:
        raise ModelBenchmarkExecutionError(
            "execute_provider=True requires an explicit provider callable"
        )
    if provider is not None and not callable(provider):
        raise ModelBenchmarkExecutionError("provider must be callable")

    if not execute_provider:
        results = tuple(
            BenchmarkCaseResult(
                case_id=case.id,
                model_id=protocol.model_id,
                prompt_version=case.prompt_version or protocol.prompt_version,
                execution_mode="offline",
                latency_ms=None,
                quality_score=None,
                error=None,
                response_sha256=None,
            )
            for case in protocol.cases
        )
        return ModelBenchmarkReport(
            protocol_id=protocol.protocol_id,
            model_id=protocol.model_id,
            prompt_version=protocol.prompt_version,
            schema_version=protocol.schema_version,
            execution_mode="offline",
            results=results,
            generated_at=None,
        )

    scorer = quality_scorer or lexical_quality_score
    results = tuple(
        _run_live_case(
            protocol,
            case,
            provider,
            scorer,
            capture_response_text=capture_response_text,
            clock=clock,
        )
        for case in protocol.cases
    )
    return ModelBenchmarkReport(
        protocol_id=protocol.protocol_id,
        model_id=protocol.model_id,
        prompt_version=protocol.prompt_version,
        schema_version=protocol.schema_version,
        execution_mode="live",
        results=results,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def lexical_quality_score(case: BenchmarkCase, response: str) -> float:
    """A deterministic lexical baseline, not a substitute for human review.

    Explicit expected terms are scored by coverage.  Otherwise reference-answer
    token overlap is used.  It is intentionally simple so model comparisons
    can be reproduced without a judge model or network call.
    """

    normalised_response = _normalise(response)
    if case.expected_terms:
        matched = sum(1 for term in case.expected_terms if _normalise(term) in normalised_response)
        return round(100 * matched / len(case.expected_terms), 2)
    if case.reference_answer:
        expected_tokens = set(_normalise(case.reference_answer).split())
        actual_tokens = set(normalised_response.split())
        if not expected_tokens:
            return 100.0
        return round(100 * len(expected_tokens & actual_tokens) / len(expected_tokens), 2)
    return 100.0 if response.strip() else 0.0


def save_benchmark_report(report: ModelBenchmarkReport, path: str | Path) -> Path:
    """Persist an explicit report to a caller-selected path as JSON."""

    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
    return report_path


def _run_live_case(
    protocol: BenchmarkProtocol,
    case: BenchmarkCase,
    provider: ProviderCallable | None,
    scorer: QualityScorer,
    *,
    capture_response_text: bool,
    clock: Callable[[], float],
) -> BenchmarkCaseResult:
    assert provider is not None  # guarded at the public entry point
    started_at = clock()
    prompt_version = case.prompt_version or protocol.prompt_version
    try:
        raw_response = provider(case.prompt)
        response, provider_model_id = _extract_provider_response(raw_response)
        elapsed_ms = round((clock() - started_at) * 1000, 3)
        quality = _validate_quality_score(scorer(case, response))
        return BenchmarkCaseResult(
            case_id=case.id,
            model_id=provider_model_id or protocol.model_id,
            prompt_version=prompt_version,
            execution_mode="live",
            latency_ms=elapsed_ms,
            quality_score=quality,
            error=None,
            response_sha256=_response_digest(response),
            response_text=response if capture_response_text else None,
        )
    except Exception as exc:  # provider failures must be measured, not hidden
        elapsed_ms = round((clock() - started_at) * 1000, 3)
        return BenchmarkCaseResult(
            case_id=case.id,
            model_id=protocol.model_id,
            prompt_version=prompt_version,
            execution_mode="live",
            latency_ms=elapsed_ms,
            quality_score=None,
            error=_safe_error(exc),
            response_sha256=None,
            response_text=None,
        )


def _extract_provider_response(raw_response: str | Mapping[str, Any]) -> tuple[str, str | None]:
    if isinstance(raw_response, str):
        return raw_response, None
    if not isinstance(raw_response, Mapping):
        raise TypeError("Provider must return a response string or mapping")
    response = raw_response.get("text", raw_response.get("answer"))
    if not isinstance(response, str):
        raise TypeError("Provider response mapping must include string 'text' or 'answer'")
    model_id = raw_response.get("model_id")
    if model_id is not None and not isinstance(model_id, str):
        raise TypeError("Provider response model_id must be a string when supplied")
    return response, model_id


def _parse_case(raw_case: Any, index: int) -> BenchmarkCase:
    path = f"protocol.cases[{index}]"
    if not isinstance(raw_case, Mapping):
        raise ModelBenchmarkValidationError(f"{path} must be an object")
    allowed_fields = {"id", "prompt", "expected_terms", "reference_answer", "prompt_version", "metadata"}
    _reject_unknown_fields(raw_case, allowed_fields, path)
    expected_terms = raw_case.get("expected_terms", [])
    if not isinstance(expected_terms, list) or not all(isinstance(term, str) for term in expected_terms):
        raise ModelBenchmarkValidationError(f"{path}.expected_terms must be an array of strings")
    reference_answer = raw_case.get("reference_answer")
    if reference_answer is not None and not isinstance(reference_answer, str):
        raise ModelBenchmarkValidationError(f"{path}.reference_answer must be a string when supplied")
    prompt_version = raw_case.get("prompt_version")
    if prompt_version is not None and not isinstance(prompt_version, str):
        raise ModelBenchmarkValidationError(f"{path}.prompt_version must be a string when supplied")
    return BenchmarkCase(
        id=raw_case.get("id", ""),
        prompt=raw_case.get("prompt", ""),
        expected_terms=tuple(expected_terms),
        reference_answer=reference_answer,
        prompt_version=prompt_version,
        metadata=_parse_metadata(raw_case.get("metadata", {}), f"{path}.metadata"),
    )


def _parse_metadata(raw_metadata: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw_metadata, Mapping):
        raise ModelBenchmarkValidationError(f"{path} must be an object")
    if not all(isinstance(key, str) and key for key in raw_metadata):
        raise ModelBenchmarkValidationError(f"{path} keys must be non-empty strings")
    return dict(raw_metadata)


def _validate_identifier(value: Any, path: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value.strip()):
        raise ModelBenchmarkValidationError(f"{path} must match {_IDENTIFIER_PATTERN.pattern!r}")


def _validate_short_text(value: Any, path: str) -> None:
    _validate_text(value, path, max_length=256)


def _validate_text(value: Any, path: str, *, max_length: int, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ModelBenchmarkValidationError(f"{path} must be a non-empty string")
    if len(value) > max_length:
        raise ModelBenchmarkValidationError(f"{path} exceeds {max_length} characters")


def _reject_unknown_fields(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ModelBenchmarkValidationError(f"{path} contains unsupported fields: {', '.join(unknown)}")


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _response_digest(response: str) -> str:
    return hashlib.sha256(response.encode("utf-8")).hexdigest()


def _validate_quality_score(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError("quality scorer must return a numeric value")
    if not 0 <= value <= 100:
        raise ValueError("quality scorer must return a value between 0 and 100")
    return round(float(value), 2)


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()[:400]
    for pattern, replacement in _SAFE_ERROR_REPLACEMENTS:
        message = pattern.sub(replacement, message)
    return type(exc).__name__ if not message else f"{type(exc).__name__}: {message}"
