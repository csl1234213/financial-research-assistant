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


class TestAgentTaskFlow:
    @patch("tasks.agent_tasks.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_full_agent_task_flow(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "NVIDIA 最新财报分析：营收同比增长 94%，数据中心业务爆发式增长。",
            "thread_id": "phase84_test",
            "tools_used": ["search", "financial_analysis"],
            "sources": ["https://nvidia.com/earnings"],
            "companies": ["NVIDIA"],
            "quality_score": 92.0,
        }

        token = _register_and_login("phase84_flow@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = client.post(
            "/api/v1/agent/tasks",
            json={
                "question": "分析 NVIDIA 最新财报",
                "thread_id": "phase84_test",
            },
            headers=headers,
        )
        assert create_resp.status_code == 200
        task_data = create_resp.json()
        assert task_data["status"] == "pending"
        assert "task_id" in task_data
        task_id = task_data["task_id"]

        status_resp = client.get(
            f"/api/v1/agent/tasks/{task_id}",
            headers=headers,
        )
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["id"] == task_id
        assert status_data["status"] == "pending"
        assert status_data["result"] is None

        from tasks.agent_tasks import agent_task_handler
        agent_task_handler(task_id)

        final_resp = client.get(
            f"/api/v1/agent/tasks/{task_id}",
            headers=headers,
        )
        assert final_resp.status_code == 200
        final_data = final_resp.json()
        assert final_data["id"] == task_id
        assert final_data["status"] == "success"
        assert final_data["result"] is not None
        assert "NVIDIA" in final_data["result"]["answer"]
        assert final_data["result"]["quality_score"] == 92.0

    @patch("tasks.agent_tasks.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_agent_task_failure_flow(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.side_effect = RuntimeError("Agent execution failed due to upstream error")

        token = _register_and_login("phase84_fail@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = client.post(
            "/api/v1/agent/tasks",
            json={
                "question": "分析不存在的股票代码 XYZ999",
                "thread_id": "phase84_fail_test",
            },
            headers=headers,
        )
        assert create_resp.status_code == 200
        task_id = create_resp.json()["task_id"]

        from tasks.agent_tasks import agent_task_handler
        agent_task_handler(task_id)

        final_resp = client.get(
            f"/api/v1/agent/tasks/{task_id}",
            headers=headers,
        )
        assert final_resp.status_code == 200
        final_data = final_resp.json()
        assert final_data["id"] == task_id
        assert final_data["status"] == "failed"
        assert final_data["error"] is not None
        assert "Agent execution failed" in final_data["error"]

    @patch("tasks.agent_tasks.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_agent_task_multiple_questions(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.side_effect = [
            {
                "answer": "Tesla Q3 财报分析：营收 251.8 亿美元，同比增长 8%。",
                "thread_id": "multi_1",
                "tools_used": ["search"],
                "sources": [],
                "companies": ["Tesla"],
                "quality_score": 88.0,
            },
            {
                "answer": "Apple Q3 财报分析：营收 949.3 亿美元，同比增长 6%。",
                "thread_id": "multi_2",
                "tools_used": ["search"],
                "sources": [],
                "companies": ["Apple"],
                "quality_score": 90.0,
            },
        ]

        token = _register_and_login("phase84_multi@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        task_ids = []
        for question, thread_id in [
            ("分析 Tesla 最新财报", "multi_1"),
            ("分析 Apple 最新财报", "multi_2"),
        ]:
            create_resp = client.post(
                "/api/v1/agent/tasks",
                json={"question": question, "thread_id": thread_id},
                headers=headers,
            )
            assert create_resp.status_code == 200
            task_ids.append(create_resp.json()["task_id"])

        from tasks.agent_tasks import agent_task_handler
        for task_id in task_ids:
            agent_task_handler(task_id)

        for task_id in task_ids:
            final_resp = client.get(
                f"/api/v1/agent/tasks/{task_id}",
                headers=headers,
            )
            assert final_resp.status_code == 200
            final_data = final_resp.json()
            assert final_data["status"] == "success"
            assert final_data["result"] is not None

    @patch("tasks.agent_tasks.run_agent")
    @patch("api.routers.agent.can_chat")
    def test_agent_task_usage_recording(self, mock_can_chat, mock_run_agent):
        mock_can_chat.return_value = True
        mock_run_agent.return_value = {
            "answer": "Usage tracking test passed.",
            "thread_id": "usage_test",
            "tools_used": ["search"],
            "sources": [],
            "companies": [],
            "quality_score": 85.0,
        }

        token = _register_and_login("phase84_usage@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = client.post(
            "/api/v1/agent/tasks",
            json={
                "question": "测试 usage 记录",
                "thread_id": "usage_test",
            },
            headers=headers,
        )
        assert create_resp.status_code == 200
        task_id = create_resp.json()["task_id"]

        from tasks.agent_tasks import agent_task_handler
        agent_task_handler(task_id)

        final_resp = client.get(
            f"/api/v1/agent/tasks/{task_id}",
            headers=headers,
        )
        assert final_resp.status_code == 200
        final_data = final_resp.json()
        assert final_data["status"] == "success"
        assert final_data["result"] is not None
