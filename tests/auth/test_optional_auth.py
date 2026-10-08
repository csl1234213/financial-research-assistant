from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from auth.dependencies import get_optional_user


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat",
            "headers": headers,
        }
    )


def test_missing_authorization_header_remains_anonymous():
    db = MagicMock()

    assert get_optional_user(_request(), db) is None
    db.query.assert_not_called()


@pytest.mark.parametrize(
    "header",
    [
        "Basic abc",
        "Bearer",
        "Bearer ",
        "Bearer token with-spaces",
    ],
)
def test_malformed_optional_credentials_fail_closed(header):
    with pytest.raises(HTTPException) as exc_info:
        get_optional_user(_request(header), MagicMock())

    assert exc_info.value.status_code == 401


@patch("auth.dependencies.decode_token", return_value=None)
def test_invalid_optional_bearer_token_is_not_downgraded_to_anonymous(_decode):
    with pytest.raises(HTTPException) as exc_info:
        get_optional_user(_request("Bearer invalid-token"), MagicMock())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired token"


@patch("auth.dependencies.decode_token", return_value={"sub": "7"})
def test_valid_token_for_unknown_user_fails_closed(_decode):
    db = MagicMock()
    db.query.return_value.options.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        get_optional_user(_request("Bearer valid-token"), db)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "User not found"
