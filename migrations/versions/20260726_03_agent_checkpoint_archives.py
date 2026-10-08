"""Add auditable Agent checkpoint archival state.

Revision ID: 20260726_03
Revises: 20260726_02
Create Date: 2026-07-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_03"
down_revision: Union[str, None] = "20260726_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "agent_checkpoints" not in sa.inspect(bind).get_table_names():
        return
    if "archived_at" in _column_names(bind, "agent_checkpoints"):
        return

    with op.batch_alter_table("agent_checkpoints") as batch_op:
        batch_op.add_column(
            sa.Column(
                "archived_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "agent_checkpoints" not in sa.inspect(bind).get_table_names():
        return
    if "archived_at" not in _column_names(bind, "agent_checkpoints"):
        return

    with op.batch_alter_table("agent_checkpoints") as batch_op:
        batch_op.drop_column("archived_at")
