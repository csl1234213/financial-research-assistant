from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.database import Base

if TYPE_CHECKING:
    from models.tenant import Tenant
    from models.user import User


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "uq_documents_tenant_content_sha256",
            "tenant_id",
            "content_sha256",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(128), nullable=False, default="Unknown")
    report_type: Mapped[str] = mapped_column(String(128), nullable=False, default="Financial Report")
    period: Mapped[str] = mapped_column(String(64), nullable=False, default="Unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="indexed")
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=False, index=True
    )
    content_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    byte_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    indexed_chunk_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="documents")
    uploaded_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[uploaded_by_user_id],
    )
