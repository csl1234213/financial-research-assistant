"""Focused tests for rate-limit runtime configuration."""

import pytest

from api.app import get_positive_int_setting


def test_rate_limit_settings_use_environment_and_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "250")
    assert get_positive_int_setting("RATE_LIMIT_REQUESTS", 100) == 250

    for invalid in ("0", "-1", "not-an-integer"):
        monkeypatch.setenv("RATE_LIMIT_REQUESTS", invalid)
        with pytest.raises(RuntimeError, match="RATE_LIMIT_REQUESTS"):
            get_positive_int_setting("RATE_LIMIT_REQUESTS", 100)
