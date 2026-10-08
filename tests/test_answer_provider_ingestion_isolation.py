"""An Answer outage cannot prevent formal offline ingestion from reaching READY."""
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.answer_synthesis_ollama import LocalQwenDraftGenerator
from llm.providers.provider_exceptions import ProviderError
from models.tenant import Tenant
from models.user import User
from services.formal_ingestion_composition import FormalIngestionComposition
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import Base, _import_models
from tests.test_answer_provider_contract import config, registered_fixture
from tests.test_answer_synthesis_ollama import request


def test_answer_outage_does_not_break_formal_ingestion(monkeypatch, tmp_path):
    registered_fixture(monkeypatch)
    answer = LocalQwenDraftGenerator(provider_config=config("a"), enabled=True)

    def unavailable(*_):
        raise ProviderError("Answer provider unavailable")

    monkeypatch.setattr(answer.provider, "chat", unavailable)
    with pytest.raises(ProviderError):
        answer.generate(request())
    _import_models()
    engine = create_engine(f"sqlite:///{(tmp_path / 'unit.sqlite').as_posix()}")
    Base.metadata.create_all(engine)  # Offline unit database only.
    try:
        with Session(engine) as session, session.begin():
            session.add(Tenant(id=1, name="Unit", slug="unit"))
            session.flush()
            session.add(User(id=2, tenant_id=1, email="unit@example.test", password_hash="fixture"))
        with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
            runtime = FormalIngestionComposition(lambda: Session(engine),
                storage_root=tmp_path / "uploads", artifact_root=tmp_path / "artifacts",
                vectors=vectors, embedder=lambda texts: [[1., .5] for _ in texts],
                embedding_identity="independent-offline-embedding")
            assert "/upload-sessions" in runtime.app().openapi()["paths"]
            data = (Path(__file__).parent / "fixtures/moutai-standard-statements-2025.pdf").read_bytes()
            upload = runtime.upload.create(tenant_id=1, user_id=2, filename="report.pdf", size=len(data),
                sha256=hashlib.sha256(data).hexdigest(), mime_type="application/pdf")
            runtime.upload.receive(upload.upload_id, 1, 2, data)
            finalized = runtime.upload.finalize(upload.upload_id, 1, 2)
            assert runtime.runner.run(finalized.ingestion_job_id, tenant_id=1, user_id=2) == "ready"
            assert runtime.ledger.ready_index(finalized.ingestion_job_id, 1, 2)
            assert len(runtime.ledger.status(finalized.ingestion_job_id, 1, 2)["completed_stages"]) == 5
    finally:
        engine.dispose()
