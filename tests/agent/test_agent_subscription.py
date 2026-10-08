import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.app import app
from storage.database import SessionLocal, init_db

client = TestClient(app)


@pytest.fixture(autouse=True, scope="session")
def setup_db_once():
    init_db()
    yield


@pytest.fixture(autouse=True)
def setup_db():
    yield
    SessionLocal().close()


def _register_and_login(email, password="TestPass123!"):
    resp = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    if resp.status_code in (201, 200):
        data = resp.json()
        if "token" in data:
            return data["token"]
        if "access_token" in data:
            return data["access_token"]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if resp.status_code == 200:
        data = resp.json()
        if "token" in data:
            return data["token"]
        if "access_token" in data:
            return data["access_token"]
    raise RuntimeError(f"Failed to register/login: {resp.status_code} {resp.text}")


class TestSubscriptionLimit:
    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_agent_chat_when_limit_allowed(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Analysis OK.",
            "thread_id": "test",
            "tools_used": [],
            "sources": [],
            "companies": [],
            "research_plan": [],
            "quality_score": 80.0,
            "critique": {},
            "revision_count": 0,
            "history": [],
            "duration": 0.5,
        }

        token = _register_and_login("limit_ok@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 200

    @patch("api.routers.agent.can_chat")
    def test_agent_chat_when_limit_exceeded_returns_429(self, mock_can_chat):
        mock_can_chat.return_value = False

        token = _register_and_login("limit_exceeded@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert "limit" in detail.lower() or "plan" in detail.lower()

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_multiple_requests_count_toward_limit(self, mock_can_chat, mock_run_agent):
        mock_can_chat.side_effect = [True, True, True, False]
        mock_run_agent.return_value = {
            "answer": "Analysis.",
            "thread_id": "test",
            "tools_used": [],
            "sources": [],
            "companies": [],
            "research_plan": [],
            "quality_score": 80.0,
            "critique": {},
            "revision_count": 0,
            "history": [],
            "duration": 0.5,
        }

        token = _register_and_login("multiple_req@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        for i in range(3):
            resp = client.post(
                "/api/v1/agent/chat",
                json={"question": f"分析 NVIDIA 第{i + 1}次"},
                headers=headers,
            )
            assert resp.status_code == 200

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA 第4次"},
            headers=headers,
        )
        assert resp.status_code == 429

    @patch("api.routers.agent.can_chat")
    def test_429_error_message_descriptive(self, mock_can_chat):
        mock_can_chat.return_value = False

        token = _register_and_login("desc_error@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 429
        data = resp.json()
        assert "detail" in data
        assert len(data["detail"]) > 0
