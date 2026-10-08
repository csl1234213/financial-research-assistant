"""Add tenant-scoped document fingerprints and indexing metadata.

Revision ID: 20260729_07
Revises: 20260729_06
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_07"
down_revision: Union[str, None] = "20260729_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All new columns remain nullable so existing deployments can migrate
    # without inventing checksums or uploader identities for legacy rows.
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column("content_sha256", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("byte_size", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("indexed_chunk_count", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_documents_uploaded_by_user_id_users",
            "users",
            ["uploaded_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_documents_uploaded_by_user_id",
            ["uploaded_by_user_id"],
            unique=False,
        )
        batch_op.create_index(
            "uq_documents_tenant_content_sha256",
            ["tenant_id", "content_sha256"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("uq_documents_tenant_content_sha256")
        batch_op.drop_index("ix_documents_uploaded_by_user_id")
        batch_op.drop_constraint(
            "fk_documents_uploaded_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("indexed_chunk_count")
        batch_op.drop_column("uploaded_by_user_id")
        batch_op.drop_column("byte_size")
        batch_op.drop_column("content_sha256")
