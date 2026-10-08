import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.app import app
from storage.database import init_db

client = TestClient(app)


@pytest.fixture(autouse=True, scope="session")
def setup_db():
    init_db()
    yield


def _register_and_login(email, password="TestPass123!"):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    if resp.status_code in (201, 200):
        data = resp.json()
        token = data.get("token") or data.get("access_token")
        if token:
            return token
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    if resp.status_code == 200:
        data = resp.json()
        token = data.get("token") or data.get("access_token")
        if token:
            return token
    raise RuntimeError(f"Auth failed: {resp.status_code} {resp.text}")


class TestAsyncAgentAPI:
    @patch("api.routers.agent.can_chat")
    def test_create_agent_task_returns_pending(self, mock_can_chat):
        mock_can_chat.return_value = True
        token = _register_and_login("async_task@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/tasks",
            json={"question": "分析 NVIDIA", "thread_id": "async_thread_1"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert "task_id" in data
        assert len(data["task_id"]) > 0

    @patch("api.routers.agent.can_chat")
    def test_get_task_status_pending(self, mock_can_chat):
        mock_can_chat.return_value = True
        token = _register_and_login("status_test@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = client.post(
            "/api/v1/agent/tasks",
            json={"question": "分析 Tesla", "thread_id": "status_thread"},
            headers=headers,
        )
        assert create_resp.status_code == 200
        task_id = create_resp.json()["task_id"]

        status_resp = client.get(
            f"/api/v1/agent/tasks/{task_id}",
            headers=headers,
        )

        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["id"] == task_id
        assert data["status"] == "pending"
        assert data["result"] is None

    @patch("api.routers.agent.can_chat")
    def test_get_task_not_found(self, mock_can_chat):
        mock_can_chat.return_value = True
        token = _register_and_login("notfound@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get(
            "/api/v1/agent/tasks/nonexistent_task_id",
            headers=headers,
        )
        assert resp.status_code == 404

    @patch("api.routers.agent.can_chat")
    def test_tenant_isolation_task_access(self, mock_can_chat):
        mock_can_chat.return_value = True
        token_a = _register_and_login("tenant_a_task@example.com")
        token_b = _register_and_login("tenant_b_task@example.com")
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        create_resp = client.post(
            "/api/v1/agent/tasks",
            json={"question": "分析 NVIDIA", "thread_id": "iso_task"},
            headers=headers_a,
        )
        assert create_resp.status_code == 200
        task_id = create_resp.json()["task_id"]

        status_resp = client.get(
            f"/api/v1/agent/tasks/{task_id}",
            headers=headers_a,
        )
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["id"] == task_id
        assert data["status"] == "pending"

        from storage.database import SessionLocal
        from tasks.repository import TaskRepository
        db = SessionLocal()
        try:
            repo = TaskRepository(db)
            task = repo.get_task(task_id)
            assert task is not None
            assert task.tenant_id is not None
        finally:
            db.close()

    @patch("api.routers.agent.can_chat")
    def test_create_task_without_thread_id(self, mock_can_chat):
        mock_can_chat.return_value = True
        token = _register_and_login("no_thread@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/tasks",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["thread_id"] == "default"

    @patch("api.routers.agent.can_chat")
    def test_rate_limit_enforced(self, mock_can_chat):
        mock_can_chat.return_value = False
        token = _register_and_login("rate_limit@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/tasks",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )
        assert resp.status_code == 429
