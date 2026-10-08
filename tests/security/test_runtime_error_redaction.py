from services.agent_runtime.runtime import _fallback_response


def test_runtime_fallback_does_not_expose_internal_exception_details() -> None:
    secret_error = "postgresql://admin:password@internal-db/private"

    response = _fallback_response(
        "Analyze Tesla",
        "thread-1",
        secret_error,
        "trace-123",
    )

    assert secret_error not in response["answer"]
    assert "password" not in response["answer"]
    assert response["trace_id"] == "trace-123"


def test_provider_balance_failure_is_classified_without_upstream_details() -> None:
    response = _fallback_response(
        "Analyze Tesla",
        "thread-1",
        "Insufficient balance; upstream response omitted",
        "trace-123",
    )

    assert response["answer"].startswith("[Provider Error]")
    assert "upstream" not in response["answer"].lower()
