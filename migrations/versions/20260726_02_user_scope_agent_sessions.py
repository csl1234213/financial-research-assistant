"""Scope agent sessions and checkpoint archives by user.

Revision ID: 20260726_02
Revises: 20260726_01
Create Date: 2026-07-26

Authenticated users in the same tenant commonly use the client default
``thread_id``.  User scope is therefore part of the persistence boundary, not
optional metadata.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_02"
down_revision: Union[str, None] = "20260726_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(bind, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(bind).get_indexes(table_name)
        if index.get("name")
    }


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "agent_sessions" in tables:
        indexes = _index_names(bind, "agent_sessions")
        with op.batch_alter_table("agent_sessions") as batch_op:
            if "ix_agent_sessions_tenant_thread" in indexes:
                batch_op.drop_index("ix_agent_sessions_tenant_thread")
            if "ix_agent_sessions_tenant_user_thread" not in indexes:
                batch_op.create_index(
                    "ix_agent_sessions_tenant_user_thread",
                    ["tenant_id", "user_id", "thread_id"],
                    unique=True,
                )

    if "agent_checkpoints" not in tables:
        return

    columns = _column_names(bind, "agent_checkpoints")
    if "user_id" not in columns:
        with op.batch_alter_table("agent_checkpoints") as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch_op.create_index(
                "ix_agent_checkpoints_user_id",
                ["user_id"],
                unique=False,
            )

        op.execute(
            """
            UPDATE agent_checkpoints
            SET user_id = (
                SELECT user_id
                FROM agent_sessions
                WHERE agent_sessions.tenant_id = agent_checkpoints.tenant_id
                  AND agent_sessions.thread_id = agent_checkpoints.thread_id
                ORDER BY agent_sessions.updated_at DESC
                LIMIT 1
            )
            WHERE user_id IS NULL
            """
        )

    indexes = _index_names(bind, "agent_checkpoints")
    with op.batch_alter_table("agent_checkpoints") as batch_op:
        if "ix_agent_checkpoints_tenant_thread" in indexes:
            batch_op.drop_index("ix_agent_checkpoints_tenant_thread")
        if "ix_agent_checkpoints_tenant_user_thread" not in indexes:
            batch_op.create_index(
                "ix_agent_checkpoints_tenant_user_thread",
                ["tenant_id", "user_id", "thread_id", "created_at"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "agent_checkpoints" in tables:
        indexes = _index_names(bind, "agent_checkpoints")
        columns = _column_names(bind, "agent_checkpoints")
        with op.batch_alter_table("agent_checkpoints") as batch_op:
            if "ix_agent_checkpoints_tenant_user_thread" in indexes:
                batch_op.drop_index("ix_agent_checkpoints_tenant_user_thread")
            if "ix_agent_checkpoints_user_id" in indexes:
                batch_op.drop_index("ix_agent_checkpoints_user_id")
            if "user_id" in columns:
                batch_op.drop_column("user_id")
            batch_op.create_index(
                "ix_agent_checkpoints_tenant_thread",
                ["tenant_id", "thread_id", "created_at"],
                unique=False,
            )

    if "agent_sessions" in tables:
        indexes = _index_names(bind, "agent_sessions")
        with op.batch_alter_table("agent_sessions") as batch_op:
            if "ix_agent_sessions_tenant_user_thread" in indexes:
                batch_op.drop_index("ix_agent_sessions_tenant_user_thread")
            batch_op.create_index(
                "ix_agent_sessions_tenant_thread",
                ["tenant_id", "thread_id"],
                unique=True,
            )
