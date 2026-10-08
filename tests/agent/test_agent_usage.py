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


class TestAgentUsage:
    @patch("api.routers.agent.record_usage")
    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_usage_recorded_after_agent_chat(self, mock_can_chat, mock_run_agent, mock_record_usage):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "NVIDIA analysis.",
            "thread_id": "test",
            "tools_used": ["financial_search_tool"],
            "sources": [],
            "companies": [],
            "research_plan": [],
            "quality_score": 85.0,
            "critique": {},
            "revision_count": 0,
            "history": [],
            "duration": 1.0,
        }

        token = _register_and_login("agent_usage@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 200

        mock_record_usage.assert_called_once()

        call_kwargs = mock_record_usage.call_args[1]
        assert call_kwargs["event_type"] == "chat_request"
        assert call_kwargs["resource_type"] == "chat"
        assert call_kwargs["quantity"] == 1
        assert "tenant_id" in call_kwargs
        assert "user_id" in call_kwargs
        assert "metadata" in call_kwargs
        assert call_kwargs["metadata"]["endpoint"] == "/api/v1/agent/chat"
        assert call_kwargs["metadata"]["agent_type"] == "langgraph"

    @patch("api.routers.agent.record_usage")
    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_usage_includes_duration(self, mock_can_chat, mock_run_agent, mock_record_usage):
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
            "duration": 2.5,
        }

        token = _register_and_login("usage_duration@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 200

        call_kwargs = mock_record_usage.call_args[1]
        metadata = call_kwargs["metadata"]
        assert "duration" in metadata
        assert isinstance(metadata["duration"], (int, float))

    @patch("api.routers.agent.record_usage")
    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_usage_includes_tools_and_quality_score(self, mock_can_chat, mock_run_agent, mock_record_usage):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Analysis complete.",
            "thread_id": "test",
            "tools_used": ["financial_search_tool", "get_financial_metrics"],
            "sources": [],
            "companies": [],
            "research_plan": [],
            "quality_score": 92.0,
            "critique": {"passed": True},
            "revision_count": 1,
            "history": [],
            "duration": 1.5,
        }

        token = _register_and_login("usage_tools@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA"},
            headers=headers,
        )

        assert resp.status_code == 200

        call_kwargs = mock_record_usage.call_args[1]
        metadata = call_kwargs["metadata"]
        assert metadata["tools_used"] == ["financial_search_tool", "get_financial_metrics"]
        assert metadata["quality_score"] == 92.0
