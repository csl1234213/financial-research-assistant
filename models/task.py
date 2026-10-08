import json
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.database import Base

if TYPE_CHECKING:
    from models.tenant import Tenant
    from models.user import User


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TaskType(str, Enum):
    PROCESS_DOCUMENT = "process_document"
    FORMAL_READY_DOCUMENT = "formal_ready_document"
    REFRESH_KNOWLEDGE = "refresh_knowledge"
    AGENT_TASK = "agent_task"


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "dispatch_state IN ('none', 'pending', 'leased', 'delivered', 'failed')",
            name="ck_task_dispatch_state",
        ),
        CheckConstraint("dispatch_attempt_count >= 0", name="ck_task_dispatch_attempts"),
        CheckConstraint(
            "(dispatch_state = 'leased' AND dispatch_lease_token IS NOT NULL "
            "AND dispatch_lease_expires_at IS NOT NULL) OR (dispatch_state <> 'leased' "
            "AND dispatch_lease_token IS NULL AND dispatch_lease_expires_at IS NULL)",
            name="ck_task_dispatch_lease",
        ),
        Index("ix_tasks_dispatch_due", "dispatch_state", "dispatch_next_attempt_at", "dispatch_lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TaskStatus.PENDING.value, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    _payload: Mapped[str] = mapped_column("payload", Text, default="{}", nullable=False)
    _result: Mapped[str] = mapped_column("result", Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 派发义务与执行状态正交；历史任务默认不产生新的消息。
    dispatch_state: Mapped[str] = mapped_column(String(20), default="none", server_default="none", nullable=False)
    dispatch_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    dispatch_lease_token: Mapped[Optional[str]] = mapped_column(String(32))
    dispatch_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispatch_next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispatch_error_code: Mapped[Optional[str]] = mapped_column(String(64))

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="tasks")
    user: Mapped["User"] = relationship("User", back_populates="tasks")

    @property
    def payload(self) -> Dict[str, Any]:
        try:
            return json.loads(self._payload)
        except (json.JSONDecodeError, TypeError):
            return {}

    @payload.setter
    def payload(self, value: Dict[str, Any]) -> None:
        self._payload = json.dumps(value, ensure_ascii=False)

    @property
    def result(self) -> Dict[str, Any]:
        try:
            return json.loads(self._result)
        except (json.JSONDecodeError, TypeError):
            return {}

    @result.setter
    def result(self, value: Dict[str, Any]) -> None:
        self._result = json.dumps(value, ensure_ascii=False)
