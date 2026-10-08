import pytest
from fastapi import HTTPException

from auth.dependencies import require_admin_user
from models.user import User


def _user_with_role(role: str) -> User:
    return User(
        email=f"{role}@example.com",
        password_hash="not-used",
        role=role,
        tenant_id=1,
    )


@pytest.mark.parametrize("role", ["admin", "owner", "ADMIN"])
def test_operator_roles_can_access_admin_actions(role):
    user = _user_with_role(role)

    assert require_admin_user(user) is user


@pytest.mark.parametrize("role", ["user", "analyst", ""])
def test_non_operator_roles_are_rejected(role):
    with pytest.raises(HTTPException) as exc_info:
        require_admin_user(_user_with_role(role))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Administrator role required"
