"""Migrate stored DeepSeek settings to the supported V4 model IDs.

Revision ID: 20260729_05
Revises: 20260729_04
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_05"
down_revision: Union[str, None] = "20260729_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE llm_provider_settings
            SET model = 'deepseek-v4-flash',
                updated_at = CURRENT_TIMESTAMP
            WHERE provider = 'deepseek'
              AND model IN (
                  'deepseek-chat',
                  'deepseek-reasoner',
                  'deepseek-coder'
              )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE llm_provider_settings
            SET model = 'deepseek-chat',
                updated_at = CURRENT_TIMESTAMP
            WHERE provider = 'deepseek'
              AND model IN (
                  'deepseek-v4-flash',
                  'deepseek-v4-pro'
              )
            """
        )
    )
