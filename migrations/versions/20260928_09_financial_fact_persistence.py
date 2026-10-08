"""Persist tenant-scoped canonical financial facts and ingestion audits.

Revision ID: 20260928_09
Revises: 20260729_08
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


def _financial_amount_type():
    if op.get_bind().dialect.name == "sqlite":
        return sa.String(length=80)
    return sa.Numeric(precision=38, scale=12)


revision: str = "20260928_09"
down_revision: Union[str, None] = "20260729_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "financial_fact_ingestion_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("document_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rows_seen", sa.Integer(), nullable=False),
        sa.Column("rows_verified", sa.Integer(), nullable=False),
        sa.Column("rows_mapped", sa.Integer(), nullable=False),
        sa.Column("facts_eligible", sa.Integer(), nullable=False),
        sa.Column("facts_inserted", sa.Integer(), nullable=False),
        sa.Column("facts_unchanged", sa.Integer(), nullable=False),
        sa.Column("facts_conflicted", sa.Integer(), nullable=False),
        sa.Column("facts_rejected", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_financial_fact_runs_tenant_document",
        "financial_fact_ingestion_runs",
        ["tenant_id", "document_id"],
    )

    op.create_table(
        "financial_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fact_id", sa.String(length=40), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("document_version", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.String(length=128), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("accounting_standard", sa.String(length=32), nullable=False),
        sa.Column("canonical_metric", sa.String(length=128), nullable=False),
        sa.Column("metric_label", sa.String(length=255), nullable=False),
        sa.Column("original_label", sa.String(length=512), nullable=True),
        sa.Column("normalized_label", sa.String(length=512), nullable=True),
        sa.Column("statement_type", sa.String(length=64), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=True),
        sa.Column("fiscal_year", sa.String(length=16), nullable=True),
        sa.Column("fiscal_quarter", sa.String(length=16), nullable=True),
        sa.Column("period_type", sa.String(length=24), nullable=False),
        sa.Column("period_start", sa.String(length=32), nullable=True),
        sa.Column("period_end", sa.String(length=32), nullable=True),
        sa.Column("document_reporting_period", sa.String(length=64), nullable=True),
        sa.Column("fact_period", sa.String(length=64), nullable=True),
        sa.Column("statement_period", sa.String(length=64), nullable=True),
        sa.Column("table_row_period", sa.String(length=64), nullable=True),
        sa.Column("table_column_period", sa.String(length=128), nullable=True),
        sa.Column("value", _financial_amount_type(), nullable=False),
        sa.Column("normalized_value", _financial_amount_type(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=False),
        sa.Column("source_unit", sa.String(length=64), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=128), nullable=True),
        sa.Column("table_id", sa.String(length=255), nullable=True),
        sa.Column("row_id", sa.String(length=128), nullable=True),
        sa.Column("chunk_id", sa.String(length=512), nullable=False),
        sa.Column("document", sa.String(length=512), nullable=False),
        sa.Column("source_locator", sa.String(length=512), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("mapping_status", sa.String(length=24), nullable=True),
        sa.Column("mapping_rule", sa.String(length=255), nullable=True),
        sa.Column("row_verification_status", sa.String(length=24), nullable=True),
        sa.Column("source_kind", sa.String(length=64), nullable=True),
        sa.Column("created_from", sa.String(length=64), nullable=True),
        sa.Column("derivation", sa.String(length=64), nullable=False),
        sa.Column("growth_basis", sa.String(length=64), nullable=True),
        sa.Column("display_unit", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=8, scale=7), nullable=False),
        sa.Column("dimension", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("structured_identity", sa.JSON(), nullable=False),
        sa.Column("ingestion_run_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["financial_fact_ingestion_runs.run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "fact_id", name="uq_financial_facts_document_fact"),
    )
    op.create_index(
        "ix_financial_facts_tenant_metric_year_scope",
        "financial_facts",
        ["tenant_id", "canonical_metric", "fiscal_year", "scope"],
    )
    op.create_index(
        "ix_financial_facts_tenant_company_metric",
        "financial_facts",
        ["tenant_id", "company_id", "canonical_metric"],
    )
    op.create_index(
        "ix_financial_facts_document_version",
        "financial_facts",
        ["tenant_id", "document_id", "document_version"],
    )

    op.create_table(
        "financial_fact_conflicts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("document_version", sa.String(length=64), nullable=False),
        sa.Column("fact_id", sa.String(length=40), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("existing_value", _financial_amount_type(), nullable=True),
        sa.Column("incoming_value", _financial_amount_type(), nullable=True),
        sa.Column("existing_provenance", sa.JSON(), nullable=True),
        sa.Column("incoming_provenance", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["financial_fact_ingestion_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_fact_conflicts_tenant_fact",
        "financial_fact_conflicts",
        ["tenant_id", "fact_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_financial_fact_conflicts_tenant_fact", table_name="financial_fact_conflicts")
    op.drop_table("financial_fact_conflicts")
    op.drop_index("ix_financial_facts_document_version", table_name="financial_facts")
    op.drop_index("ix_financial_facts_tenant_company_metric", table_name="financial_facts")
    op.drop_index("ix_financial_facts_tenant_metric_year_scope", table_name="financial_facts")
    op.drop_table("financial_facts")
    op.drop_index("ix_financial_fact_runs_tenant_document", table_name="financial_fact_ingestion_runs")
    op.drop_table("financial_fact_ingestion_runs")
