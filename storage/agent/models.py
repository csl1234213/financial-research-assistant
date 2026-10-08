import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.database import Base


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    thread_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    messages: Mapped[List["AgentMessage"]] = relationship(
        "AgentMessage", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_agent_sessions_tenant_user_thread",
            "tenant_id",
            "user_id",
            "thread_id",
            unique=True,
        ),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    _metadata: Mapped[str] = mapped_column("metadata", Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    session: Mapped["AgentSession"] = relationship("AgentSession", back_populates="messages")

    @property
    def metadata_dict(self) -> Dict[str, Any]:
        return json.loads(self._metadata) if self._metadata else {}

    @metadata_dict.setter
    def metadata_dict(self, value: Dict[str, Any]):
        self._metadata = json.dumps(value, ensure_ascii=False, default=str)


class AgentCheckpoint(Base):
    __tablename__ = "agent_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Checkpoints are keyed by a client-controlled thread ID, so thread_id
    # alone is not a tenant boundary.
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    thread_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    checkpoint_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_agent_checkpoints_tenant_user_thread",
            "tenant_id",
            "user_id",
            "thread_id",
            "created_at",
        ),
    )
