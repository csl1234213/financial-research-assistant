import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import app
from auth.dependencies import get_current_user
from models.task import TaskStatus as TaskStatusModel
from models.task import TaskType as TaskTypeModel
from models.tenant import Tenant
from models.user import User
from storage.database import Base, get_db
from tasks.models import TaskStatus, TaskType
from tasks.queue import TaskQueue, get_task_queue
from tasks.repository import TaskRepository
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database(
    "test_task_queue_integration.db"
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(repo_user):
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: repo_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_queue():
    queue = get_task_queue()
    queue._tasks.clear()
    queue._queue.clear()
    yield
    queue._tasks.clear()
    queue._queue.clear()


@pytest.fixture(autouse=True)
def _setup_repo_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    db_path = TEST_DATABASE_URL.replace("sqlite:///", "")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except (PermissionError, OSError):
            pass


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def repo_tenant(db_session):
    t = Tenant(name="Test Tenant", slug="test")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def repo_user(db_session, repo_tenant):
    u = User(email="test@test.com", password_hash="hash", tenant_id=repo_tenant.id)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


class TestTaskQueue:
    def test_create_task_requires_tenant_id(self):
        queue = TaskQueue()
        with pytest.raises(ValueError, match="tenant_id is required"):
            queue.create_task(
                task_type=TaskType.PROCESS_DOCUMENT,
                payload={"file_path": "/tmp/test.pdf"},
            )

    def test_create_task_success(self):
        queue = TaskQueue()
        task = queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/test.pdf"},
            tenant_id=1,
            user_id=10,
        )
        assert task.id is not None
        assert task.type == TaskType.PROCESS_DOCUMENT
        assert task.status == TaskStatus.PENDING
        assert task.tenant_id == 1
        assert task.user_id == 10
        assert task.payload["file_path"] == "/tmp/test.pdf"

    def test_enqueue_and_dequeue(self):
        queue = TaskQueue()
        task = queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/test.pdf"},
            tenant_id=1,
        )
        queue.enqueue(task)

        dequeued = queue.dequeue(timeout=0.1)
        assert dequeued is not None
        assert dequeued.id == task.id

    def test_dequeue_empty_returns_none(self):
        queue = TaskQueue()
        result = queue.dequeue(timeout=0.1)
        assert result is None

    def test_get_task_status(self):
        queue = TaskQueue()
        task = queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/test.pdf"},
            tenant_id=1,
        )
        retrieved = queue.get_task(task.id)
        assert retrieved is not None
        assert retrieved.status == TaskStatus.PENDING

    def test_update_task_status(self):
        queue = TaskQueue()
        task = queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/test.pdf"},
            tenant_id=1,
        )
        queue.update_task(task.id, status=TaskStatus.RUNNING, progress=50)
        updated = queue.get_task(task.id)
        assert updated.status == TaskStatus.RUNNING
        assert updated.progress == 50

    def test_update_task_error(self):
        queue = TaskQueue()
        task = queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/test.pdf"},
            tenant_id=1,
        )
        queue.update_task(
            task.id,
            status=TaskStatus.FAILED,
            error_message="Something went wrong",
        )
        updated = queue.get_task(task.id)
        assert updated.status == TaskStatus.FAILED
        assert updated.error_message == "Something went wrong"

    def test_list_tasks_by_tenant(self):
        queue = TaskQueue()
        t1 = queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/a.pdf"},
            tenant_id=1,
        )
        t2 = queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/b.pdf"},
            tenant_id=2,
        )

        tenant1_tasks = queue.list_tasks(tenant_id=1)
        assert len(tenant1_tasks) == 1
        assert tenant1_tasks[0].id == t1.id

        tenant2_tasks = queue.list_tasks(tenant_id=2)
        assert len(tenant2_tasks) == 1
        assert tenant2_tasks[0].id == t2.id

    def test_list_tasks_all(self):
        queue = TaskQueue()
        queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/a.pdf"},
            tenant_id=1,
        )
        queue.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/b.pdf"},
            tenant_id=2,
        )

        all_tasks = queue.list_tasks()
        assert len(all_tasks) == 2


class TestWorker:
    def test_worker_processes_task(self, repo_tenant, repo_user, db_session):
        repo = TaskRepository(db_session)
        task = repo.create_task(
            TaskTypeModel.PROCESS_DOCUMENT,
            {"file_path": "/tmp/nonexistent.pdf", "document_id": 1},
            repo_tenant.id,
            repo_user.id,
        )

        claimed = repo.claim_task()
        assert claimed is not None
        assert claimed.status == TaskStatusModel.RUNNING.value

        repo.update_task(
            task.public_id,
            status=TaskStatusModel.FAILED,
            error_message="File not found: /tmp/nonexistent.pdf",
        )

        updated = repo.get_task(task.public_id)
        assert updated is not None
        assert updated.status == TaskStatusModel.FAILED.value
        assert updated.error_message is not None

    def test_worker_tenant_isolation(self):
        with pytest.raises(ValueError, match="tenant_id is required"):
            TaskRepository.__new__(TaskRepository).create_task(
                TaskTypeModel.PROCESS_DOCUMENT,
                {"file_path": "/tmp/test.pdf"},
                None,
                1,
            )

    def test_worker_unknown_task_type(self, repo_tenant, repo_user, db_session):
        repo = TaskRepository(db_session)
        task = repo.create_task(
            TaskTypeModel.REFRESH_KNOWLEDGE,
            {},
            repo_tenant.id,
            repo_user.id,
        )

        claimed = repo.claim_task()
        assert claimed is not None
        assert claimed.status == TaskStatusModel.RUNNING.value

        repo.update_task(
            task.public_id,
            status=TaskStatusModel.FAILED,
            error_message="No handler for task type: refresh_knowledge",
        )

        updated = repo.get_task(task.public_id)
        assert updated is not None
        assert updated.status == TaskStatusModel.FAILED.value
        assert "No handler" in updated.error_message


class TestTaskAPI:
    def test_get_task_not_found(self, client):
        response = client.get("/api/v1/tasks/nonexistent")
        assert response.status_code == 404

    def test_list_tasks_empty(self, client):
        response = client.get("/api/v1/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    @patch("tasks.knowledge_tasks.process_document_task")
    def test_task_lifecycle(self, mock_process, client, repo_tenant, repo_user, db_session):
        mock_process.side_effect = lambda task_id: None

        repo = TaskRepository(db_session)
        task = repo.create_task(
            TaskTypeModel.PROCESS_DOCUMENT,
            {"file_path": "/tmp/test.pdf", "document_id": 1},
            repo_tenant.id,
            repo_user.id,
        )

        response = client.get(f"/api/v1/tasks/{task.public_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["tenant_id"] == repo_tenant.id

    def test_task_tenant_isolation_api(self, client, repo_tenant, repo_user, db_session):
        repo = TaskRepository(db_session)
        t1 = repo.create_task(
            TaskTypeModel.PROCESS_DOCUMENT,
            {"file_path": "/tmp/a.pdf"},
            repo_tenant.id,
            repo_user.id,
        )

        response = client.get(f"/api/v1/tasks/{t1.public_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == repo_tenant.id
