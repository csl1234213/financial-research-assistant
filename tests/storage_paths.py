"""Test-only storage helpers.

Every file-backed test database lives below the per-process directory created
by ``tests.conftest``.  Keeping the path absolute avoids depending on pytest's
working directory, while the process-local root also makes the helper safe for
xdist workers and concurrent pytest invocations.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

_TEST_ROOT_ENV = "FINANCIAL_RAG_TEST_RUN_ROOT"
_engines: list[Engine] = []
_engines_lock = Lock()


def get_test_storage_root() -> Path:
    """Return the isolated root configured before test-module collection."""

    raw_root = os.environ.get(_TEST_ROOT_ENV)
    if not raw_root:
        raise RuntimeError(
            f"{_TEST_ROOT_ENV} is not configured; run tests through pytest"
        )

    root = Path(raw_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sqlite_test_path(filename: str) -> Path:
    """Return an absolute, worker-local path for a SQLite test database."""

    if Path(filename).name != filename:
        raise ValueError("SQLite test database filename must not contain directories")
    if not filename.endswith((".db", ".sqlite", ".sqlite3")):
        raise ValueError("SQLite test database must use a SQLite file extension")

    database_dir = get_test_storage_root() / "sqlite"
    database_dir.mkdir(parents=True, exist_ok=True)
    return database_dir / filename


def create_sqlite_test_database(filename: str) -> tuple[str, Engine]:
    """Create and track a file-backed SQLite engine for one test module."""

    path = sqlite_test_path(filename)
    database_url = f"sqlite:///{path.as_posix()}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    with _engines_lock:
        _engines.append(engine)
    return database_url, engine


def dispose_sqlite_test_engines() -> None:
    """Release every tracked SQLite handle before session-root removal."""

    with _engines_lock:
        engines = list(reversed(_engines))
        _engines.clear()

    for engine in engines:
        engine.dispose(close=True)
