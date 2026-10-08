import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import app
from auth.dependencies import get_current_user
from models.task import TaskStatus, TaskType
from models.tenant import Tenant
from models.user import User
from storage.database import Base, get_db
from tasks.repository import TaskRepository
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database(
    "test_task_persistence.db"
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists(TEST_DATABASE_URL.replace("sqlite:///", "")):
        try:
            os.remove(TEST_DATABASE_URL.replace("sqlite:///", ""))
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
def repo(db_session):
    return TaskRepository(db_session)


@pytest.fixture
def tenant(db_session):
    t = Tenant(name="Test Tenant", slug="test")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def user(db_session, tenant):
    u = User(email="test@test.com", password_hash="hash", tenant_id=tenant.id)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def client(user):
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestTaskModel:
    def test_create_task(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/test.pdf"},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        assert task.id is not None
        assert task.public_id is not None
        assert task.task_type == TaskType.PROCESS_DOCUMENT.value
        assert task.status == TaskStatus.PENDING.value
        assert task.tenant_id == tenant.id
        assert task.user_id == user.id
        assert task.payload == {"file_path": "/tmp/test.pdf"}

    def test_task_tenant_relation(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        assert task.tenant_id == tenant.id
        assert task.tenant is not None
        assert task.tenant.id == tenant.id

    def test_task_user_relation(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        assert task.user_id == user.id
        assert task.user is not None
        assert task.user.id == user.id

    def test_create_task_requires_tenant_id(self, repo, user):
        with pytest.raises(ValueError, match="tenant_id is required"):
            repo.create_task(
                task_type=TaskType.PROCESS_DOCUMENT,
                payload={},
                tenant_id=None,
                user_id=user.id,
            )

    def test_payload_json_serialization(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"nested": {"key": "value"}, "list": [1, 2, 3]},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        assert task.payload == {"nested": {"key": "value"}, "list": [1, 2, 3]}


class TestTaskRepository:
    def test_claim_task(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        claimed = repo.claim_task()
        assert claimed is not None
        assert claimed.status == TaskStatus.RUNNING.value

    def test_claim_task_no_pending(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        repo.claim_task()
        claimed = repo.claim_task()
        assert claimed is None

    def test_update_task(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        updated = repo.update_task(
            task.public_id,
            status=TaskStatus.RUNNING,
            progress=50,
        )
        assert updated is not None
        assert updated.status == TaskStatus.RUNNING.value
        assert updated.progress == 50

    def test_update_task_error(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )
        updated = repo.update_task(
            task.public_id,
            status=TaskStatus.FAILED,
            error_message="Something went wrong",
        )
        assert updated.status == TaskStatus.FAILED.value
        assert updated.error_message == "Something went wrong"

    def test_list_tasks(self, repo, tenant, user):
        repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        result = repo.list_tasks(tenant_id=tenant.id)
        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_list_tasks_tenant_isolation(self, repo, tenant, user, db_session):
        t2 = Tenant(name="Tenant 2", slug="tenant2")
        db_session.add(t2)
        db_session.commit()
        u2 = User(email="u2@test.com", password_hash="hash", tenant_id=t2.id)
        db_session.add(u2)
        db_session.commit()

        repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        repo.create_task(TaskType.PROCESS_DOCUMENT, {}, t2.id, u2.id)

        result = repo.list_tasks(tenant_id=tenant.id)
        assert result["total"] == 1

    def test_list_tasks_pagination(self, repo, tenant, user):
        for i in range(5):
            repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)

        result = repo.list_tasks(tenant_id=tenant.id, page=1, size=2)
        assert result["total"] == 5
        assert len(result["items"]) == 2
        assert result["page"] == 1
        assert result["size"] == 2

    def test_list_tasks_by_status(self, repo, tenant, user):
        task = repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        repo.update_task(task.public_id, status=TaskStatus.RUNNING)

        result = repo.list_tasks(tenant_id=tenant.id, status="running")
        assert result["total"] == 1

    def test_recover_stale_tasks(self, repo, tenant, user, db_session):
        task = repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        task.status = TaskStatus.RUNNING.value
        task.started_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        db_session.commit()

        recovered = repo.recover_stale_tasks()
        assert recovered == 1

        db_session.refresh(task)
        assert task.status == TaskStatus.PENDING.value

    def test_delete_task(self, repo, tenant, user):
        task = repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        assert repo.delete_task(task.public_id) is True
        assert repo.get_task(task.public_id) is None


class TestTaskAPI:
    def test_get_task(self, repo, tenant, user, client):
        task = repo.create_task(
            TaskType.PROCESS_DOCUMENT,
            {"file_path": "/tmp/test.pdf"},
            tenant.id,
            user.id,
        )
        response = client.get(f"/api/v1/tasks/{task.public_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == task.public_id
        assert data["status"] == "pending"
        assert data["tenant_id"] == tenant.id

    def test_get_task_not_found(self, client):
        response = client.get("/api/v1/tasks/nonexistent")
        assert response.status_code == 404

    def test_list_tasks(self, repo, tenant, user, client):
        repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        response = client.get("/api/v1/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert "items" in data
        assert "page" in data
        assert "size" in data

    def test_list_tasks_pagination(self, repo, tenant, user, client):
        for i in range(5):
            repo.create_task(TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id)
        response = client.get("/api/v1/tasks?page=1&size=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["size"] == 2

    def test_unauthorized_request(self):
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as test_client:
            response = test_client.get("/api/v1/tasks/nonexistent")
        app.dependency_overrides.clear()
        assert response.status_code == 401

    def test_task_endpoint_rejects_another_tenants_task(self, client, db_session, tenant, user):
        other_tenant = Tenant(name="Other tenant", slug="other-tenant")
        db_session.add(other_tenant)
        db_session.flush()
        other_user = User(
            email="other-tenant@example.com",
            password_hash="hash",
            tenant_id=other_tenant.id,
        )
        db_session.add(other_user)
        db_session.commit()

        hidden_task = TaskRepository(db_session).create_task(
            TaskType.PROCESS_DOCUMENT,
            {},
            other_tenant.id,
            other_user.id,
        )
        response = client.get(f"/api/v1/tasks/{hidden_task.public_id}")
        assert response.status_code == 403


class TestWorker:
    @patch("tasks.knowledge_tasks.process_document_task")
    def test_pending_to_running_flow(self, mock_process, repo, tenant, user, db_session):
        mock_process.return_value = None

        task = repo.create_task(
            TaskType.PROCESS_DOCUMENT,
            {"file_path": "/tmp/test.pdf", "document_id": 1},
            tenant.id,
            user.id,
        )

        claimed = repo.claim_task()
        assert claimed is not None
        assert claimed.status == TaskStatus.RUNNING.value
        assert claimed.started_at is not None
        assert claimed.public_id == task.public_id

    def test_running_to_success(self, repo, tenant, user):
        task = repo.create_task(
            TaskType.PROCESS_DOCUMENT,
            {"file_path": "/tmp/test.pdf"},
            tenant.id,
            user.id,
        )
        repo.claim_task()
        updated = repo.update_task(
            task.public_id,
            status=TaskStatus.SUCCESS,
            progress=100,
            result={"chunks": 10},
        )
        assert updated.status == TaskStatus.SUCCESS.value
        assert updated.progress == 100
        assert updated.completed_at is not None
        assert updated.result == {"chunks": 10}

    def test_failed_task_update(self, repo, tenant, user):
        task = repo.create_task(
            TaskType.PROCESS_DOCUMENT, {}, tenant.id, user.id
        )
        repo.claim_task()
        updated = repo.update_task(
            task.public_id,
            status=TaskStatus.FAILED,
            error_message="File not found",
        )
        assert updated.status == TaskStatus.FAILED.value
        assert updated.error_message == "File not found"
        assert updated.completed_at is not None
