"""Add encrypted, user-scoped LLM provider settings.

Revision ID: 20260729_04
Revises: 20260726_03
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_04"
down_revision: Union[str, None] = "20260726_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(length=4), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("revision", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "provider",
            name="uq_llm_provider_settings_principal_provider",
        ),
    )
    op.create_index(
        "ix_llm_provider_settings_tenant_id",
        "llm_provider_settings",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_llm_provider_settings_user_id",
        "llm_provider_settings",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_provider_settings_user_id",
        table_name="llm_provider_settings",
    )
    op.drop_index(
        "ix_llm_provider_settings_tenant_id",
        table_name="llm_provider_settings",
    )
    op.drop_table("llm_provider_settings")
