from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import app
from auth.jwt import create_access_token
from cache.session import ThreadCacheDeletion
from models.tenant import Tenant
from models.user import User
from storage.agent.repository import AgentRepository
from storage.database import Base, get_db

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def principals():
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        tenant_a = Tenant(name="Tenant A", slug="session-security-a")
        tenant_b = Tenant(name="Tenant B", slug="session-security-b")
        db.add_all([tenant_a, tenant_b])
        db.flush()
        user_a = User(
            email="session-a@example.com",
            password_hash="unused",
            tenant_id=tenant_a.id,
        )
        user_a_peer = User(
            email="session-a-peer@example.com",
            password_hash="unused",
            tenant_id=tenant_a.id,
        )
        user_b = User(
            email="session-b@example.com",
            password_hash="unused",
            tenant_id=tenant_b.id,
        )
        db.add_all([user_a, user_a_peer, user_b])
        db.commit()
        ids = {
            "tenant_a": tenant_a.id,
            "tenant_b": tenant_b.id,
            "user_a": user_a.id,
            "user_a_peer": user_a_peer.id,
            "user_b": user_b.id,
        }
    app.dependency_overrides[get_db] = override_get_db
    yield ids
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def _auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def _seed_private_session(
    tenant_id: int,
    user_id: int,
    content: str,
) -> None:
    with TestingSessionLocal() as db:
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id, user_id, "default")
        repo.add_message(session.id, "user", content)


def test_real_jwt_scope_returns_each_users_own_same_thread(principals):
    _seed_private_session(
        principals["tenant_a"],
        principals["user_a"],
        "owner secret",
    )
    _seed_private_session(
        principals["tenant_a"],
        principals["user_a_peer"],
        "peer secret",
    )
    _seed_private_session(
        principals["tenant_b"],
        principals["user_b"],
        "other tenant secret",
    )

    with TestClient(app) as client:
        owner = client.get(
            "/api/v1/agent/sessions/default",
            headers=_auth_headers(principals["user_a"]),
        )
        peer = client.get(
            "/api/v1/agent/sessions/default",
            headers=_auth_headers(principals["user_a_peer"]),
        )
        other_tenant = client.get(
            "/api/v1/agent/sessions/default",
            headers=_auth_headers(principals["user_b"]),
        )

    assert owner.status_code == 200
    assert owner.json()["messages"][0]["content"] == "owner secret"
    assert peer.status_code == 200
    assert peer.json()["messages"][0]["content"] == "peer secret"
    assert other_tenant.status_code == 200
    assert other_tenant.json()["messages"][0]["content"] == "other tenant secret"


@patch(
    "api.routers.agent_sessions.delete_scoped_checkpoint_thread",
    return_value=True,
)
@patch(
    "api.routers.agent_sessions.session_cache.delete_thread",
    return_value=ThreadCacheDeletion(successful=True, keys_deleted=1),
)
def test_authenticated_delete_cannot_remove_peer_session(
    delete_cache,
    delete_runtime,
    principals,
):
    _seed_private_session(
        principals["tenant_a"],
        principals["user_a_peer"],
        "peer secret",
    )

    with TestClient(app) as client:
        response = client.delete(
            "/api/v1/agent/sessions/default",
            headers=_auth_headers(principals["user_a"]),
        )

    assert response.status_code == 404
    delete_runtime.assert_not_called()
    delete_cache.assert_not_called()
    with TestingSessionLocal() as db:
        peer_session = AgentRepository(db).get_session(
            principals["tenant_a"],
            principals["user_a_peer"],
            "default",
        )
        assert peer_session is not None
