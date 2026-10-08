from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from tests.storage_paths import (
    create_sqlite_test_database,
    get_test_storage_root,
    sqlite_test_path,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_application_storage_defaults_are_isolated_from_the_repository():
    run_root = get_test_storage_root()
    database_path = Path(make_url(os.environ["DATABASE_URL"]).database).resolve()

    assert REPOSITORY_ROOT not in (run_root, *run_root.parents)
    assert database_path.is_relative_to(run_root)
    assert Path(os.environ["CHROMA_PATH"]).resolve().is_relative_to(run_root)
    assert Path(os.environ["CACHE_DIR"]).resolve().is_relative_to(run_root)
    assert Path(os.environ["UPLOAD_DIR"]).resolve().is_relative_to(run_root)
    assert Path(os.environ["PDF_DIR"]).resolve().is_relative_to(run_root)


def test_sqlite_helper_uses_an_absolute_worker_local_path():
    database_url, engine = create_sqlite_test_database("helper_contract.db")
    database_path = Path(make_url(database_url).database)

    assert database_path.is_absolute()
    assert database_path.resolve().is_relative_to(get_test_storage_root())
    assert isinstance(engine.pool, NullPool)

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE storage_contract (id INTEGER)"))

    assert database_path.exists()

    database_path.unlink()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE storage_contract (id INTEGER)"))

    assert database_path.exists()


@pytest.mark.parametrize(
    "filename",
    ["../outside.db", "nested/database.db", "not-a-database.txt"],
)
def test_sqlite_helper_rejects_paths_outside_its_storage_root(filename):
    with pytest.raises(ValueError):
        sqlite_test_path(filename)


def test_repository_root_has_no_generated_test_databases_or_chroma_directories():
    assert list(REPOSITORY_ROOT.glob("test_*.db*")) == []
    assert list(REPOSITORY_ROOT.glob("chroma_db_test_*")) == []
