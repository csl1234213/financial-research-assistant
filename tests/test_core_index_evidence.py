"""Expected-vs-actual validation, no Provider and no regeneration on reads."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from storage.chroma_store import ChromaEmbeddingStore
from storage.core_index_evidence import CoreIndexEvidenceReader
from storage.ingestion_artifacts import IngestionArtifactStore
from tasks.ingestion_index_stage import CoreIndexBuilder
from tests.core_index_fixture_data import SOURCE_SHA, prepare


@pytest.fixture
def built(tmp_path):
    store = IngestionArtifactStore(tmp_path / "artifacts")
    lease, parsed, quality = prepare(store)
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        builder = CoreIndexBuilder(
            store, vectors, embedder=lambda texts: [[1.0, 0.5] for _ in texts], embedding_identity="fixture-only"
        )
        result = builder.execute(lease, parse_artifact_sha256=parsed, quality_artifact_sha256=quality)
        receipt = json.loads(store.read(1, SOURCE_SHA, result["artifact_sha256"]))
        yield store, vectors, receipt, builder, lease, parsed, quality


def test_roundtrip_and_idempotent_build(built):
    store, vectors, receipt, builder, lease, parsed, quality = built
    assert (
        CoreIndexEvidenceReader(store, vectors).validate(receipt, tenant_id=1, document_id=42, source_sha256=SOURCE_SHA)
        == 2
    )
    again = builder.execute(lease, parse_artifact_sha256=parsed, quality_artifact_sha256=quality)
    assert json.loads(store.read(1, SOURCE_SHA, again["artifact_sha256"])) == receipt
    assert receipt["evidence_size"]["raw_evidence_bytes"] > 0


def test_ready_reader_does_not_build_or_embed(built, monkeypatch):
    store, vectors, receipt, builder, *_ = built
    calls = {"build": 0, "embed": 0}

    def forbidden_build(*args, **kwargs):
        calls["build"] += 1
        raise AssertionError("READY must not rebuild")

    def forbidden_embed(*args, **kwargs):
        calls["embed"] += 1
        raise AssertionError("READY must not embed")

    monkeypatch.setattr(CoreIndexBuilder, "execute", forbidden_build)
    monkeypatch.setattr(builder, "embedder", forbidden_embed)
    assert (
        CoreIndexEvidenceReader(store, vectors).validate(receipt, tenant_id=1, document_id=42, source_sha256=SOURCE_SHA)
        == 2
    )
    assert calls == {"build": 0, "embed": 0}


@pytest.mark.parametrize(
    "mutation",
    [
        "within",
        "outside",
        "text",
        "swapped",
        "metadata",
        "document_metadata",
        "missing_metadata",
        "missing",
        "wrong_block",
        "dimension",
    ],
)
def test_actual_projection_mutations(built, mutation):
    store, vectors, receipt, *_ = built
    collection = vectors.client.get_collection(receipt["collection"])
    actual = collection.get(include=["documents", "metadatas", "embeddings"])
    identifier = actual["ids"][0]
    if mutation in {"within", "outside"}:
        collection.update(ids=[identifier], embeddings=[[1.0 + (1e-7 if mutation == "within" else 0.01), 0.5]])
    elif mutation == "text":
        collection.update(ids=[identifier], documents=["changed"], embeddings=[actual["embeddings"][0].tolist()])
    elif mutation == "swapped":
        collection.update(
            ids=actual["ids"],
            documents=list(reversed(actual["documents"])),
            embeddings=[row.tolist() for row in actual["embeddings"]],
        )
    elif mutation in {"metadata", "document_metadata", "missing_metadata"}:
        # Chroma update merges keys; replace the row to truly delete a required field.
        metadata = dict(actual["metadatas"][0])
        if mutation == "document_metadata":
            metadata["document_id"] = "999"
        elif mutation == "metadata":
            metadata["tenant_id"] = 999
        else:
            metadata.pop("source_sha256")
        collection.delete(ids=[identifier])
        collection.add(
            ids=[identifier],
            documents=[actual["documents"][0]],
            embeddings=[actual["embeddings"][0].tolist()],
            metadatas=[metadata],
        )
    elif mutation == "missing":
        collection.delete(ids=[identifier])
    elif mutation == "wrong_block":
        collection.delete(ids=[identifier])
        collection.add(
            ids=["wrong-block"],
            documents=[actual["documents"][0]],
            embeddings=[actual["embeddings"][0].tolist()],
            metadatas=[actual["metadatas"][0]],
        )
    else:
        # Store itself rejects incompatible dimensions; the shared validator also rejects
        # a persisted adapter returning a different dimension (separate test below).
        with pytest.raises(Exception):
            collection.update(ids=[identifier], embeddings=[[1.0]])
        return

    def call():
        return CoreIndexEvidenceReader(store, vectors).validate(
            receipt, tenant_id=1, document_id=42, source_sha256=SOURCE_SHA
        )

    if mutation == "within":
        assert call() == 2
    else:
        with pytest.raises(ValueError, match="INDEX_READBACK_FAILED"):
            call()


def test_shared_validator_rejects_dimension_mismatch(built):
    store, vectors, receipt, *_ = built
    collection = vectors.client.get_collection(receipt["collection"])

    def wrong_dimension(**kwargs):
        result = collection.get(**kwargs)
        result["embeddings"] = [row.tolist() for row in result["embeddings"]]
        result["embeddings"][0] = result["embeddings"][0][:-1]
        return result

    adapter = SimpleNamespace(
        client=SimpleNamespace(get_collection=lambda name: SimpleNamespace(count=collection.count, get=wrong_dimension))
    )
    with pytest.raises(ValueError, match="INDEX_READBACK_FAILED"):
        CoreIndexEvidenceReader(store, adapter).validate(receipt, tenant_id=1, document_id=42, source_sha256=SOURCE_SHA)


@pytest.mark.parametrize(
    "mutation", ["count_only", "sha", "missing", "corrupt", "document", "source", "policy", "format"]
)
def test_evidence_identity_and_corruption(built, mutation):
    store, vectors, original, *_ = built
    receipt = dict(original)
    if mutation == "count_only":
        receipt.pop("evidence_artifact_ref")
    elif mutation == "sha":
        receipt["evidence_artifact_sha256"] = "b" * 64
    elif mutation == "missing":
        receipt["evidence_artifact_ref"] = receipt["evidence_artifact_sha256"] = "b" * 64
    elif mutation == "corrupt":
        # Corrupt bytes are stored as a distinct artifact: SHA check passes, format must fail.
        digest = store.put(1, SOURCE_SHA, b"invalid evidence bytes")
        receipt["evidence_artifact_ref"] = receipt["evidence_artifact_sha256"] = digest
    elif mutation == "document":
        receipt["document_id"] = 99
    elif mutation == "source":
        receipt["source_sha256"] = "b" * 64
    elif mutation == "policy":
        receipt["index_policy_version"] = "obsolete"
    else:
        receipt["evidence_format_version"] = "unsupported"
    with pytest.raises((ValueError, FileNotFoundError)):
        CoreIndexEvidenceReader(store, vectors).validate(receipt, tenant_id=1, document_id=42, source_sha256=SOURCE_SHA)


def test_separate_process_restart_revalidates_without_provider(built, tmp_path):
    store, vectors, receipt, *_ = built
    code = """
import json, sys
from pathlib import Path
from storage.chroma_store import ChromaEmbeddingStore
from storage.ingestion_artifacts import IngestionArtifactStore
from storage.core_index_evidence import CoreIndexEvidenceReader
receipt=json.loads(sys.argv[3])
with ChromaEmbeddingStore(Path(sys.argv[2]), host="") as vectors:
    CoreIndexEvidenceReader(IngestionArtifactStore(Path(sys.argv[1])), vectors).validate(
        receipt, tenant_id=1, document_id=42, source_sha256=receipt["source_sha256"])
"""
    args = [sys.executable, "-c", code, str(store.root), str(tmp_path / "vectors"), json.dumps(receipt)]
    first = subprocess.run(args, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stderr
    collection = vectors.client.get_collection(receipt["collection"])
    identifiers = collection.get()["ids"]
    collection.update(ids=[identifiers[0]], embeddings=[[9.0, 0.5]])
    assert collection.count() == receipt["verified_chunk_count"]
    second = subprocess.run(args, capture_output=True, text=True, timeout=60)
    assert second.returncode != 0 and "INDEX_READBACK_FAILED" in second.stderr
