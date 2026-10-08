import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from storage.agent.models import AgentCheckpoint, AgentMessage, AgentSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSessionListItem:
    """One deterministic session-list row with its aggregate message count."""

    session: AgentSession
    message_count: int


@dataclass(frozen=True)
class AgentSessionDeletion:
    """Database effects produced by deleting one scoped conversation."""

    thread_id: str
    messages_deleted: int
    checkpoints_archived: int


class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- Session ----

    def create_session(self, tenant_id: int, user_id: Optional[int], thread_id: str) -> AgentSession:
        session = AgentSession(tenant_id=tenant_id, user_id=user_id, thread_id=thread_id)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(
        self,
        tenant_id: int,
        user_id: Optional[int],
        thread_id: str,
    ) -> Optional[AgentSession]:
        return (
            self.db.query(AgentSession)
            .filter(
                AgentSession.tenant_id == tenant_id,
                AgentSession.user_id == user_id,
                AgentSession.thread_id == thread_id,
            )
            .first()
        )

    def get_or_create_session(self, tenant_id: int, user_id: Optional[int], thread_id: str) -> AgentSession:
        session = self.get_session(tenant_id, user_id, thread_id)
        if session is None:
            session = self.create_session(tenant_id, user_id, thread_id)
        return session

    def list_sessions(
        self,
        tenant_id: int,
        user_id: int,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[AgentSessionListItem], int]:
        """List only the principal's sessions in a stable newest-first order."""

        scope = (
            AgentSession.tenant_id == tenant_id,
            AgentSession.user_id == user_id,
        )
        total = self.db.query(func.count(AgentSession.id)).filter(*scope).scalar() or 0
        rows = (
            self.db.query(AgentSession, func.count(AgentMessage.id))
            .outerjoin(AgentMessage, AgentMessage.session_id == AgentSession.id)
            .filter(*scope)
            .group_by(AgentSession.id)
            .order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return (
            [
                AgentSessionListItem(
                    session=session,
                    message_count=int(message_count),
                )
                for session, message_count in rows
            ],
            int(total),
        )

    def touch_session(self, session: AgentSession):
        session.updated_at = datetime.now(timezone.utc)
        self.db.commit()

    def delete_session(
        self,
        tenant_id: int,
        user_id: int,
        thread_id: str,
    ) -> Optional[AgentSessionDeletion]:
        """Delete one conversation and retain its checkpoints as an archive."""

        session = self.get_session(tenant_id, user_id, thread_id)
        if session is None:
            return None

        messages_deleted = (
            self.db.query(AgentMessage)
            .filter(AgentMessage.session_id == session.id)
            .delete(synchronize_session=False)
        )
        archived_at = datetime.now(timezone.utc)
        checkpoints_archived = (
            self.db.query(AgentCheckpoint)
            .filter(
                AgentCheckpoint.tenant_id == tenant_id,
                AgentCheckpoint.user_id == user_id,
                AgentCheckpoint.thread_id == thread_id,
                AgentCheckpoint.archived_at.is_(None),
            )
            .update(
                {AgentCheckpoint.archived_at: archived_at},
                synchronize_session=False,
            )
        )
        self.db.delete(session)
        self.db.commit()
        return AgentSessionDeletion(
            thread_id=thread_id,
            messages_deleted=messages_deleted,
            checkpoints_archived=checkpoints_archived,
        )

    # ---- Message ----

    def add_message(
        self,
        session_id: int,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentMessage:
        msg = AgentMessage(
            session_id=session_id,
            role=role,
            content=content,
            _metadata=json.dumps(metadata or {}, ensure_ascii=False, default=str),
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def get_messages(self, session_id: int, limit: int = 50) -> List[AgentMessage]:
        return (
            self.db.query(AgentMessage)
            .filter(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.created_at.desc(), AgentMessage.id.desc())
            .limit(limit)
            .all()
        )[::-1]

    def list_messages(
        self,
        session_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[AgentMessage], int]:
        """Page a session transcript in deterministic chronological order."""

        query = self.db.query(AgentMessage).filter(
            AgentMessage.session_id == session_id
        )
        total = query.count()
        messages = (
            query.order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return messages, total

    # ---- Checkpoint ----

    def save_checkpoint(
        self,
        tenant_id: int,
        thread_id: str,
        checkpoint_data: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> AgentCheckpoint:
        cp = AgentCheckpoint(
            tenant_id=tenant_id,
            user_id=user_id,
            thread_id=thread_id,
            checkpoint_data=json.dumps(checkpoint_data, ensure_ascii=False, default=str),
        )
        self.db.add(cp)
        self.db.commit()
        self.db.refresh(cp)
        return cp

    def get_latest_checkpoint(
        self,
        tenant_id: int,
        thread_id: str,
        user_id: Optional[int] = None,
    ) -> Optional[AgentCheckpoint]:
        return (
            self.db.query(AgentCheckpoint)
            .filter(
                AgentCheckpoint.tenant_id == tenant_id,
                AgentCheckpoint.user_id == user_id,
                AgentCheckpoint.thread_id == thread_id,
                AgentCheckpoint.archived_at.is_(None),
            )
            .order_by(
                AgentCheckpoint.created_at.desc(),
                AgentCheckpoint.id.desc(),
            )
            .first()
        )

    def get_checkpoint(self, tenant_id: int, checkpoint_id: int) -> Optional[AgentCheckpoint]:
        return (
            self.db.query(AgentCheckpoint)
            .filter(
                AgentCheckpoint.tenant_id == tenant_id,
                AgentCheckpoint.id == checkpoint_id,
            )
            .first()
        )

    def delete_checkpoints(
        self,
        tenant_id: int,
        thread_id: str,
        user_id: Optional[int] = None,
    ) -> int:
        count = (
            self.db.query(AgentCheckpoint)
            .filter(
                AgentCheckpoint.tenant_id == tenant_id,
                AgentCheckpoint.user_id == user_id,
                AgentCheckpoint.thread_id == thread_id,
            )
            .delete()
        )
        self.db.commit()
        return count
