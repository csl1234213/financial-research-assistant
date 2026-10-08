import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from observability.serialization import to_json_safe
from storage.database import Base

if TYPE_CHECKING:
    from models.tenant import Tenant
    from models.user import User


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    thread_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    _metadata: Mapped[str] = mapped_column("metadata", Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    spans: Mapped[List["AgentSpan"]] = relationship(
        "AgentSpan", back_populates="trace", cascade="all, delete-orphan"
    )
    tenant: Mapped["Tenant"] = relationship("Tenant")
    user: Mapped["User"] = relationship("User")

    @property
    def meta(self) -> Dict[str, Any]:
        try:
            value = json.loads(self._metadata)
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @meta.setter
    def meta(self, value: Mapping[str, Any]) -> None:
        self._metadata = json.dumps(to_json_safe(value), ensure_ascii=False, sort_keys=True)


class AgentSpan(Base):
    __tablename__ = "agent_spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[int] = mapped_column(
        ForeignKey("agent_traces.id"), nullable=False, index=True
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    _metadata: Mapped[str] = mapped_column("metadata", Text, default="{}", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    trace: Mapped["AgentTrace"] = relationship("AgentTrace", back_populates="spans")

    @property
    def meta(self) -> Dict[str, Any]:
        try:
            value = json.loads(self._metadata)
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    @meta.setter
    def meta(self, value: Mapping[str, Any]) -> None:
        self._metadata = json.dumps(to_json_safe(value), ensure_ascii=False, sort_keys=True)
