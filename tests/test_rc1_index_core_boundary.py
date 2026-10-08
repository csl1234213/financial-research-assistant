"""Core index projections, explicit enhancement and runtime failure gates."""
import importlib.abc
import inspect
import json
import subprocess
import sys

import pytest

from document_compatibility.evidence_subject import INDEX_POLICY, subject_from_metadata
from storage.chroma_store import ChromaEmbeddingStore
from storage.ingestion_artifacts import IngestionArtifactStore
from tasks.ingestion_index_stage import CoreIndexBuilder
from tests.core_index_fixture_data import SOURCE_SHA, prepare
from tests.formal_ingestion_test_harness import SOURCE, current_time, formal, setup_real  # noqa: F401


def test_core_import_without_query_or_enhancement():
    code = '''
import importlib.abc
import sys
class RejectQuery(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('retrieval.', 'core.answer_synthesis',
             'document_compatibility.narrative_subject_context', 'services.index_subject_enhancement')):
            raise AssertionError('forbidden core index dependency: ' + fullname)
sys.meta_path.insert(0, RejectQuery())
from tasks.ingestion_index_stage import CoreIndexBuilder
CoreIndexBuilder(None, None, embedder=lambda texts: [], embedding_identity='test')
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "query" not in inspect.signature(CoreIndexBuilder.execute).parameters


def test_core_real_projection_idempotency_and_optional_not_called(tmp_path, monkeypatch):
    store = IngestionArtifactStore(tmp_path / "artifacts")
    lease, parsed, quality = prepare(store)
    class RejectEnhancement(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "services.index_subject_enhancement":
                raise AssertionError("semantic enhancement imported in core mode")

    # Do not import the excluded implementation merely to install a spy.
    monkeypatch.setattr(sys, "meta_path", [RejectEnhancement(), *sys.meta_path])
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        index = CoreIndexBuilder(store, vectors, embedder=lambda texts: [[1., .5] for _ in texts],
                                 embedding_identity="fixture-only")
        first = index.execute(lease, parse_artifact_sha256=parsed, quality_artifact_sha256=quality)
        assert index.execute(lease, parse_artifact_sha256=parsed, quality_artifact_sha256=quality) == first
        receipt = json.loads(store.read(1, SOURCE_SHA, first["artifact_sha256"]))
        collection = vectors.client.get_collection(receipt["collection"])
        assert collection.count() == receipt["verified_chunk_count"] == 2
        assert receipt["index_policy_version"] == INDEX_POLICY
        result = collection.get(include=["documents", "metadatas", "embeddings"])
        assert set(result["documents"]) == {"控股股东 名称 示例集团有限公司", "主要业务：制造"}
        assert all("subject_context" not in row and "subject_context_version" not in row
                   for row in result["metadatas"])
        assert all(subject_from_metadata(row).subject_relation_to_issuer == "UNKNOWN"
                   for row in result["metadatas"])
        assert all(row["embedding_identity"] == "fixture-only" and row["source_sha256"] == SOURCE_SHA
                   for row in result["metadatas"])


def test_missing_core_projection_cannot_complete_index_or_ready(formal, tmp_path, monkeypatch):  # noqa: F811
    from tasks.ingestion_stage_executor import IngestionStageExecutor
    ledger, task = setup_real(formal, tmp_path / "artifacts")
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        index = CoreIndexBuilder(ledger.artifact_store, vectors,
            embedder=lambda texts: [[1., .5] for _ in texts], embedding_identity="fixture-only")
        executor = IngestionStageExecutor(ledger, source_resolver=lambda _: SOURCE,
            clock=current_time, index_operator=index)
        for _ in range(4):
            assert executor.run_one(task) == "completed"
        original = vectors.add_documents
        monkeypatch.setattr(vectors, "add_documents", lambda documents: original(documents[:-1]))
        assert executor.run_one(task) == "failed"
        status = ledger.status(task, 1, 2)
        assert status["status"] == "failed" and "INDEXING" not in status["completed_stages"]
        with pytest.raises(ValueError):
            ledger.ready_index(task, 1, 2)
