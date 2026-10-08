from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.database import Base

if TYPE_CHECKING:
    from models.document import Document
    from models.subscription import TenantSubscription
    from models.task import Task
    from models.usage import UsageRecord
    from models.user import User


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    users: Mapped[List["User"]] = relationship("User", back_populates="tenant")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="tenant")
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="tenant")
    usage_records: Mapped[List["UsageRecord"]] = relationship("UsageRecord", back_populates="tenant")
    subscription: Mapped[Optional["TenantSubscription"]] = relationship(
        "TenantSubscription", back_populates="tenant", uselist=False
    )
