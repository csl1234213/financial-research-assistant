"""Add formal upload/checkpoint persistence and independent dispatch obligations."""

import sqlalchemy as sa
from alembic import op

revision = "20261002_10"
down_revision = "20260928_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical tasks deliberately acquire no dispatch obligation.
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("dispatch_state", sa.String(20), nullable=False, server_default="none"))
        batch.add_column(sa.Column("dispatch_attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("dispatch_lease_token", sa.String(32)))
        batch.add_column(sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("dispatch_next_attempt_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("dispatch_error_code", sa.String(64)))
        batch.create_check_constraint(
            "ck_task_dispatch_state", "dispatch_state IN ('none', 'pending', 'leased', 'delivered', 'failed')"
        )
        batch.create_check_constraint("ck_task_dispatch_attempts", "dispatch_attempt_count >= 0")
        batch.create_check_constraint(
            "ck_task_dispatch_lease",
            "(dispatch_state = 'leased' AND dispatch_lease_token IS NOT NULL "
            "AND dispatch_lease_expires_at IS NOT NULL) OR (dispatch_state <> 'leased' "
            "AND dispatch_lease_token IS NULL AND dispatch_lease_expires_at IS NULL)",
        )
        batch.create_index(
            "ix_tasks_dispatch_due", ["dispatch_state", "dispatch_next_attempt_at", "dispatch_lease_expires_at"]
        )
    op.create_table(
        "upload_sessions",
        sa.Column("upload_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("expected_size", sa.Integer(), nullable=False),
        sa.Column("received_size", sa.Integer(), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("verified_sha256", sa.String(64)),
        sa.Column("storage_path", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id")),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id")),
        sa.UniqueConstraint("task_id", name="uq_upload_task_binding"),
        sa.CheckConstraint(
            "status IN ('CREATED','UPLOADING','UPLOADED','VERIFYING','VERIFIED','FINALIZED','FAILED','EXPIRED')",
            name="ck_upload_status",
        ),
        sa.CheckConstraint(
            "expected_size > 0 AND received_size >= 0 AND received_size <= expected_size", name="ck_upload_size"
        ),
        sa.CheckConstraint(
            "status <> 'FINALIZED' OR (document_id IS NOT NULL AND task_id IS NOT NULL AND finalized_at IS NOT NULL)",
            name="ck_upload_finalized_binding",
        ),
        sa.CheckConstraint(
            "status NOT IN ('VERIFIED','FINALIZED') OR (verified_sha256 = expected_sha256 "
            "AND verified_sha256 IS NOT NULL AND received_size = expected_size AND verified_at IS NOT NULL)",
            name="ck_upload_verified_integrity",
        ),
        sa.CheckConstraint("protocol IN ('legacy_multipart','tus','s3_multipart')", name="ck_upload_protocol"),
    )
    op.create_index("ix_upload_sessions_tenant_id", "upload_sessions", ["tenant_id"])
    op.create_index("ix_upload_sessions_user_id", "upload_sessions", ["user_id"])
    op.create_table(
        "task_stage_checkpoints",
        sa.Column("checkpoint_id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_id", sa.String(128)),
        sa.Column("artifact_sha256", sa.String(64)),
        sa.Column("quality_status", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "stage", name="uq_task_checkpoint_stage"),
        sa.CheckConstraint(
            "stage IN ('PARSING','QUALITY_CHECK','BUILDING_FACTS','BUILDING_TREE','INDEXING')",
            name="ck_checkpoint_stage",
        ),
        sa.CheckConstraint(
            "status IN ('pending','leased','complete','failed','quarantined')", name="ck_checkpoint_status"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_checkpoint_attempts"),
        sa.CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'leased' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_checkpoint_lease",
        ),
        sa.CheckConstraint(
            "status <> 'complete' OR (artifact_id IS NOT NULL "
            "AND artifact_sha256 IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_checkpoint_complete_evidence",
        ),
    )


def downgrade() -> None:
    op.drop_table("task_stage_checkpoints")
    op.drop_table("upload_sessions")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("ix_tasks_dispatch_due")
        for name in ("ck_task_dispatch_lease", "ck_task_dispatch_attempts", "ck_task_dispatch_state"):
            batch.drop_constraint(name, type_="check")
        for name in (
            "dispatch_error_code",
            "dispatch_next_attempt_at",
            "dispatch_lease_expires_at",
            "dispatch_lease_token",
            "dispatch_attempt_count",
            "dispatch_state",
        ):
            batch.drop_column(name)
