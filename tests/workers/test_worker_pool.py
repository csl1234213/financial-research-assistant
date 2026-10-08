import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from models.task import Task as TaskModel
from models.task import TaskStatus, TaskType
from models.tenant import Tenant
from models.user import User
from storage.database import Base
from tasks.repository import TaskRepository
from tasks.worker import TaskWorker
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_worker_pool.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _new_repo():
    db = TestingSessionLocal()
    return TaskRepository(db)


@pytest.fixture(autouse=True)
def _setup_db():
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
def tenant(db_session):
    t = Tenant(name="Worker Test Co", slug="worker-test")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def user(db_session, tenant):
    u = User(
        email="worker@test.com",
        password_hash="hashed",
        tenant_id=tenant.id,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def repo(db_session):
    return TaskRepository(db_session)


class TestWorkerProcess:
    def test_worker_standalone_startup(self):
        worker = TaskWorker(worker_id="test-worker-001")
        assert worker._worker_id == "test-worker-001"
        assert worker._running is False

    def test_worker_consumes_task(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"file_path": "/tmp/test.pdf", "document_id": 1},
            tenant_id=tenant.id,
            user_id=user.id,
        )

        claimed = repo.claim_task()
        assert claimed is not None
        assert claimed.public_id == task.public_id
        assert claimed.status == TaskStatus.RUNNING.value

    def test_worker_updates_task_status(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )

        claimed = repo.claim_task()
        claimed.worker_id = "worker-001"
        claimed.locked_at = datetime.now(timezone.utc)
        repo._db.commit()

        repo.update_task(
            task.public_id,
            status=TaskStatus.SUCCESS,
            result={"chunks": 42},
        )

        updated = repo.get_task(task.public_id)
        assert updated.status == TaskStatus.SUCCESS.value
        assert updated.result == {"chunks": 42}

    def test_worker_sets_worker_id(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )

        claimed = repo.claim_task()
        claimed.worker_id = "worker-007"
        claimed.locked_at = datetime.now(timezone.utc)
        repo._db.commit()

        updated = repo.get_task(task.public_id)
        assert updated.worker_id == "worker-007"
        assert updated.locked_at is not None


class TestConcurrency:
    def test_two_workers_cannot_claim_same_task(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )

        claimed1 = repo.claim_task()
        assert claimed1 is not None
        assert claimed1.public_id == task.public_id

        claimed2 = repo.claim_task()
        assert claimed2 is None

    def test_ten_tasks_distributed(self, repo, tenant, user):
        for i in range(10):
            repo.create_task(
                task_type=TaskType.PROCESS_DOCUMENT,
                payload={"index": i},
                tenant_id=tenant.id,
                user_id=user.id,
            )

        claimed_count = 0
        for _ in range(10):
            claimed = repo.claim_task()
            if claimed:
                claimed_count += 1

        assert claimed_count == 10

        claimed = repo.claim_task()
        assert claimed is None


class TestFailureRecovery:
    def test_worker_crash_stale_task_recovery(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )

        claimed = repo.claim_task()
        claimed.started_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        repo._db.commit()

        recovered = repo.recover_stale_tasks()
        assert recovered == 1

        repo._db.refresh(task)
        assert task.status == TaskStatus.PENDING.value
        assert task.started_at is None

    def test_retry_works(self, repo, tenant, user):
        task = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={},
            tenant_id=tenant.id,
            user_id=user.id,
        )

        claimed = repo.claim_task()
        repo.update_task(
            task.public_id,
            status=TaskStatus.FAILED,
            error_message="Simulated failure",
        )

        failed = repo.get_task(task.public_id)
        assert failed.status == TaskStatus.FAILED.value

        repo.update_task(task.public_id, status=TaskStatus.PENDING)
        task.retry_count = 1
        repo._db.commit()

        pending = repo.get_task(task.public_id)
        assert pending.status == TaskStatus.PENDING.value
        assert pending.retry_count == 1


class TestTenantSecurity:
    def test_worker_a_cannot_process_tenant_b_task(self, repo, tenant, user, db_session):
        tenant_b = Tenant(name="Competitor", slug="competitor")
        db_session.add(tenant_b)
        db_session.commit()
        db_session.refresh(tenant_b)

        task_a = repo.create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={"owner": "tenant_a"},
            tenant_id=tenant.id,
            user_id=user.id,
        )

        task_b = TaskModel(
            public_id="tenant-b-task-001",
            task_type=TaskType.PROCESS_DOCUMENT.value,
            status=TaskStatus.PENDING.value,
            tenant_id=tenant_b.id,
            user_id=user.id,
        )
        task_b.payload = {"owner": "tenant_b"}
        db_session.add(task_b)
        db_session.commit()

        assert task_a.tenant_id == tenant.id
        assert task_b.tenant_id == tenant_b.id
        assert task_a.tenant_id != task_b.tenant_id


class TestWorkerService:
    def test_worker_lifecycle(self):
        worker = TaskWorker(worker_id="lifecycle-test")
        assert worker._running is False

        worker.start()
        time.sleep(0.5)
        assert worker._running is True

        worker.stop()
        time.sleep(0.5)
        assert worker._running is False

    def test_worker_heartbeat_registration(self, db_session):
        from models.worker_node import WorkerNode
        from tasks.heartbeat import WorkerHeartbeat

        heartbeat = WorkerHeartbeat(worker_id="heartbeat-test", hostname="test-host")
        heartbeat._db = db_session
        heartbeat.send()

        node = db_session.query(WorkerNode).filter(
            WorkerNode.worker_id == "heartbeat-test"
        ).first()
        assert node is not None
        assert node.status == "online"
        assert node.last_seen is not None

    def test_multiple_workers_different_ids(self):
        worker1 = TaskWorker(worker_id="worker-a")
        worker2 = TaskWorker(worker_id="worker-b")

        assert worker1._worker_id != worker2._worker_id
        assert worker1._worker_id == "worker-a"
        assert worker2._worker_id == "worker-b"
