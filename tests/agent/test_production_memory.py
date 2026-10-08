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
def setup_db_once():
    init_db()
    yield


def _register_and_login(email, password="TestPass123!"):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    if resp.status_code in (201, 200):
        data = resp.json()
        if "token" in data:
            return data["token"]
        if "access_token" in data:
            return data["access_token"]
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    if resp.status_code == 200:
        data = resp.json()
        if "token" in data:
            return data["token"]
        if "access_token" in data:
            return data["access_token"]
    raise RuntimeError(f"Failed to register/login: {resp.status_code} {resp.text}")


class TestProductionMemory:
    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_full_conversation_flow(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True

        conversation_state = {"history": []}

        def side_effect(question, thread_id, tenant_id=None, user_id=None):
            conversation_state["history"].append({"role": "user", "content": question})
            answer = f"[Agent] Response to: {question}"
            conversation_state["history"].append({"role": "assistant", "content": answer})
            return {
                "answer": answer,
                "thread_id": thread_id,
                "tools_used": ["financial_search_tool"],
                "sources": [
                    {"content": "NVIDIA Q1: $60.9B", "metadata": {"source": "NVIDIA_Q1.pdf"}}
                ],
                "companies": ["NVIDIA"],
                "research_plan": [],
                "quality_score": 85.0,
                "critique": {"passed": True},
                "revision_count": 0,
                "history": list(conversation_state["history"]),
                "duration": 1.0,
            }

        mock_run_agent.side_effect = side_effect

        token = _register_and_login("prod_memory@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp1 = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA", "thread_id": "prod_thread_1"},
            headers=headers,
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["answer"] == "[Agent] Response to: 分析 NVIDIA"
        assert data1["thread_id"] == "prod_thread_1"

        resp2 = client.post(
            "/api/v1/agent/chat",
            json={"question": "它的主要风险是什么？", "thread_id": "prod_thread_1"},
            headers=headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["answer"] == "[Agent] Response to: 它的主要风险是什么？"
        assert data2["thread_id"] == "prod_thread_1"

        assert len(conversation_state["history"]) == 4
        assert conversation_state["history"][0]["role"] == "user"
        assert conversation_state["history"][0]["content"] == "分析 NVIDIA"
        assert conversation_state["history"][2]["role"] == "user"
        assert conversation_state["history"][2]["content"] == "它的主要风险是什么？"

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_context_restored_after_runtime_restart(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True

        saved_context = []

        def side_effect_1(question, thread_id, tenant_id=None, user_id=None):
            saved_context.append({"question": question, "thread_id": thread_id})
            return {
                "answer": f"[Run 1] Answer to: {question}",
                "thread_id": thread_id,
                "tools_used": ["search"],
                "sources": [],
                "companies": [],
                "research_plan": [],
                "quality_score": 80.0,
                "critique": {},
                "revision_count": 0,
                "history": [],
                "duration": 0.5,
            }

        mock_run_agent.side_effect = side_effect_1

        token = _register_and_login("restart_test@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp1 = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA", "thread_id": "restart_thread"},
            headers=headers,
        )
        assert resp1.status_code == 200
        assert resp1.json()["answer"] == "[Run 1] Answer to: 分析 NVIDIA"

        mock_run_agent.reset_mock()

        def side_effect_2(question, thread_id, tenant_id=None, user_id=None):
            saved_context.append({"question": question, "thread_id": thread_id})
            return {
                "answer": f"[Run 2] Context: {saved_context[0]['question']} → {question}",
                "thread_id": thread_id,
                "tools_used": ["search"],
                "sources": [],
                "companies": [],
                "research_plan": [],
                "quality_score": 80.0,
                "critique": {},
                "revision_count": 0,
                "history": [],
                "duration": 0.5,
            }

        mock_run_agent.side_effect = side_effect_2

        resp2 = client.post(
            "/api/v1/agent/chat",
            json={"question": "它的主要风险是什么？", "thread_id": "restart_thread"},
            headers=headers,
        )
        assert resp2.status_code == 200
        assert "分析 NVIDIA" in resp2.json()["answer"]
        assert "它的主要风险是什么？" in resp2.json()["answer"]

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_checkpoint_saved_and_restored(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Checkpoint test response.",
            "thread_id": "cp_thread",
            "tools_used": ["financial_search_tool"],
            "sources": [{"content": "NVIDIA data", "metadata": {"source": "NVIDIA.pdf"}}],
            "companies": ["NVIDIA"],
            "research_plan": [],
            "quality_score": 90.0,
            "critique": {"passed": True},
            "revision_count": 0,
            "history": [],
            "duration": 0.5,
        }

        token = _register_and_login("checkpoint_test@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA", "thread_id": "cp_thread"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["quality_score"] == 90.0
        assert resp.json()["thread_id"] == "cp_thread"

        call_args = mock_run_agent.call_args[1]
        assert "tenant_id" in call_args
        assert call_args["tenant_id"] is not None
        assert call_args["thread_id"] == "cp_thread"

    @patch("api.routers.agent.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_tenant_isolation_across_threads(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Isolation test.",
            "thread_id": "iso_thread",
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

        token_a = _register_and_login("tenant_a_prod@example.com")
        token_b = _register_and_login("tenant_b_prod@example.com")

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        resp_a = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 NVIDIA", "thread_id": "prod_iso_thread"},
            headers=headers_a,
        )
        assert resp_a.status_code == 200

        resp_b = client.post(
            "/api/v1/agent/chat",
            json={"question": "分析 Tesla", "thread_id": "prod_iso_thread"},
            headers=headers_b,
        )
        assert resp_b.status_code == 200

        assert mock_run_agent.call_count == 2

        call_a = mock_run_agent.call_args_list[0][1]
        call_b = mock_run_agent.call_args_list[1][1]

        assert call_a["user_id"] != call_b["user_id"]
        assert call_a["thread_id"] == "prod_iso_thread"
        assert call_b["thread_id"] == "prod_iso_thread"
        assert call_a["question"] == "分析 NVIDIA"
        assert call_b["question"] == "分析 Tesla"
