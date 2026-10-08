"""Regression tests for the production Alembic schema lifecycle."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "agent_checkpoints",
    "agent_messages",
    "agent_sessions",
    "agent_spans",
    "agent_traces",
    "billing_records",
    "documents",
    "llm_provider_settings",
    "plans",
    "tasks",
    "tenant_subscriptions",
    "tenants",
    "usage_records",
    "users",
    "worker_nodes",
}


def _alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def test_fresh_database_upgrades_to_head_without_schema_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = _alembic_config()
    expected_revision = ScriptDirectory.from_config(config).get_current_head()
    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert EXPECTED_TABLES <= set(inspector.get_table_names())
        checkpoint_columns = {
            column["name"]
            for column in inspector.get_columns("agent_checkpoints")
        }
        assert "archived_at" in checkpoint_columns
        llm_setting_columns = {
            column["name"]
            for column in inspector.get_columns("llm_provider_settings")
        }
        assert "is_default" in llm_setting_columns
        document_columns = {
            column["name"]
            for column in inspector.get_columns("documents")
        }
        assert {
            "content_sha256",
            "byte_size",
            "uploaded_by_user_id",
            "indexed_chunk_count",
        } <= document_columns
        document_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("documents")
        }
        deduplication_index = document_indexes[
            "uq_documents_tenant_content_sha256"
        ]
        assert deduplication_index["unique"] == 1
        assert deduplication_index["column_names"] == [
            "tenant_id",
            "content_sha256",
        ]

        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == expected_revision
    finally:
        engine.dispose()
