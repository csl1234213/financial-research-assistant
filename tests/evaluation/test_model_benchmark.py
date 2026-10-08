import hashlib

import pytest

from evaluation.model_benchmark import (
    BenchmarkCase,
    BenchmarkProtocol,
    ModelBenchmarkExecutionError,
    ModelBenchmarkValidationError,
    lexical_quality_score,
    load_benchmark_protocol,
    parse_benchmark_protocol,
    run_model_benchmark,
)
from prompt_builder import FINANCIAL_RAG_PROMPT_VERSION

FINANCIAL_RAG_BENCHMARK_VERSION = (
    f"financial-rag-{FINANCIAL_RAG_PROMPT_VERSION}"
)
FROZEN_FINANCIAL_MODEL_BENCHMARK_V1_PROMPT_VERSION = "financial-rag-2.4.0"


def _protocol():
    return BenchmarkProtocol(
        protocol_id="unit-model-benchmark",
        model_id="unit-model-v1",
        prompt_version=FINANCIAL_RAG_BENCHMARK_VERSION,
        cases=(
            BenchmarkCase(
                id="unit-case-001",
                prompt="What should the assistant do?",
                expected_terms=("evidence", "uncertainty"),
            ),
        ),
    )


def test_source_controlled_benchmark_protocol_is_valid():
    protocol = load_benchmark_protocol("evaluation/benchmarks/financial_model_benchmark_v1.json")

    assert protocol.protocol_id == "financial-model-benchmark-v1"
    assert len(protocol.cases) == 3
    # Benchmark v1 is a frozen 2.4.0 protocol. New runtime prompt revisions
    # must not silently rewrite the version recorded by this baseline artifact.
    assert protocol.prompt_version == FROZEN_FINANCIAL_MODEL_BENCHMARK_V1_PROMPT_VERSION


def test_offline_mode_is_deterministic_and_never_invokes_provider():
    def provider(_prompt):
        raise AssertionError("offline benchmark must not call a provider")

    report = run_model_benchmark(_protocol(), provider)

    assert report.execution_mode == "offline"
    assert report.generated_at is None
    assert report.results[0].latency_ms is None
    assert report.results[0].quality_score is None
    assert report.results[0].error is None
    assert report.summary["successful_cases"] == 0


def test_live_mode_requires_explicit_opt_in_and_records_auditable_result():
    with pytest.raises(ModelBenchmarkExecutionError, match="requires an explicit provider"):
        run_model_benchmark(_protocol(), execute_provider=True)

    times = iter((10.0, 10.125))
    report = run_model_benchmark(
        _protocol(),
        lambda _prompt: {"text": "Use evidence and state uncertainty.", "model_id": "served-model-v2"},
        execute_provider=True,
        clock=lambda: next(times),
    )

    result = report.results[0]
    assert report.execution_mode == "live"
    assert result.model_id == "served-model-v2"
    assert result.prompt_version == FINANCIAL_RAG_BENCHMARK_VERSION
    assert result.latency_ms == 125.0
    assert result.quality_score == 100.0
    assert result.response_text is None
    assert result.response_sha256 == hashlib.sha256(
        b"Use evidence and state uncertainty."
    ).hexdigest()


def test_live_mode_captures_sanitized_error_without_failing_the_full_report():
    report = run_model_benchmark(
        _protocol(),
        lambda _prompt: (_ for _ in ()).throw(RuntimeError("token=sk-abcdefghijklmnopqrstuv")),
        execute_provider=True,
        clock=lambda: 4.0,
    )

    result = report.results[0]
    assert result.error.startswith("RuntimeError:")
    assert "sk-" not in result.error
    assert "[redacted" in result.error
    assert result.quality_score is None


def test_protocol_rejects_unknown_fields_and_bad_quality_contracts():
    raw = {
        "schema_version": "1.0",
        "protocol_id": "valid-protocol",
        "model_id": "model",
        "prompt_version": "v1",
        "cases": [{"id": "case-001", "prompt": "Question", "unknown": True}],
    }
    with pytest.raises(ModelBenchmarkValidationError, match="unsupported fields"):
        parse_benchmark_protocol(raw)

    report = run_model_benchmark(
        _protocol(),
        lambda _prompt: "answer",
        execute_provider=True,
        quality_scorer=lambda _case, _answer: 101.0,
    )
    assert "between 0 and 100" in (report.results[0].error or "")


def test_deterministic_lexical_quality_baseline():
    case = BenchmarkCase(id="quality-case-001", prompt="Prompt", expected_terms=("evidence", "risk"))

    assert lexical_quality_score(case, "Evidence supports the risk discussion.") == 100.0
    assert lexical_quality_score(case, "Evidence only.") == 50.0
