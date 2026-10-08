"""Add a user-scoped default LLM provider.

Revision ID: 20260729_06
Revises: 20260729_05
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_06"
down_revision: Union[str, None] = "20260729_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_provider_settings",
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE llm_provider_settings
            SET is_default = true
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY tenant_id, user_id
                            ORDER BY
                                CASE WHEN provider = 'deepseek' THEN 0 ELSE 1 END,
                                created_at,
                                id
                        ) AS row_number
                    FROM llm_provider_settings
                ) AS ranked_settings
                WHERE row_number = 1
            )
            """
        )
    )
    op.create_index(
        "uq_llm_provider_settings_principal_default",
        "llm_provider_settings",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_llm_provider_settings_principal_default",
        table_name="llm_provider_settings",
    )
    op.drop_column("llm_provider_settings", "is_default")
