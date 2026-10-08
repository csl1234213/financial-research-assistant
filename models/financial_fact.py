"""Relational persistence models for source-backed financial facts."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from storage.database import Base
from storage.types import ExactFinancialDecimal


class FinancialFactIngestionRun(Base):
    __tablename__ = "financial_fact_ingestion_runs"
    __table_args__ = (Index("ix_financial_fact_runs_tenant_document", "tenant_id", "document_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    rows_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_mapped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_conflicted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinancialFactRecord(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint("document_id", "fact_id", name="uq_financial_facts_document_fact"),
        Index("ix_financial_facts_tenant_metric_year_scope", "tenant_id", "canonical_metric", "fiscal_year", "scope"),
        Index("ix_financial_facts_tenant_company_metric", "tenant_id", "company_id", "canonical_metric"),
        Index("ix_financial_facts_document_version", "tenant_id", "document_id", "document_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(String(40), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[str] = mapped_column(String(128), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    accounting_standard: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_metric: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_label: Mapped[str] = mapped_column(String(255), nullable=False)
    original_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    statement_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fiscal_year: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fiscal_quarter: Mapped[str | None] = mapped_column(String(16), nullable=True)
    period_type: Mapped[str] = mapped_column(String(24), nullable=False)
    period_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_end: Mapped[str | None] = mapped_column(String(32), nullable=True)
    document_reporting_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fact_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    statement_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_row_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_column_period: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value: Mapped[Decimal] = mapped_column(ExactFinancialDecimal(), nullable=False)
    normalized_value: Mapped[Decimal] = mapped_column(ExactFinancialDecimal(), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    source_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(128), nullable=True)
    table_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chunk_id: Mapped[str] = mapped_column(String(512), nullable=False)
    document: Mapped[str] = mapped_column(String(512), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    mapping_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    row_verification_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    derivation: Mapped[str] = mapped_column(String(64), nullable=False, default="direct")
    growth_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False, default=Decimal("1"))
    dimension: Mapped[str | None] = mapped_column(String(128), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    structured_identity: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    ingestion_run_id: Mapped[str] = mapped_column(
        ForeignKey("financial_fact_ingestion_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class FinancialFactConflictRecord(Base):
    __tablename__ = "financial_fact_conflicts"
    __table_args__ = (Index("ix_financial_fact_conflicts_tenant_fact", "tenant_id", "fact_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("financial_fact_ingestion_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    document_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_id: Mapped[str] = mapped_column(String(40), nullable=False)
    identity: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    existing_value: Mapped[Decimal | None] = mapped_column(ExactFinancialDecimal(), nullable=True)
    incoming_value: Mapped[Decimal | None] = mapped_column(ExactFinancialDecimal(), nullable=True)
    existing_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    incoming_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )
