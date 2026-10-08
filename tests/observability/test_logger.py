import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from observability.logger import StructuredLogger, log_agent_request


@dataclass(frozen=True)
class _ProviderRuntimeConfig:
    provider: str
    api_key: str


def test_structured_logger_serializes_rich_fields_and_redacts_credentials():
    logger = StructuredLogger("test.observability")
    cycle = {}
    cycle["self"] = cycle

    formatted = logger._format(
        "INFO",
        "agent_test",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        amount=Decimal("2.50"),
        labels={"beta", "alpha"},
        non_finite=float("nan"),
        authorization="Bearer private-token",
        nested={"password": "must-not-log"},
        cycle=cycle,
    )
    payload = json.loads(formatted)

    assert payload["event"] == "agent_test"
    assert payload["observed_at"] == "2026-01-01T00:00:00+00:00"
    assert payload["amount"] == "2.50"
    assert payload["labels"] == ["alpha", "beta"]
    assert payload["non_finite"] == "<non-finite-float>"
    assert payload["authorization"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    assert payload["cycle"]["self"] == "<cycle>"
    assert "private-token" not in formatted
    assert "must-not-log" not in formatted


def test_agent_request_log_does_not_write_financial_prompt_content(monkeypatch):
    captured = {}

    def capture(event, **fields):
        captured["event"] = event
        captured.update(fields)

    monkeypatch.setattr("observability.logger.agent_logger.info", capture)
    question = "Confidential acquisition revenue is 42 million."

    log_agent_request(
        request_id="request-1",
        tenant_id=7,
        thread_id="thread-1",
        question=question,
    )

    assert captured["event"] == "agent_request_started"
    assert captured["question_chars"] == len(question)
    assert len(captured["question_sha256"]) == 64
    assert "question" not in captured
    assert question not in json.dumps(captured)


def test_structured_logger_redacts_api_key_inside_dataclass():
    logger = StructuredLogger("test.observability.dataclass")
    api_key = "sk-dataclass-must-not-log-1234"

    formatted = logger._format(
        "INFO",
        "provider_selected",
        provider_config=_ProviderRuntimeConfig(
            provider="deepseek",
            api_key=api_key,
        ),
    )
    payload = json.loads(formatted)

    assert payload["provider_config"] == {
        "provider": "deepseek",
        "api_key": "[REDACTED]",
    }
    assert api_key not in formatted
