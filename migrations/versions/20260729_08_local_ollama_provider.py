"""Allow user-scoped local Ollama endpoint settings without API keys.

Revision ID: 20260729_08
Revises: 20260729_07
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_08"
down_revision: Union[str, None] = "20260729_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_provider_settings",
        sa.Column("base_url", sa.String(length=512), nullable=True),
    )
    with op.batch_alter_table("llm_provider_settings") as batch_op:
        batch_op.alter_column(
            "encrypted_api_key",
            existing_type=sa.Text(),
            nullable=True,
        )
        batch_op.alter_column(
            "key_hint",
            existing_type=sa.String(length=4),
            nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    null_key_rows = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM llm_provider_settings "
            "WHERE encrypted_api_key IS NULL OR key_hint IS NULL"
        )
    ).scalar_one()
    if null_key_rows:
        raise RuntimeError(
            "Cannot downgrade while a keyless local provider setting exists"
        )
    with op.batch_alter_table("llm_provider_settings") as batch_op:
        batch_op.alter_column(
            "key_hint",
            existing_type=sa.String(length=4),
            nullable=False,
        )
        batch_op.alter_column(
            "encrypted_api_key",
            existing_type=sa.Text(),
            nullable=False,
        )
    op.drop_column("llm_provider_settings", "base_url")
