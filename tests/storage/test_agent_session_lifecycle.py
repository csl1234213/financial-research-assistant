from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from storage.agent.models import AgentCheckpoint, AgentSession
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


def test_list_sessions_is_principal_scoped_paginated_and_deterministic(db):
    repo = AgentRepository(db)
    first = repo.create_session(1, 10, "first")
    second = repo.create_session(1, 10, "second")
    repo.create_session(1, 11, "other-user")
    repo.create_session(2, 10, "other-tenant")
    repo.add_message(first.id, "user", "question")
    repo.add_message(first.id, "assistant", "answer")

    same_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first.updated_at = same_time
    second.updated_at = same_time
    db.commit()

    rows, total = repo.list_sessions(1, 10, limit=1, offset=0)
    assert total == 2
    assert [row.session.thread_id for row in rows] == ["second"]
    assert rows[0].message_count == 0

    rows, total = repo.list_sessions(1, 10, limit=1, offset=1)
    assert total == 2
    assert [row.session.thread_id for row in rows] == ["first"]
    assert rows[0].message_count == 2


def test_list_messages_is_chronological_and_reports_total(db):
    repo = AgentRepository(db)
    session = repo.create_session(1, 10, "transcript")
    repo.add_message(session.id, "user", "one")
    repo.add_message(session.id, "assistant", "two")
    repo.add_message(session.id, "user", "three")

    messages, total = repo.list_messages(session.id, limit=2, offset=1)

    assert total == 3
    assert [message.content for message in messages] == ["two", "three"]


def test_delete_session_archives_only_scoped_checkpoints(db):
    repo = AgentRepository(db)
    owned = repo.create_session(1, 10, "shared")
    other_user = repo.create_session(1, 11, "shared")
    other_tenant = repo.create_session(2, 10, "shared")
    repo.add_message(owned.id, "user", "private")
    repo.add_message(other_user.id, "user", "other user")
    repo.add_message(other_tenant.id, "user", "other tenant")
    owned_checkpoint = repo.save_checkpoint(1, "shared", {"step": 1}, user_id=10)
    other_checkpoint = repo.save_checkpoint(1, "shared", {"step": 2}, user_id=11)
    tenant_checkpoint = repo.save_checkpoint(2, "shared", {"step": 3}, user_id=10)

    result = repo.delete_session(1, 10, "shared")

    assert result is not None
    assert result.messages_deleted == 1
    assert result.checkpoints_archived == 1
    assert repo.get_session(1, 10, "shared") is None
    assert repo.get_session(1, 11, "shared") is not None
    assert repo.get_session(2, 10, "shared") is not None
    assert db.get(AgentCheckpoint, owned_checkpoint.id).archived_at is not None
    assert db.get(AgentCheckpoint, other_checkpoint.id).archived_at is None
    assert db.get(AgentCheckpoint, tenant_checkpoint.id).archived_at is None
    assert repo.get_latest_checkpoint(1, "shared", user_id=10) is None


def test_delete_nonexistent_session_is_a_noop(db):
    repo = AgentRepository(db)

    assert repo.delete_session(1, 10, "missing") is None
    assert db.query(AgentSession).count() == 0
