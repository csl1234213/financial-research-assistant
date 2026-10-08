"""Explicit formal-suite taxonomy and opt-in experimental import hard gate.

Run with -p tests.formal_acceptance_boundary and
FORMAL_ACCEPTANCE_BLOCK_EXPERIMENTAL=true. Import failure is fatal, never caught.
"""

import importlib.abc
import os
import sys

import pytest

FORMAL_FILES = frozenset({
    "tests/migrations/test_formal_ingestion_migration.py",
    "tests/test_formal_persistence_d2.py",
    "tests/test_formal_checkpoint_d2.py",
    "tests/test_formal_composition_d2c.py",
    "tests/test_formal_finalize_api_d2c.py",
    "tests/test_formal_tus_live_d2c.py",
    "tests/test_ready_promotion_d2.py",
    "tests/test_core_index_evidence.py",
    "tests/test_ingestion_artifacts.py",
    "tests/test_rc1_tree_build_boundary.py",
    "tests/test_rc1_answer_dependency_boundary.py",
    "tests/test_rc1_index_core_boundary.py",
    "tests/test_upload_session_contracts.py",
})
EXPERIMENTAL_MODULES = frozenset({
    "storage.upload_session_pilot", "storage.upload_registration_sql",
    "storage.ingestion_sql_models", "tasks.ingestion_ledger",
    "tasks.upload_outbox", "tasks.ingestion_source",
    "tests.test_upload_registration_sql", "tests.test_upload_session_pilot",
    "tests.test_ingestion_stage_executor", "tests.test_ingestion_ledger",
    "tests.test_upload_session_api",
})
BLOCKED = os.environ.get("FORMAL_ACCEPTANCE_BLOCK_EXPERIMENTAL") == "true"


class RejectExperimental(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in EXPERIMENTAL_MODULES):
            raise AssertionError("Formal acceptance imported experimental dependency: " + fullname)


if BLOCKED:
    assert not EXPERIMENTAL_MODULES.intersection(sys.modules), "Experimental modules loaded before hard gate"
    sys.meta_path.insert(0, RejectExperimental())


def pytest_configure(config):
    for marker, description in {
        "FORMAL_ACCEPTANCE": "explicit formal ingestion acceptance subset",
        "LEGACY": "retained compatibility behavior, excluded from formal acceptance",
        "EXPERIMENTAL": "isolated experimental persistence/serialization behavior",
        "formal_unit": "SQLite create_all unit counterpart, not PostgreSQL migration evidence",
    }.items():
        config.addinivalue_line("markers", f"{marker}: {description}")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    for item in items:
        path = item.path.relative_to(config.rootpath).as_posix()
        if path == "tests/test_upload_session_api.py":
            item.add_marker(pytest.mark.LEGACY)
        elif path in FORMAL_FILES and not item.get_closest_marker("LEGACY") and not item.get_closest_marker("EXPERIMENTAL"):
            item.add_marker(pytest.mark.FORMAL_ACCEPTANCE)
        if BLOCKED:
            for definitions in item._fixtureinfo.name2fixturedefs.values():
                for definition in definitions:
                    module = definition.func.__module__
                    assert module not in EXPERIMENTAL_MODULES, f"Experimental fixture registered: {module}"
    if BLOCKED:
        from storage.database import Base

        assert not any(name.startswith("p23_isolated_") for name in Base.metadata.tables)
