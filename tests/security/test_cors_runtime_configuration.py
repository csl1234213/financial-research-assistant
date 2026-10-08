"""Focused tests for CORS runtime configuration."""

import pytest
from fastapi.testclient import TestClient

from api.app import (
    DEFAULT_CORS_ORIGINS,
    app,
    get_cors_origins,
)


def test_cors_origins_default_to_local_vite_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert get_cors_origins() == list(DEFAULT_CORS_ORIGINS)


def test_cors_origins_parse_a_trimmed_allowlist() -> None:
    assert get_cors_origins(" https://copilot.example ,http://localhost:3000/ , ") == [
        "https://copilot.example",
        "http://localhost:3000",
    ]


def test_cors_origins_require_an_explicit_production_allowlist() -> None:
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        get_cors_origins("", app_env="production")


def test_default_cors_configuration_accepts_vite_preflight() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
