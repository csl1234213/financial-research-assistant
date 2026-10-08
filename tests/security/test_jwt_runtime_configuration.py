"""Focused tests for explicit JWT configuration and retired-key rejection."""

import hashlib

import pytest

from auth import jwt


def _clear_auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("APP_ENV", "AUTH_SECRET_KEY", "SECRET_KEY"):
        monkeypatch.delenv(variable, raising=False)


def test_auth_secret_prefers_explicit_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "legacy-signing-key")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    assert jwt._resolve_secret_key() == "x" * 32


def test_auth_secret_rejects_legacy_alias_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "legacy-signing-key")
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        jwt._resolve_secret_key()


def test_auth_secret_rejects_missing_or_placeholder_production_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_auth_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        jwt._resolve_secret_key()
    for value in ("change-me-to-a-random-secret-key", "short"):
        monkeypatch.setenv("AUTH_SECRET_KEY", value)
        with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
            jwt._resolve_secret_key()


def test_retired_signing_digest_rejection_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    synthetic_value = "a" * 48
    monkeypatch.setattr(jwt, "_RETIRED_SIGNING_KEY_SHA256", hashlib.sha256(synthetic_value.encode()).digest())
    for value in (synthetic_value, synthetic_value.upper()):
        monkeypatch.setenv("AUTH_SECRET_KEY", value)
        with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
            jwt._resolve_secret_key()


def test_auth_secret_accepts_explicit_test_secret_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret")
    assert jwt._resolve_secret_key() == "test-secret"


def test_auth_secret_uses_development_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_environment(monkeypatch)
    assert jwt._resolve_secret_key() == jwt.DEVELOPMENT_SECRET_KEY
