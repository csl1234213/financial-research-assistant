"""Observability contracts for the LangGraph checkpoint backend."""

from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver

import services.agent_runtime.checkpointing as checkpointing


def _reset_status(monkeypatch) -> None:
    monkeypatch.setattr(
        checkpointing,
        "_postgres_status",
        checkpointing.CheckpointBackendStatus(
            backend="postgres",
            status="not_checked",
            fallback_count=0,
        ),
    )
    checkpointing._setup_databases.clear()


def test_local_checkpoint_status_is_explicitly_ephemeral(monkeypatch) -> None:
    monkeypatch.setattr(checkpointing.storage_config, "use_postgres", False)

    assert checkpointing.get_checkpoint_backend_status() == {
        "backend": "memory",
        "status": "ephemeral",
        "fallback_count": 0,
        "last_error_type": None,
    }


def test_postgres_failure_records_sanitized_fallback_state(monkeypatch) -> None:
    _reset_status(monkeypatch)
    monkeypatch.setattr(checkpointing.storage_config, "use_postgres", True)
    monkeypatch.setattr(
        checkpointing.storage_config,
        "database_url",
        "postgresql://user:secret@database/app",
    )

    class FailingPostgresSaver:
        @classmethod
        def from_conn_string(cls, _database_url):
            raise RuntimeError("connection included a secret")

    import langgraph.checkpoint.postgres as postgres_module

    monkeypatch.setattr(
        postgres_module,
        "PostgresSaver",
        FailingPostgresSaver,
    )

    with checkpointing.agent_checkpointer(tenant_id=7, user_id=11) as saver:
        assert isinstance(saver, InMemorySaver)

    status = checkpointing.get_checkpoint_backend_status()
    assert status == {
        "backend": "postgres",
        "status": "fallback",
        "fallback_count": 1,
        "last_error_type": "RuntimeError",
    }
    assert "secret" not in str(status)


def test_successful_postgres_setup_recovers_status_but_keeps_fallback_count(
    monkeypatch,
) -> None:
    _reset_status(monkeypatch)
    monkeypatch.setattr(checkpointing.storage_config, "use_postgres", True)
    monkeypatch.setattr(
        checkpointing.storage_config,
        "database_url",
        "postgresql://database/app",
    )
    checkpointing._record_postgres_status(
        "fallback",
        error=ConnectionError("temporary"),
    )

    class FakeSaver:
        setup_calls = 0

        def setup(self):
            self.setup_calls += 1

    fake_saver = FakeSaver()

    class FakePostgresSaver:
        @classmethod
        @contextmanager
        def from_conn_string(cls, _database_url):
            yield fake_saver

    import langgraph.checkpoint.postgres as postgres_module

    monkeypatch.setattr(
        postgres_module,
        "PostgresSaver",
        FakePostgresSaver,
    )

    with checkpointing.agent_checkpointer(tenant_id=7, user_id=11) as saver:
        assert saver is fake_saver

    assert fake_saver.setup_calls == 1
    assert checkpointing.get_checkpoint_backend_status() == {
        "backend": "postgres",
        "status": "ok",
        "fallback_count": 1,
        "last_error_type": None,
    }
