"""Formal test wiring, not a second implementation of registration/ingestion.

PostgreSQL always upgrades the real Alembic graph in a disposable schema.
SQLite create_all is explicitly unit-only. Only Tenant/User environment data
are seeded directly; Upload/Document/Task/checkpoints use real repositories.
"""

import hashlib
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from core.upload_session_contracts import UploadState
from models.tenant import Tenant
from models.user import User
from services.upload_session_service import UploadSessionService
from storage.database import Base, _import_models
from storage.ingestion_artifacts import IngestionArtifactStore
from storage.upload_session_repository import UploadSessionRepository
from tasks.formal_ingestion_ledger import FormalIngestionLedger
from tests.formal_contract_data import HASH, NOW, verifying

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/moutai-standard-statements-2025.pdf"


@pytest.fixture(params=[
    pytest.param("sqlite", marks=pytest.mark.formal_unit),
    pytest.param("postgresql", marks=pytest.mark.FORMAL_ACCEPTANCE),
])
def formal(tmp_path, request):
    _import_models()
    schema = None
    if request.param == "postgresql":
        url = os.environ.get("P23_ISOLATED_POSTGRES_URL")
        if not url:
            pytest.fail("Isolated PostgreSQL is mandatory for formal acceptance")
        parsed = make_url(url)
        if parsed.host != "127.0.0.1" or parsed.database != "p23_upload_test":
            pytest.fail("Only isolated loopback p23_upload_test database permitted")
        schema = f"p23_formal_e_{uuid4().hex}"
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine.dispose()

        @event.listens_for(engine, "connect")
        def scope(connection, _):
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
            connection.commit()
    else:
        engine = create_engine(f"sqlite:///{(tmp_path / 'formal.sqlite').as_posix()}")
        event.listen(engine, "connect", lambda db, _: db.execute("PRAGMA foreign_keys=ON"))
    try:
        if schema:
            with engine.connect() as connection:
                config = Config(str(ROOT / "alembic.ini"))
                config.set_main_option("script_location", str(ROOT / "migrations"))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            # Persisted restart fixtures convey this public engine option to
            # child engines; search_path alone is not serialized across processes.
            engine = engine.execution_options(schema_translate_map={None: schema})
        else:
            Base.metadata.create_all(engine)  # Unit-only, never PostgreSQL acceptance.
        with Session(engine) as db, db.begin():
            db.add(Tenant(id=1, name="Formal", slug="formal"))
            db.flush()
            db.add(User(id=2, tenant_id=1, email="formal@example.test", password_hash="fixture"))
        factory = lambda: Session(engine)  # noqa: E731
        repo = UploadSessionRepository(factory)
        repo.create(replace(verifying(), state=UploadState.CREATED))
        repo.accept_content(
            "upload-1", 1, 2, size=100, sha256=HASH, valid_pdf=True,
            storage_path="fixture/document.pdf", now=NOW,
        )
        yield engine, repo, factory
    finally:
        if schema:
            with engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def setup_real(formal_data, root):
    """Real PDF service transitions; no manual source binding or READY seed."""
    _, repo, factory = formal_data
    service = UploadSessionService(repo, root / "uploads")
    data = SOURCE.read_bytes()
    upload = service.create(
        tenant_id=1, user_id=2, filename=SOURCE.name, size=len(data),
        sha256=hashlib.sha256(data).hexdigest(), mime_type="application/pdf",
    )
    service.receive(upload.upload_id, 1, 2, data)
    result = service.finalize(upload.upload_id, 1, 2)
    ledger = FormalIngestionLedger(factory, artifact_store=IngestionArtifactStore(root / "artifacts"))
    return ledger, result.ingestion_job_id


def current_time():
    return datetime.now(timezone.utc)
