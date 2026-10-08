from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.database import Base

if TYPE_CHECKING:
    from models.subscription import TenantSubscription


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    max_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_chats_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    max_embeddings: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    price: Mapped[float] = mapped_column(nullable=False, default=0.0)
    _features: Mapped[str] = mapped_column("features", Text, default="[]", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    subscriptions: Mapped[List["TenantSubscription"]] = relationship(
        "TenantSubscription", back_populates="plan"
    )
