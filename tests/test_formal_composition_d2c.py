"""Formal core startup and real operators without experimental persistence."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task
from services.formal_ingestion_composition import FormalIngestionComposition
from storage.chroma_store import ChromaEmbeddingStore
from tests.formal_ingestion_test_harness import formal  # noqa: F401


def test_formal_core_starts_with_experimental_imports_blocked(tmp_path, record_property):
    script = """
import importlib.abc, sys, json
from pathlib import Path
class RejectExperimental(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('core.answer_synthesis', 'retrieval.tree_', 'services.index_subject_enhancement',
                                'document_compatibility.narrative_subject_context')):
            raise AssertionError('Forbidden formal core dependency: ' + fullname)
        if fullname in {'storage.upload_session_pilot','storage.upload_registration_sql',
                        'storage.ingestion_sql_models','tasks.ingestion_ledger','tasks.upload_outbox',
                        'tasks.ingestion_source'}:
            raise AssertionError('Experimental persistence imported: ' + fullname)
sys.meta_path.insert(0, RejectExperimental())
from services.formal_ingestion_composition import FormalIngestionComposition
root = Path(sys.argv[1])
runtime = FormalIngestionComposition(lambda: None, storage_root=root/'uploads',
    artifact_root=root/'artifacts', vectors=object(), embedder=lambda texts: [],
    embedding_identity='startup-fixture')
app = runtime.app()
from sqlalchemy.orm import configure_mappers
configure_mappers()
assert '/upload-sessions' in app.openapi()['paths']
repo=Path.cwd().resolve()
files=[]
for module in tuple(sys.modules.values()):
    location=getattr(module,'__file__',None)
    if location:
        path=Path(location).resolve()
        if path.is_relative_to(repo): files.append(path.relative_to(repo).as_posix())
print('FORMAL_CORE_PROJECT_MODULES='+json.dumps(sorted(set(files))))
print('FORMAL_CORE_STARTS_WITHOUT_EXPERIMENTAL_PERSISTENCE=PASS')
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "=PASS" in result.stdout
    files = json.loads(
        next(
            line.split("=", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("FORMAL_CORE_PROJECT_MODULES=")
        )
    )
    record_property("FORMAL_CORE_PROJECT_MODULES", json.dumps(files))


def test_formal_composition_executes_actual_five_stages(formal, tmp_path):  # noqa: F811
    engine, _, factory = formal
    data = (Path(__file__).parent / "fixtures/moutai-standard-statements-2025.pdf").read_bytes()
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        runtime = FormalIngestionComposition(
            factory,
            storage_root=tmp_path / "uploads",
            artifact_root=tmp_path / "artifacts",
            vectors=vectors,
            embedder=lambda texts: [[1.0, len(text) / 10000] for text in texts],
            embedding_identity="formal-offline-fixture",
        )
        upload = runtime.upload.create(
            tenant_id=1,
            user_id=2,
            filename="report.pdf",
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            mime_type="application/pdf",
        )
        runtime.upload.receive(upload.upload_id, 1, 2, data)
        finalized = runtime.upload.finalize(upload.upload_id, 1, 2)
        assert runtime.runner.run(finalized.ingestion_job_id, tenant_id=1, user_id=2) == "ready"
        first = runtime.ledger.ready_index(finalized.ingestion_job_id, 1, 2)
        assert runtime.runner.run(finalized.ingestion_job_id, tenant_id=1, user_id=2) == "ready"
        assert runtime.ledger.ready_index(finalized.ingestion_job_id, 1, 2) == first
        assert runtime.ledger.ready_document_metadata(finalized.ingestion_job_id, 1, 2)["filename"] == "report.pdf"
        rows, next_offset = runtime.repository.finalized_for_owner(1, 2)
        assert len(rows) == 1 and next_offset is None
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Document)) == 1
            assert session.scalar(select(func.count()).select_from(Task)) == 1
            assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 5
