from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

migration = import_module(
    "migrations.versions.20260729_08_local_ollama_provider"
)


def _legacy_settings_table(connection):
    connection.execute(
        sa.text(
            "CREATE TABLE llm_provider_settings ("
            "id INTEGER PRIMARY KEY, "
            "encrypted_api_key TEXT NOT NULL, "
            "key_hint VARCHAR(4) NOT NULL)"
        )
    )


def test_upgrade_preserves_existing_credentials_and_allows_keyless_rows():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_settings_table(connection)
        connection.execute(
            sa.text(
                "INSERT INTO llm_provider_settings "
                "(id, encrypted_api_key, key_hint) VALUES (1, 'ciphertext', 'ABCD')"
            )
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns("llm_provider_settings")
        }
        assert columns["base_url"]["nullable"] is True
        assert columns["encrypted_api_key"]["nullable"] is True
        assert columns["key_hint"]["nullable"] is True
        assert connection.execute(
            sa.text(
                "SELECT encrypted_api_key, key_hint FROM llm_provider_settings "
                "WHERE id = 1"
            )
        ).one() == ("ciphertext", "ABCD")
        connection.execute(
            sa.text(
                "INSERT INTO llm_provider_settings "
                "(id, encrypted_api_key, key_hint, base_url) "
                "VALUES (2, NULL, NULL, 'http://host.docker.internal:11434')"
            )
        )


def test_downgrade_refuses_to_discard_keyless_local_provider_rows():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _legacy_settings_table(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO llm_provider_settings "
                "(id, encrypted_api_key, key_hint, base_url) "
                "VALUES (1, NULL, NULL, 'http://host.docker.internal:11434')"
            )
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context), pytest.raises(RuntimeError, match="keyless"):
            migration.downgrade()
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM llm_provider_settings")
        ).scalar_one() == 1
