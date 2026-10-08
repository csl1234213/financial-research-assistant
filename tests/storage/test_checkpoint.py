import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import models.tenant  # noqa: F401
import models.user  # noqa: F401
from models.tenant import Tenant
from storage.agent.checkpoint import PostgresSaver
from storage.agent.repository import AgentRepository
from storage.database import Base
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_checkpoint.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def cleanup():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_db = TestingSessionLocal()
    try:
        seed_db.add_all(
            [
                Tenant(id=1, name="Checkpoint Tenant A", slug="checkpoint-a"),
                Tenant(id=2, name="Checkpoint Tenant B", slug="checkpoint-b"),
            ]
        )
        seed_db.commit()
    finally:
        seed_db.close()

    yield

    Base.metadata.drop_all(bind=engine)
    db_path = TEST_DATABASE_URL.replace("sqlite:///", "")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except (PermissionError, OSError):
            pass


class TestPostgresSaver:
    def test_put_and_get_checkpoint(self, db):
        saver = PostgresSaver(db, tenant_id=1)
        config = {"configurable": {"thread_id": "cp_test_1"}}
        checkpoint = {"answer": "NVIDIA analysis", "tools_used": ["search"]}
        metadata = {"source": "agent"}

        result = saver.put(config, checkpoint, metadata)
        assert result["configurable"]["thread_id"] == "cp_test_1"
        assert "checkpoint_id" in result["configurable"]

        restored = saver.get(config)
        assert restored is not None
        assert restored["checkpoint"]["answer"] == "NVIDIA analysis"
        assert restored["checkpoint"]["tools_used"] == ["search"]
        assert restored["metadata"]["source"] == "agent"

    def test_get_nonexistent_checkpoint(self, db):
        saver = PostgresSaver(db, tenant_id=1)
        config = {"configurable": {"thread_id": "nonexistent_thread"}}
        assert saver.get(config) is None

    def test_multiple_checkpoints_for_same_thread(self, db):
        saver = PostgresSaver(db, tenant_id=1)
        config = {"configurable": {"thread_id": "multi_cp_thread"}}

        saver.put(config, {"step": 1}, {"iteration": 1})
        saver.put(config, {"step": 2}, {"iteration": 2})
        saver.put(config, {"step": 3}, {"iteration": 3})

        latest = saver.get(config)
        assert latest is not None
        assert latest["checkpoint"]["step"] == 3

    def test_checkpoint_persistence_across_instances(self, db):
        saver1 = PostgresSaver(db, tenant_id=1)
        config = {"configurable": {"thread_id": "persist_test"}}
        saver1.put(config, {"data": "persistent"}, {})

        saver2 = PostgresSaver(db, tenant_id=1)
        restored = saver2.get(config)
        assert restored is not None
        assert restored["checkpoint"]["data"] == "persistent"

    def test_extract_thread_id_from_config(self, db):
        saver = PostgresSaver(db, tenant_id=1)
        assert saver._extract_thread_id({"configurable": {"thread_id": "my_thread"}}) == "my_thread"

    def test_extract_thread_id_default(self, db):
        saver = PostgresSaver(db, tenant_id=1)
        assert saver._extract_thread_id({}) == "default"

    def test_tenant_isolation_checkpoints(self, db):
        saver_a = PostgresSaver(db, tenant_id=1)
        saver_b = PostgresSaver(db, tenant_id=2)
        config = {"configurable": {"thread_id": "iso_thread"}}

        saver_a.put(config, {"owner": "tenant_1"}, {})
        saver_b.put(config, {"owner": "tenant_2"}, {})

        repo = AgentRepository(db)
        checkpoints_a = repo.get_latest_checkpoint(1, "iso_thread")
        checkpoints_b = repo.get_latest_checkpoint(2, "iso_thread")
        assert checkpoints_a is not None
        assert checkpoints_b is not None
        assert json.loads(checkpoints_a.checkpoint_data)["checkpoint"]["owner"] == "tenant_1"
        assert json.loads(checkpoints_b.checkpoint_data)["checkpoint"]["owner"] == "tenant_2"

    def test_user_isolation_checkpoints_within_tenant(self, db):
        config = {"configurable": {"thread_id": "default"}}
        saver_a = PostgresSaver(db, tenant_id=1, user_id=101)
        saver_b = PostgresSaver(db, tenant_id=1, user_id=102)

        saver_a.put(config, {"owner": "user_101"}, {})
        saver_b.put(config, {"owner": "user_102"}, {})

        assert saver_a.get(config)["checkpoint"]["owner"] == "user_101"
        assert saver_b.get(config)["checkpoint"]["owner"] == "user_102"

    def test_put_writes_noop(self, db):
        saver = PostgresSaver(db, tenant_id=1)
        saver.put_writes({"configurable": {"thread_id": "t"}}, [], "task_1")
