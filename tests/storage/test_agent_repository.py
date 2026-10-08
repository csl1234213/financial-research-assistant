import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from storage.agent.repository import AgentRepository
from storage.database import Base

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


class TestAgentRepository:
    def test_create_session(self, db):
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id=1, user_id=1, thread_id="test_thread_1")
        assert session.id is not None
        assert session.tenant_id == 1
        assert session.user_id == 1
        assert session.thread_id == "test_thread_1"

    def test_get_session(self, db):
        repo = AgentRepository(db)
        repo.create_session(tenant_id=2, user_id=2, thread_id="test_thread_2")
        session = repo.get_session(tenant_id=2, user_id=2, thread_id="test_thread_2")
        assert session is not None
        assert session.tenant_id == 2

    def test_get_or_create_session_creates_new(self, db):
        repo = AgentRepository(db)
        session = repo.get_or_create_session(tenant_id=3, user_id=3, thread_id="new_thread")
        assert session.id is not None
        assert session.thread_id == "new_thread"

    def test_get_or_create_session_returns_existing(self, db):
        repo = AgentRepository(db)
        s1 = repo.get_or_create_session(tenant_id=4, user_id=4, thread_id="existing_thread")
        s2 = repo.get_or_create_session(tenant_id=4, user_id=4, thread_id="existing_thread")
        assert s1.id == s2.id

    def test_add_message(self, db):
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id=5, user_id=5, thread_id="msg_thread")
        msg = repo.add_message(session.id, "user", "分析 NVIDIA")
        assert msg.id is not None
        assert msg.role == "user"
        assert msg.content == "分析 NVIDIA"

    def test_get_messages(self, db):
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id=6, user_id=6, thread_id="msg_thread_2")
        repo.add_message(session.id, "user", "Q1")
        repo.add_message(session.id, "assistant", "A1")
        repo.add_message(session.id, "user", "Q2")
        repo.add_message(session.id, "assistant", "A2")

        messages = repo.get_messages(session.id)
        assert len(messages) == 4
        assert messages[0].role == "user"
        assert messages[0].content == "Q1"
        assert messages[-1].role == "assistant"
        assert messages[-1].content == "A2"

    def test_tenant_isolation(self, db):
        repo = AgentRepository(db)
        repo.create_session(tenant_id=10, user_id=1, thread_id="shared_thread")
        repo.create_session(tenant_id=20, user_id=2, thread_id="shared_thread")

        s10 = repo.get_session(tenant_id=10, user_id=1, thread_id="shared_thread")
        s20 = repo.get_session(tenant_id=20, user_id=2, thread_id="shared_thread")

        assert s10 is not None
        assert s20 is not None
        assert s10.id != s20.id
        assert s10.tenant_id == 10
        assert s20.tenant_id == 20

    def test_user_isolation_within_same_tenant_and_thread(self, db):
        repo = AgentRepository(db)
        first = repo.get_or_create_session(
            tenant_id=30,
            user_id=301,
            thread_id="default",
        )
        second = repo.get_or_create_session(
            tenant_id=30,
            user_id=302,
            thread_id="default",
        )
        repo.add_message(first.id, "user", "first user's private question")

        assert first.id != second.id
        assert repo.get_session(30, 301, "default").id == first.id
        assert repo.get_session(30, 302, "default").id == second.id
        assert repo.get_messages(second.id) == []

    def test_messages_ordered_by_created_at(self, db):
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id=7, user_id=7, thread_id="order_thread")
        repo.add_message(session.id, "user", "M1")
        repo.add_message(session.id, "assistant", "M2")
        repo.add_message(session.id, "user", "M3")

        messages = repo.get_messages(session.id, limit=2)
        assert len(messages) == 2
        assert messages[0].content == "M2"
        assert messages[1].content == "M3"

    def test_message_metadata(self, db):
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id=8, user_id=8, thread_id="meta_thread")
        msg = repo.add_message(
            session.id,
            "assistant",
            "Answer",
            metadata={"tokens": 150, "model": "deepseek"},
        )
        assert msg.metadata_dict == {"tokens": 150, "model": "deepseek"}

    def test_touch_session_updates_timestamp(self, db):
        repo = AgentRepository(db)
        session = repo.create_session(tenant_id=9, user_id=9, thread_id="touch_thread")
        original_updated = session.updated_at
        import time
        time.sleep(0.1)
        repo.touch_session(session)
        assert session.updated_at > original_updated
