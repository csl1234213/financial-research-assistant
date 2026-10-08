"""Focused tests for storage runtime configuration."""

import pytest

from config.storage import StorageConfig


def test_storage_environment_uses_app_env_with_legacy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    assert StorageConfig().is_production is True
