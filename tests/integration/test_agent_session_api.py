from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import app
from auth.dependencies import get_current_user
from cache.session import ThreadCacheDeletion
from storage.agent.models import AgentCheckpoint
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


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def principal():
    return SimpleNamespace(id=10, tenant_id=1)


@pytest.fixture
def client(principal):
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: principal
    with TestClient(app) as test_client:
        yield test_client


def seed_session(
    tenant_id: int,
    user_id: int,
    thread_id: str,
    messages: tuple[tuple[str, str], ...] = (),
):
    with TestingSessionLocal() as db:
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id, user_id, thread_id)
        for role, content in messages:
            repo.add_message(session.id, role, content)
        return session.id


def test_session_reload_preserves_generation_duration_metadata(client):
    session_id = seed_session(1, 10, "duration-reload", (("user", "What is AI?"),))
    with TestingSessionLocal() as db:
        AgentRepository(db).add_message(
            session_id, "assistant", "An explanation.", {"duration_ms": 18200},
        )

    first = client.get("/api/v1/agent/sessions/duration-reload")
    reloaded = client.get("/api/v1/agent/sessions/duration-reload")

    assert first.status_code == reloaded.status_code == 200
    assert reloaded.json()["messages"][1]["metadata"]["duration_ms"] == 18200
    assert first.json()["messages"] == reloaded.json()["messages"]


def test_sessions_require_authentication():
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as anonymous_client:
        response = anonymous_client.get("/api/v1/agent/sessions")

    assert response.status_code in {401, 403}


def test_list_sessions_is_current_user_scoped(client):
    seed_session(1, 10, "owned", (("user", "private"),))
    seed_session(1, 11, "same-tenant-other-user")
    seed_session(2, 10, "other-tenant")

    response = client.get("/api/v1/agent/sessions?limit=10&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["thread_id"] == "owned"
    assert payload["items"][0]["message_count"] == 1
    assert "tenant_id" not in payload["items"][0]
    assert "user_id" not in payload["items"][0]


def test_read_and_export_session_transcript(client):
    seed_session(
        1,
        10,
        "research",
        (
            ("user", "Analyze Tesla"),
            ("assistant", "Tesla report"),
            ("user", "Explain margin"),
        ),
    )

    detail = client.get(
        "/api/v1/agent/sessions/research"
        "?message_limit=2&message_offset=1"
    )
    exported = client.get(
        "/api/v1/agent/sessions/research/export?limit=2&offset=0"
    )

    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["total_messages"] == 3
    assert [message["content"] for message in detail_payload["messages"]] == [
        "Tesla report",
        "Explain margin",
    ]
    assert exported.status_code == 200
    export_payload = exported.json()
    assert export_payload["format_version"] == "1.0"
    assert export_payload["total_messages"] == 3
    assert export_payload["session"]["thread_id"] == "research"
    assert [message["role"] for message in export_payload["messages"]] == [
        "user",
        "assistant",
    ]


@pytest.mark.parametrize(
    ("tenant_id", "user_id"),
    [(1, 11), (2, 10)],
)
def test_read_does_not_reveal_cross_principal_session(
    client,
    tenant_id,
    user_id,
):
    seed_session(tenant_id, user_id, "shared", (("user", "secret"),))

    response = client.get("/api/v1/agent/sessions/shared")

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent session not found"


@patch(
    "api.routers.agent_sessions.delete_scoped_checkpoint_thread",
    return_value=True,
)
@patch(
    "api.routers.agent_sessions.session_cache.delete_thread",
    return_value=ThreadCacheDeletion(successful=True, keys_deleted=2),
)
def test_delete_removes_messages_archives_checkpoint_and_clears_cache(
    delete_cache,
    delete_runtime,
    client,
):
    seed_session(1, 10, "portfolio*", (("user", "private"),))
    seed_session(1, 10, "portfolio-safe", (("user", "keep"),))
    with TestingSessionLocal() as db:
        repo = AgentRepository(db)
        checkpoint = repo.save_checkpoint(
            1,
            "portfolio*",
            {"state": "private"},
            user_id=10,
        )
        checkpoint_id = checkpoint.id

    response = client.delete("/api/v1/agent/sessions/portfolio%2A")

    assert response.status_code == 200
    assert response.json() == {
        "deleted": True,
        "thread_id": "portfolio*",
        "messages_deleted": 1,
        "checkpoints_archived": 1,
        "runtime_checkpoints_deleted": True,
        "cache_keys_deleted": 2,
    }
    delete_runtime.assert_called_once_with(1, 10, "portfolio*")
    delete_cache.assert_called_once_with("portfolio*", 1, user_id=10)
    with TestingSessionLocal() as db:
        repo = AgentRepository(db)
        assert repo.get_session(1, 10, "portfolio*") is None
        assert repo.get_session(1, 10, "portfolio-safe") is not None
        assert db.get(AgentCheckpoint, checkpoint_id).archived_at is not None


@patch(
    "api.routers.agent_sessions.delete_scoped_checkpoint_thread",
    return_value=False,
)
def test_delete_fails_closed_when_runtime_checkpoint_cannot_be_removed(
    delete_runtime,
    client,
):
    seed_session(1, 10, "durable", (("user", "private"),))

    response = client.delete("/api/v1/agent/sessions/durable")

    assert response.status_code == 503
    with TestingSessionLocal() as db:
        assert AgentRepository(db).get_session(1, 10, "durable") is not None


@patch(
    "api.routers.agent_sessions.delete_scoped_checkpoint_thread",
    return_value=True,
)
def test_repeated_delete_has_clear_not_found_semantics(
    delete_runtime,
    client,
):
    seed_session(1, 10, "once")

    with patch(
        "api.routers.agent_sessions.session_cache.delete_thread",
        return_value=ThreadCacheDeletion(successful=True, keys_deleted=0),
    ):
        first = client.delete("/api/v1/agent/sessions/once")
        second = client.delete("/api/v1/agent/sessions/once")

    assert first.status_code == 200
    assert second.status_code == 404


@patch(
    "api.routers.agent_sessions.delete_scoped_checkpoint_thread",
    return_value=True,
)
@patch(
    "api.routers.agent_sessions.session_cache.delete_thread",
    return_value=ThreadCacheDeletion(successful=False, keys_deleted=0),
)
def test_delete_fails_closed_when_cache_cannot_be_invalidated(
    delete_cache,
    delete_runtime,
    client,
):
    seed_session(1, 10, "cached", (("user", "private"),))

    response = client.delete("/api/v1/agent/sessions/cached")

    assert response.status_code == 503
    with TestingSessionLocal() as db:
        assert AgentRepository(db).get_session(1, 10, "cached") is not None


@pytest.mark.parametrize("thread_id", ["%20", "%20surrounded", "surrounded%20"])
def test_thread_id_rejects_blank_or_surrounding_whitespace(client, thread_id):
    response = client.get(f"/api/v1/agent/sessions/{thread_id}")

    assert response.status_code == 422


def test_thread_id_rejects_values_over_storage_limit(client):
    response = client.get(f"/api/v1/agent/sessions/{'x' * 257}")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "endpoint",
    ["/api/v1/chat", "/api/v1/agent/chat"],
)
@pytest.mark.parametrize("thread_id", ["", " ", " surrounded"])
def test_chat_entrypoints_reject_unmanageable_thread_ids(
    client,
    endpoint,
    thread_id,
):
    response = client.post(
        endpoint,
        json={"question": "Analyze Tesla", "thread_id": thread_id},
    )

    assert response.status_code == 422
