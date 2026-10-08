"""Create the complete application schema.

Revision ID: 20260726_00
Revises:
Create Date: 2026-07-26

This is an immutable schema snapshot. ``checkfirst=True`` also lets an
existing pre-Alembic installation adopt the migration chain without trying to
recreate tables that are already present.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_00"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> sa.MetaData:
    metadata = sa.MetaData()

    plans = sa.Table(
        "plans",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("max_documents", sa.Integer(), nullable=False),
        sa.Column("max_chats_per_day", sa.Integer(), nullable=False),
        sa.Column("max_embeddings", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("features", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_plans_slug", plans.c.slug, unique=True)

    tenants = sa.Table(
        "tenants",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_tenants_slug", tenants.c.slug, unique=True)

    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    sa.Index("ix_users_email", users.c.email, unique=True)

    documents = sa.Table(
        "documents",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("company", sa.String(128), nullable=False),
        sa.Column("report_type", sa.String(128), nullable=False),
        sa.Column("period", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_documents_tenant_id", documents.c.tenant_id)

    subscriptions = sa.Table(
        "tenant_subscriptions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("plans.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "start_date",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    sa.Index("ix_tenant_subscriptions_tenant_id", subscriptions.c.tenant_id, unique=True)
    sa.Index("ix_tenant_subscriptions_plan_id", subscriptions.c.plan_id)

    tasks = sa.Table(
        "tasks",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
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
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
    )
    sa.Index("ix_tasks_public_id", tasks.c.public_id, unique=True)
    sa.Index("ix_tasks_task_type", tasks.c.task_type)
    sa.Index("ix_tasks_status", tasks.c.status)
    sa.Index("ix_tasks_tenant_id", tasks.c.tenant_id)
    sa.Index("ix_tasks_user_id", tasks.c.user_id)
    sa.Index("ix_tasks_worker_id", tasks.c.worker_id)

    usage_records = sa.Table(
        "usage_records",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("meta", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_usage_records_tenant_id", usage_records.c.tenant_id)
    sa.Index("ix_usage_records_user_id", usage_records.c.user_id)
    sa.Index("ix_usage_records_event_type", usage_records.c.event_type)
    sa.Index("ix_usage_records_created_at", usage_records.c.created_at)

    billing_records = sa.Table(
        "billing_records",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "usage_event_id",
            sa.Integer(),
            sa.ForeignKey("usage_records.id"),
            nullable=True,
        ),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_billing_records_tenant_id", billing_records.c.tenant_id)
    sa.Index("ix_billing_records_user_id", billing_records.c.user_id)
    sa.Index("ix_billing_records_usage_event_id", billing_records.c.usage_event_id)
    sa.Index("ix_billing_records_created_at", billing_records.c.created_at)

    worker_nodes = sa.Table(
        "worker_nodes",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("hostname", sa.String(256), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("active_tasks", sa.Integer(), nullable=False),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    sa.Index("ix_worker_nodes_worker_id", worker_nodes.c.worker_id, unique=True)

    agent_sessions = sa.Table(
        "agent_sessions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("thread_id", sa.String(256), nullable=False),
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
    )
    sa.Index("ix_agent_sessions_tenant_id", agent_sessions.c.tenant_id)
    sa.Index("ix_agent_sessions_user_id", agent_sessions.c.user_id)
    sa.Index("ix_agent_sessions_thread_id", agent_sessions.c.thread_id)
    sa.Index(
        "ix_agent_sessions_tenant_user_thread",
        agent_sessions.c.tenant_id,
        agent_sessions.c.user_id,
        agent_sessions.c.thread_id,
        unique=True,
    )

    agent_messages = sa.Table(
        "agent_messages",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("agent_sessions.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_agent_messages_session_id", agent_messages.c.session_id)

    agent_checkpoints = sa.Table(
        "agent_checkpoints",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("thread_id", sa.String(256), nullable=False),
        sa.Column("checkpoint_data", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_agent_checkpoints_user_id", agent_checkpoints.c.user_id)
    sa.Index("ix_agent_checkpoints_thread_id", agent_checkpoints.c.thread_id)
    sa.Index(
        "ix_agent_checkpoints_tenant_user_thread",
        agent_checkpoints.c.tenant_id,
        agent_checkpoints.c.user_id,
        agent_checkpoints.c.thread_id,
        agent_checkpoints.c.created_at,
    )

    agent_traces = sa.Table(
        "agent_traces",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("thread_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    sa.Index("ix_agent_traces_request_id", agent_traces.c.request_id, unique=True)
    sa.Index("ix_agent_traces_tenant_id", agent_traces.c.tenant_id)
    sa.Index("ix_agent_traces_user_id", agent_traces.c.user_id)
    sa.Index("ix_agent_traces_thread_id", agent_traces.c.thread_id)

    agent_spans = sa.Table(
        "agent_spans",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trace_id",
            sa.Integer(),
            sa.ForeignKey("agent_traces.id"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    sa.Index("ix_agent_spans_trace_id", agent_spans.c.trace_id)
    sa.Index("ix_agent_spans_node_name", agent_spans.c.node_name)

    return metadata


def upgrade() -> None:
    _schema().create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    _schema().drop_all(bind=op.get_bind(), checkfirst=True)
