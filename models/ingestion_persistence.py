"""Canonical upload and current-stage persistence; no execution history."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from storage.database import Base


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED','UPLOADING','UPLOADED','VERIFYING','VERIFIED','FINALIZED','FAILED','EXPIRED')",
            name="ck_upload_status",
        ),
        CheckConstraint(
            "expected_size > 0 AND received_size >= 0 AND received_size <= expected_size",
            name="ck_upload_size",
        ),
        CheckConstraint(
            "status <> 'FINALIZED' OR (document_id IS NOT NULL AND task_id IS NOT NULL AND finalized_at IS NOT NULL)",
            name="ck_upload_finalized_binding",
        ),
        CheckConstraint(
            "status NOT IN ('VERIFIED','FINALIZED') OR (verified_sha256 = expected_sha256 "
            "AND verified_sha256 IS NOT NULL AND received_size = expected_size AND verified_at IS NOT NULL)",
            name="ck_upload_verified_integrity",
        ),
        CheckConstraint("protocol IN ('legacy_multipart','tus','s3_multipart')", name="ck_upload_protocol"),
        UniqueConstraint("task_id", name="uq_upload_task_binding"),
    )
    upload_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_size: Mapped[int] = mapped_column(Integer, nullable=False)
    received_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_sha256: Mapped[str | None] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))


class TaskStageCheckpoint(Base):
    __tablename__ = "task_stage_checkpoints"
    __table_args__ = (
        UniqueConstraint("task_id", "stage", name="uq_task_checkpoint_stage"),
        CheckConstraint(
            "stage IN ('PARSING','QUALITY_CHECK','BUILDING_FACTS','BUILDING_TREE','INDEXING')",
            name="ck_checkpoint_stage",
        ),
        CheckConstraint(
            "status IN ('pending','leased','complete','failed','quarantined')",
            name="ck_checkpoint_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_checkpoint_attempts"),
        CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'leased' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_checkpoint_lease",
        ),
        CheckConstraint(
            "status <> 'complete' OR (artifact_id IS NOT NULL AND artifact_sha256 IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="ck_checkpoint_complete_evidence",
        ),
    )
    checkpoint_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(128))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    quality_status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
