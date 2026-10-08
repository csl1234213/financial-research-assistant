"""Scope agent checkpoints by tenant.

Revision ID: 20260726_01
Revises:
Create Date: 2026-07-26

Legacy checkpoint rows did not carry a tenant identifier.  The migration uses
the most recently active matching agent session where one exists; ambiguous or
orphaned legacy rows are assigned tenant 0, which is not used for authenticated
agent sessions.  This deliberately favors non-disclosure over availability.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_01"
down_revision: Union[str, None] = "20260726_00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_checkpoints" not in inspector.get_table_names():
        return
    if "tenant_id" in _column_names(bind, "agent_checkpoints"):
        return

    with op.batch_alter_table("agent_checkpoints") as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE agent_checkpoints
        SET tenant_id = COALESCE(
            (
                SELECT tenant_id
                FROM agent_sessions
                WHERE agent_sessions.thread_id = agent_checkpoints.thread_id
                ORDER BY agent_sessions.updated_at DESC
                LIMIT 1
            ),
            0
        )
        WHERE tenant_id IS NULL
        """
    )

    with op.batch_alter_table("agent_checkpoints") as batch_op:
        batch_op.alter_column("tenant_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(
            "ix_agent_checkpoints_tenant_thread",
            ["tenant_id", "thread_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_checkpoints" not in inspector.get_table_names():
        return
    columns = _column_names(bind, "agent_checkpoints")
    if "tenant_id" not in columns:
        return

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("agent_checkpoints")}
    with op.batch_alter_table("agent_checkpoints") as batch_op:
        if "ix_agent_checkpoints_tenant_thread" in indexes:
            batch_op.drop_index("ix_agent_checkpoints_tenant_thread")
        batch_op.drop_column("tenant_id")
