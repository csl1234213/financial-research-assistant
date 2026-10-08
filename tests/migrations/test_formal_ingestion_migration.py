"""Mandatory isolated PostgreSQL acceptance of the formal persistence revision."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.ingestion_persistence import TaskStageCheckpoint, UploadSession
from models.task import Task
from tasks.task_dispatcher import TaskDispatcher

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migration_database():
    url = os.environ.get("P23_ISOLATED_POSTGRES_URL")
    if not url:
        pytest.fail("Real isolated PostgreSQL is required; migration acceptance cannot skip")
    parsed = make_url(url)
    assert parsed.host == "127.0.0.1" and parsed.database == "p23_upload_test"
    schema = "p23_migration_" + uuid4().hex
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            config.attributes["connection"] = connection
            yield connection, config
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def assert_formal_schema(connection):
    inspector = inspect(connection)
    for model in (UploadSession, TaskStageCheckpoint, Task):
        table = model.__table__
        actual = {item["name"]: item for item in inspector.get_columns(table.name)}
        assert set(actual) == set(table.columns.keys())
        assert inspector.get_pk_constraint(table.name)["constrained_columns"] == list(table.primary_key.columns.keys())
        for column in table.columns:
            assert actual[column.name]["nullable"] == column.nullable
            assert (
                str(actual[column.name]["type"].compile(dialect=connection.dialect)).lower()
                == str(column.type.compile(dialect=connection.dialect)).lower()
            )
        expected_checks = {c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}
        assert expected_checks <= {c["name"] for c in inspector.get_check_constraints(table.name)}
        expected_indexes = {index.name for index in table.indexes}
        assert expected_indexes <= {index["name"] for index in inspector.get_indexes(table.name)}
        if model is not Task:
            actual_fk = {
                (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
                for fk in inspector.get_foreign_keys(table.name)
            }
            expected_fk = {
                (tuple(fk.column_keys), fk.referred_table.name, tuple(element.column.name for element in fk.elements))
                for fk in table.foreign_key_constraints
            }
            assert actual_fk == expected_fk
            assert {c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"} <= {
                c["name"] for c in inspector.get_unique_constraints(table.name)
            }
    connection.commit()


def test_migrated_postgres_enforces_upload_and_checkpoint_constraints(migration_database):
    connection, config = migration_database
    command.upgrade(config, "head")
    connection.execute(text("INSERT INTO tenants (id,name,slug) VALUES (1,'Constraints','constraints')"))
    connection.execute(
        text(
            "INSERT INTO users (id,tenant_id,email,password_hash,role) "
            "VALUES (1,1,'constraints@example.test','fixture','user')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO tasks (id,public_id,task_type,status,tenant_id,user_id,progress,"
            "payload,result,retry_count) VALUES (1,:public_id,'process_document','pending',"
            "1,1,0,'{}','{}',0)"
        ),
        {"public_id": uuid4().hex},
    )
    connection.execute(
        text(
            "INSERT INTO documents (id,filename,company,report_type,period,status,tenant_id,"
            "uploaded_by_user_id) VALUES (1,'report.pdf','Unknown','Annual','Unknown','pending',1,1)"
        )
    )
    uploads = Table("upload_sessions", MetaData(), autoload_with=connection)
    checkpoints = Table("task_stage_checkpoints", MetaData(), autoload_with=connection)
    now = datetime.now(timezone.utc)
    base = dict(
        upload_id="constraint-upload",
        tenant_id=1,
        user_id=1,
        filename="report.pdf",
        mime_type="application/pdf",
        protocol="tus",
        expected_size=1,
        received_size=0,
        expected_sha256="a" * 64,
        status="CREATED",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
    )
    connection.execute(uploads.insert().values(**base))
    connection.commit()
    for update in (
        {"status": "UNKNOWN"},
        {"expected_size": 0},
        {"received_size": 2},
        {"protocol": "client-selected"},
        {"status": "FINALIZED"},
        {"status": "VERIFIED", "verified_sha256": "b" * 64, "verified_at": now},
        {"tenant_id": 999},
        {"user_id": 999},
        {"document_id": 999},
        {"task_id": 999},
    ):
        values = {**base, "upload_id": uuid4().hex, **update}
        with connection.begin_nested() as transaction:
            with pytest.raises(IntegrityError):
                connection.execute(uploads.insert().values(**values))
            transaction.rollback()
    with connection.begin_nested() as transaction:
        with pytest.raises(IntegrityError):
            connection.execute(uploads.insert().values(**base))
        transaction.rollback()
    checkpoint = dict(
        task_id=1, document_id=1, stage="PARSING", status="pending", attempt_count=0, source_sha256="a" * 64
    )
    connection.execute(checkpoints.insert().values(**checkpoint))
    for update in (
        {},
        {"stage": "ANSWER"},
        {"stage": "INDEXING", "status": "complete"},
        {"stage": "INDEXING", "status": "leased"},
        {"task_id": 999},
        {"document_id": 999},
    ):
        with connection.begin_nested() as transaction:
            with pytest.raises(IntegrityError):
                connection.execute(checkpoints.insert().values(**{**checkpoint, **update}))
            transaction.rollback()
    connection.commit()


def test_fresh_upgrade_and_single_head(migration_database):
    connection, config = migration_database
    assert ScriptDirectory.from_config(config).get_heads() == ["20261002_10"]
    assert inspect(connection).get_table_names() == []
    connection.commit()
    command.upgrade(config, "head")
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261002_10"
    connection.commit()
    assert_formal_schema(connection)


def test_previous_head_downgrade_reupgrade_preserves_historical_tasks(migration_database):
    connection, config = migration_database
    command.upgrade(config, "20260928_09")
    connection.execute(text("INSERT INTO tenants (id,name,slug) VALUES (1,'Migration','migration')"))
    connection.execute(
        text(
            "INSERT INTO users (id,tenant_id,email,password_hash,role) "
            "VALUES (1,1,'migration@example.test','fixture','user')"
        )
    )
    for index, status in enumerate(("pending", "running", "success", "failed"), 1):
        connection.execute(
            text(
                "INSERT INTO tasks (id,public_id,task_type,status,tenant_id,user_id,progress,"
                "payload,result,retry_count) VALUES (:id,:public_id,'process_document',"
                ":status,1,1,0,'{}','{}',0)"
            ),
            {"id": index, "public_id": uuid4().hex, "status": status},
        )
    connection.commit()
    command.upgrade(config, "head")
    assert connection.execute(text("SELECT status,dispatch_state FROM tasks ORDER BY id")).all() == [
        (status, "none") for status in ("pending", "running", "success", "failed")
    ]
    connection.commit()
    assert TaskDispatcher(lambda: Session(connection)).claim(datetime.now(timezone.utc)) is None
    assert_formal_schema(connection)
    command.downgrade(config, "20260928_09")
    assert "upload_sessions" not in inspect(connection).get_table_names()
    assert "dispatch_state" not in {c["name"] for c in inspect(connection).get_columns("tasks")}
    assert connection.scalar(text("SELECT count(*) FROM tasks")) == 4
    connection.commit()
    command.upgrade(config, "head")
    assert_formal_schema(connection)
    assert connection.scalar(text("SELECT count(*) FROM tasks WHERE dispatch_state='none'")) == 4
    connection.commit()
