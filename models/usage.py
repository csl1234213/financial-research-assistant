import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.database import Base

if TYPE_CHECKING:
    from models.tenant import Tenant
    from models.user import User


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="generic"
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    _meta: Mapped[str] = mapped_column("meta", Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="usage_records")
    user: Mapped["User"] = relationship("User", back_populates="usage_records")

    @property
    def meta(self) -> Dict[str, Any]:
        try:
            return json.loads(self._meta)
        except (json.JSONDecodeError, TypeError):
            return {}

    @meta.setter
    def meta(self, value: Dict[str, Any]) -> None:
        self._meta = json.dumps(value, ensure_ascii=False)
