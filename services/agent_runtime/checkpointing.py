"""LangGraph checkpoint lifecycle and request-scope isolation.

Production uses LangGraph's maintained PostgreSQL backend. Local SQLite
development uses the built-in in-memory saver so the graph semantics stay the
same without pretending that local state survives a process restart.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from threading import Lock
from typing import Any, Iterator

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from config.storage import storage_config

logger = logging.getLogger(__name__)

_memory_checkpointer = InMemorySaver()
_setup_lock = Lock()
_setup_databases: set[str] = set()
_status_lock = Lock()


@dataclass(frozen=True, slots=True)
class CheckpointBackendStatus:
    """Sanitized process-level state for the configured graph checkpointer."""

    backend: str
    status: str
    fallback_count: int
    last_error_type: str | None = None


_postgres_status = CheckpointBackendStatus(
    backend="postgres",
    status="not_checked",
    fallback_count=0,
)


def scoped_checkpoint_thread_id(
    tenant_id: int,
    user_id: int | None,
    thread_id: str,
) -> str:
    """Return a stable opaque key that cannot collide across principals."""

    principal = str(user_id) if user_id is not None else "system"
    digest = sha256(
        f"{tenant_id}:{principal}:{thread_id}".encode("utf-8")
    ).hexdigest()
    return f"tenant-{tenant_id}:user-{principal}:{digest}"


def _psycopg_url(database_url: str) -> str:
    """Normalize SQLAlchemy-style PostgreSQL URLs for psycopg 3."""

    return (
        database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        .replace("postgresql+psycopg://", "postgresql://", 1)
    )


def _setup_postgres_once(checkpointer: BaseCheckpointSaver, database_url: str) -> None:
    with _setup_lock:
        if database_url in _setup_databases:
            return
        setup = getattr(checkpointer, "setup")
        setup()
        _setup_databases.add(database_url)


def get_checkpoint_backend_status() -> dict[str, Any]:
    """Return a health-safe snapshot without opening an infrastructure client."""

    if not storage_config.use_postgres:
        return asdict(
            CheckpointBackendStatus(
                backend="memory",
                status="ephemeral",
                fallback_count=0,
            )
        )
    with _status_lock:
        return asdict(_postgres_status)


def _record_postgres_status(
    status: str,
    *,
    error: Exception | None = None,
) -> None:
    global _postgres_status

    with _status_lock:
        fallback_count = _postgres_status.fallback_count
        if status == "fallback":
            fallback_count += 1
        _postgres_status = CheckpointBackendStatus(
            backend="postgres",
            status=status,
            fallback_count=fallback_count,
            last_error_type=type(error).__name__ if error is not None else None,
        )


@contextmanager
def agent_checkpointer(
    tenant_id: int | None,
    user_id: int | None,
) -> Iterator[BaseCheckpointSaver | None]:
    """Yield the appropriate saver for one graph invocation.

    Anonymous demo requests intentionally remain stateless. Authenticated
    PostgreSQL requests use the official durable saver; local development uses
    an in-memory saver with the same LangGraph contract.
    """

    if tenant_id is None:
        yield None
        return

    if not storage_config.use_postgres:
        yield _memory_checkpointer
        return

    from langgraph.checkpoint.postgres import PostgresSaver

    stack = ExitStack()
    database_url = _psycopg_url(storage_config.database_url)
    try:
        checkpointer = stack.enter_context(
            PostgresSaver.from_conn_string(database_url)
        )
        _setup_postgres_once(checkpointer, database_url)
    except Exception as exc:
        stack.close()
        _record_postgres_status("fallback", error=exc)
        logger.warning(
            "PostgreSQL graph checkpointer unavailable; using process-local "
            "fallback for tenant=%s user=%s: %s",
            tenant_id,
            user_id,
            exc,
        )
        yield _memory_checkpointer
        return

    _record_postgres_status("ok")
    try:
        yield checkpointer
    finally:
        stack.close()


def delete_scoped_checkpoint_thread(
    tenant_id: int,
    user_id: int,
    thread_id: str,
) -> bool:
    """Remove operational graph state for one exact authenticated thread.

    The application-level checkpoint records remain archived for audit. This
    deletes only the LangGraph runtime copy so recreating a client thread ID
    cannot revive a conversation that the user deleted.
    """

    checkpoint_thread_id = scoped_checkpoint_thread_id(
        tenant_id,
        user_id,
        thread_id,
    )
    if not storage_config.use_postgres:
        _memory_checkpointer.delete_thread(checkpoint_thread_id)
        return True

    from langgraph.checkpoint.postgres import PostgresSaver

    database_url = _psycopg_url(storage_config.database_url)
    try:
        with PostgresSaver.from_conn_string(database_url) as checkpointer:
            _setup_postgres_once(checkpointer, database_url)
            checkpointer.delete_thread(checkpoint_thread_id)
    except Exception:
        logger.exception(
            "Unable to delete graph checkpoint for tenant=%s user=%s",
            tenant_id,
            user_id,
        )
        return False
    return True
