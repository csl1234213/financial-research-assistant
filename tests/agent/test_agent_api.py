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


class TestAgentAPI:
    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_agent_chat_authenticated(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "NVIDIA Q1 revenue was $60.9B.",
            "thread_id": "test_thread",
            "tools_used": ["financial_search_tool"],
            "sources": [{"content": "NVIDIA Q1: $60.9B", "metadata": {"source": "NVIDIA.pdf"}}],
            "companies": ["NVIDIA"],
            "research_plan": [],
            "quality_score": 85.0,
            "critique": {"passed": True},
            "revision_count": 0,
            "history": [],
            "duration": 1.5,
        }

        token = _register_and_login("agent_test@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA", "thread_id": "test_thread"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["answer"] == "NVIDIA Q1 revenue was $60.9B."
        assert data["thread_id"] == "test_thread"
        assert "financial_search_tool" in data["tools_used"]
        assert data["quality_score"] == 85.0

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_agent_chat_returns_sources(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Analysis complete.",
            "thread_id": "test_thread",
            "tools_used": ["financial_search_tool", "get_financial_metrics"],
            "sources": [
                {"content": "NVIDIA FY2027 Q1", "metadata": {"source": "NVIDIA.pdf"}},
                {"content": "Revenue $60.9B", "metadata": {"source": "NVIDIA.pdf"}},
            ],
            "companies": [],
            "research_plan": [],
            "quality_score": 90.0,
            "critique": {"passed": True},
            "revision_count": 0,
            "history": [],
            "duration": 1.0,
        }

        token = _register_and_login("agent_sources@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sources"]) == 2
        assert data["tools_used"] == ["financial_search_tool", "get_financial_metrics"]

    def test_agent_chat_unauthenticated(self):
        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
        )
        assert resp.status_code in (401, 403)

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_agent_chat_empty_question(self, mock_can_chat, mock_run_agent):
        token = _register_and_login("agent_empty@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": ""},
            headers=headers,
        )

        assert resp.status_code == 422
