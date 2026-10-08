import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from models.task import TaskStatus, TaskType
from storage.database import SessionLocal, init_db
from tasks.agent_tasks import agent_task_handler
from tasks.repository import TaskRepository


@pytest.fixture(autouse=True, scope="session")
def setup_db():
    init_db()
    yield


@pytest.fixture
def db():
    db = SessionLocal()
    yield db
    db.close()


def _fresh_repo():
    return TaskRepository(SessionLocal())


class TestAgentWorker:
    @patch("tasks.agent_tasks.run_agent")
    def test_agent_task_handler_success(self, mock_run_agent, db):
        mock_run_agent.return_value = {
            "answer": "NVIDIA 分析完成",
            "thread_id": "worker_test_thread",
            "tools_used": ["search"],
            "sources": [],
            "companies": ["NVIDIA"],
            "quality_score": 90.0,
        }

        repo = TaskRepository(db)
        task = repo.create_task(
            task_type=TaskType.AGENT_TASK,
            payload={"question": "分析 NVIDIA", "thread_id": "worker_test_thread"},
            tenant_id=1,
            user_id=1,
        )

        agent_task_handler(task.public_id)

        updated = _fresh_repo().get_task(task.public_id)
        assert updated is not None
        assert updated.status == TaskStatus.SUCCESS.value
        assert updated.result["answer"] == "NVIDIA 分析完成"
        assert updated.result["quality_score"] == 90.0

    @patch("tasks.agent_tasks.run_agent")
    def test_agent_task_handler_failure(self, mock_run_agent, db):
        mock_run_agent.side_effect = RuntimeError("Simulated error")

        repo = TaskRepository(db)
        task = repo.create_task(
            task_type=TaskType.AGENT_TASK,
            payload={"question": "分析 NVIDIA", "thread_id": "fail_thread"},
            tenant_id=1,
            user_id=1,
        )

        agent_task_handler(task.public_id)

        updated = _fresh_repo().get_task(task.public_id)
        assert updated is not None
        assert updated.status == TaskStatus.FAILED.value
        assert "Simulated error" in updated.error_message

    @patch("tasks.agent_tasks.run_agent")
    def test_agent_task_handler_no_question(self, mock_run_agent, db):
        repo = TaskRepository(db)
        task = repo.create_task(
            task_type=TaskType.AGENT_TASK,
            payload={"thread_id": "no_q_thread"},
            tenant_id=1,
            user_id=1,
        )

        agent_task_handler(task.public_id)

        updated = _fresh_repo().get_task(task.public_id)
        assert updated is not None
        assert updated.status == TaskStatus.FAILED.value
        assert "question is required" in updated.error_message
        mock_run_agent.assert_not_called()

    @patch("tasks.agent_tasks.run_agent")
    def test_agent_task_handler_nonexistent_task(self, mock_run_agent):
        agent_task_handler("nonexistent_task_id")
        mock_run_agent.assert_not_called()

    @patch("tasks.agent_tasks.run_agent")
    def test_agent_task_tenant_isolation(self, mock_run_agent, db):
        mock_run_agent.return_value = {
            "answer": "Tenant specific answer",
            "thread_id": "thread_a",
            "tools_used": [],
            "sources": [],
            "companies": [],
            "quality_score": 80.0,
        }

        repo = TaskRepository(db)
        task_a = repo.create_task(
            task_type=TaskType.AGENT_TASK,
            payload={"question": "Tenant A question", "thread_id": "thread_a"},
            tenant_id=10,
            user_id=10,
        )
        task_b = repo.create_task(
            task_type=TaskType.AGENT_TASK,
            payload={"question": "Tenant B question", "thread_id": "thread_b"},
            tenant_id=20,
            user_id=20,
        )

        agent_task_handler(task_a.public_id)
        agent_task_handler(task_b.public_id)

        updated_a = _fresh_repo().get_task(task_a.public_id)
        updated_b = _fresh_repo().get_task(task_b.public_id)

        assert updated_a.tenant_id == 10
        assert updated_b.tenant_id == 20
        assert updated_a.status == TaskStatus.SUCCESS.value
        assert updated_b.status == TaskStatus.SUCCESS.value

    @patch("tasks.agent_tasks.run_agent")
    def test_agent_task_retry_mechanism(self, mock_run_agent, db):
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError(f"Temporary failure (attempt {call_count[0]})")
            return {
                "answer": "Success after retry",
                "thread_id": "retry_thread",
                "tools_used": [],
                "sources": [],
                "companies": [],
                "quality_score": 85.0,
            }

        mock_run_agent.side_effect = side_effect

        repo = TaskRepository(db)
        task = repo.create_task(
            task_type=TaskType.AGENT_TASK,
            payload={"question": "Retry test", "thread_id": "retry_thread"},
            tenant_id=1,
            user_id=1,
        )

        agent_task_handler(task.public_id)
        assert _fresh_repo().get_task(task.public_id).status == TaskStatus.FAILED.value

        agent_task_handler(task.public_id)
        assert _fresh_repo().get_task(task.public_id).status == TaskStatus.FAILED.value

        agent_task_handler(task.public_id)
        updated = _fresh_repo().get_task(task.public_id)
        assert updated.status == TaskStatus.SUCCESS.value
        assert updated.result["answer"] == "Success after retry"
        assert call_count[0] == 3
