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


class TestTenantIsolation:
    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_tenant_a_cannot_access_tenant_b_data(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "NVIDIA analysis.",
            "thread_id": "tenant_a_thread",
            "tools_used": ["financial_search_tool"],
            "sources": [],
            "companies": [],
            "research_plan": [],
            "quality_score": 85.0,
            "critique": {"passed": True},
            "revision_count": 0,
            "history": [],
            "duration": 1.0,
        }

        token_a = _register_and_login("tenant_a@example.com")
        token_b = _register_and_login("tenant_b@example.com")

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        resp_a = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA", "thread_id": "thread_a"},
            headers=headers_a,
        )
        assert resp_a.status_code == 200

        resp_b = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 Tesla", "thread_id": "thread_b"},
            headers=headers_b,
        )
        assert resp_b.status_code == 200

        assert mock_run_agent.call_count == 2

        call_a = mock_run_agent.call_args_list[0][1]
        call_b = mock_run_agent.call_args_list[1][1]

        assert "tenant_id" in call_a
        assert "tenant_id" in call_b
        assert "user_id" in call_a
        assert "user_id" in call_b
        assert call_a["user_id"] != call_b["user_id"]
        assert call_a["thread_id"] == "thread_a"
        assert call_b["thread_id"] == "thread_b"

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_tenant_specific_thread_id(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Analysis complete.",
            "thread_id": "tenant_isolated_thread",
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

        token = _register_and_login("tenant_isolated@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA", "thread_id": "my_custom_thread"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == "tenant_isolated_thread"

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_tenant_id_injected_into_runtime(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Done.",
            "thread_id": "test",
            "tools_used": [],
            "sources": [],
            "companies": [],
            "research_plan": [],
            "quality_score": 80.0,
            "critique": {},
            "revision_count": 0,
            "history": [],
            "duration": 0.3,
        }

        token = _register_and_login("tenant_inject@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 200

        call_args = mock_run_agent.call_args
        assert call_args is not None

        kwargs = call_args[1]
        assert "tenant_id" in kwargs
        assert kwargs["tenant_id"] is not None
        assert "user_id" in kwargs
        assert kwargs["user_id"] is not None
