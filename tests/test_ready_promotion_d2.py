"""Formal READY transactions with actual Tree/Chroma and isolated PostgreSQL."""

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from core.upload_session_contracts import UploadState
from document_compatibility.engine import inspect_pdf
from document_loader import CHUNKER_VERSION, PARSER_VERSION
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task
from services.ready_promotion import ReadyPromotionService
from storage.chroma_store import ChromaEmbeddingStore
from storage.ingestion_artifacts import IngestionArtifactStore
from tasks.formal_ingestion_ledger import FormalIngestionLedger
from tasks.ingestion_index_stage import CoreIndexBuilder
from tasks.ingestion_tree_stage import FinancialTreeStage
from tests.formal_contract_data import NOW, verifying
from tests.formal_ingestion_test_harness import formal  # noqa: F401


@pytest.fixture
def ready_case(formal, tmp_path, real_report):  # noqa: F811
    engine, repo, factory = formal
    source = Path("tests/fixtures/moutai-standard-statements-2025.pdf")
    content = source.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    value = replace(
        verifying(),
        upload_id="ready-source",
        state=UploadState.CREATED,
        expected_size=len(content),
        expected_sha256=sha,
    )
    repo.create(value)
    repo.accept_content(
        value.upload_id,
        1,
        2,
        size=len(content),
        sha256=sha,
        valid_pdf=True,
        storage_path=str(source.resolve()),
        now=NOW,
    )
    result = repo.finalize(value.upload_id, 1, 2, NOW)
    store = IngestionArtifactStore(tmp_path / "artifacts")
    report = real_report
    chunks = [{"text": block.text, "page": block.page, "section": "Real report"} for block in report.blocks[:4]]
    document_id = int(result.document_id)

    def artifact(payload):
        return store.put(1, sha, json.dumps(payload, sort_keys=True, default=str).encode())

    parsed = artifact(
        {
            "schema": "financial-ingestion-parse.v1",
            "document_id": document_id,
            "tenant_id": 1,
            "source_sha256": sha,
            "chunks": chunks,
            "parser_version": PARSER_VERSION,
            "chunker_version": CHUNKER_VERSION,
        }
    )
    quality = artifact(
        {
            "schema": "financial-ingestion-quality.v1",
            "source_sha256": sha,
            "parse_artifact_sha256": parsed,
            "quality_status": "PASS",
            "missing_native_source_ids": [],
            "missing_ocr_source_ids": [],
            "compatibility": report.to_dict(),
        }
    )
    facts = artifact(
        {
            "schema": "financial-ingestion-facts.v1",
            "document_id": document_id,
            "tenant_id": 1,
            "source_sha256": sha,
            "parse_artifact_sha256": parsed,
            "quality_artifact_sha256": quality,
            "facts": [],
        }
    )
    ledger = FormalIngestionLedger(factory, artifact_store=store)
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        receipts = {}
        for stage in ("PARSING", "QUALITY_CHECK", "BUILDING_FACTS", "BUILDING_TREE", "INDEXING"):
            lease = ledger.claim(result.ingestion_job_id, NOW)
            assert lease.stage == stage
            if stage == "BUILDING_TREE":
                receipt = FinancialTreeStage(store).execute(
                    lease, parse_artifact_sha256=parsed, quality_artifact_sha256=quality
                )
            elif stage == "INDEXING":
                receipt = CoreIndexBuilder(
                    store,
                    vectors,
                    embedder=lambda texts: [[1.0, 0.5] for _ in texts],
                    embedding_identity="fixture-only",
                ).execute(lease, parse_artifact_sha256=parsed, quality_artifact_sha256=quality)
            else:
                digest = {"PARSING": parsed, "QUALITY_CHECK": quality, "BUILDING_FACTS": facts}[stage]
                receipt = {"artifact_id": digest, "artifact_sha256": digest}
                if stage == "QUALITY_CHECK":
                    receipt["quality_status"] = "PASS"
            assert ledger.finish(lease, now=NOW, **receipt)
            receipts[stage] = receipt["artifact_sha256"]
        assert ledger.status(result.ingestion_job_id, 1, 2)["status"] != "ready"
        yield engine, factory, store, vectors, result, sha, receipts


@pytest.fixture(scope="module")
def real_report():
    # Setup parsing may be shared; recovery never receives this object or expected vectors.
    return inspect_pdf(Path("tests/fixtures/moutai-standard-statements-2025.pdf"))[1]


def promote(case):
    _, factory, store, vectors, result, _, _ = case
    counters = {"experimental": 0, "provider": 0, "rebuild": 0, "enhancement": 0}
    previous = sys.getprofile()

    def profile(frame, event, arg):
        if event != "call":
            return
        module = frame.f_globals.get("__name__", "")
        if module.startswith(("storage.upload_registration_sql", "tasks.ingestion_ledger", "tasks.upload_outbox")):
            counters["experimental"] += 1
        if module.startswith("llm.") or (
            module.startswith("chromadb.utils.embedding_functions") and frame.f_code.co_name == "__call__"
        ):
            counters["provider"] += 1
        if module == "tasks.ingestion_index_stage" and frame.f_code.co_name == "execute":
            counters["rebuild"] += 1
        if module.startswith(
            ("services.index_subject_enhancement", "document_compatibility.narrative_subject_context")
        ):
            counters["enhancement"] += 1

    sys.setprofile(profile)
    try:
        return ReadyPromotionService(factory, artifact_store=store, vector_store=vectors).promote(
            result.ingestion_job_id, tenant_id=1, user_id=2, now=NOW
        )
    finally:
        sys.setprofile(previous)
        assert counters == {"experimental": 0, "provider": 0, "rebuild": 0, "enhancement": 0}


def assert_not_ready(case):
    engine, _, _, _, result, *_ = case
    with Session(engine) as session:
        assert session.get(Document, int(result.document_id)).status != "ready"
        assert session.scalar(select(Task).where(Task.public_id == result.ingestion_job_id)).status != "success"


def test_positive_idempotent_dispatch_closed(ready_case):
    first = promote(ready_case)
    assert promote(ready_case) == first
    engine, _, _, _, result, *_ = ready_case
    with Session(engine) as session:
        task = session.scalar(select(Task).where(Task.public_id == result.ingestion_job_id))
        assert task.status == "success" and task.dispatch_state == "none"
        assert session.get(Document, int(result.document_id)).status == "ready"


def test_concurrent_promotion(ready_case):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: promote(ready_case), range(2)))
    assert results[0] == results[1]


@pytest.mark.parametrize("corrupt", [False, True])
def test_new_process_reads_formal_checkpoints_not_expected_cache(ready_case, tmp_path, corrupt):
    engine, _, store, vectors, result, sha, receipts = ready_case
    if corrupt:
        receipt = json.loads(store.read(1, sha, receipts["INDEXING"]))
        collection = vectors.client.get_collection(receipt["collection"])
        collection.update(ids=[collection.get()["ids"][0]], embeddings=[[9.0, 0.5]])
    environment = dict(os.environ)
    environment["D2_READY_DB_URL"] = engine.url.render_as_string(hide_password=False)
    environment["D2_READY_DB_SCHEMA"] = engine.get_execution_options().get("schema_translate_map", {}).get(None, "")
    code = """
import os, sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from storage.database import _import_models
from storage.ingestion_artifacts import IngestionArtifactStore
from storage.chroma_store import ChromaEmbeddingStore
from services.ready_promotion import ReadyPromotionService
from tests.formal_contract_data import NOW
_import_models()
schema=os.environ["D2_READY_DB_SCHEMA"]
engine=create_engine(os.environ["D2_READY_DB_URL"],
    execution_options={"schema_translate_map": {None:schema}} if schema else {})
with ChromaEmbeddingStore(Path(sys.argv[2]), host="") as vectors:
    ReadyPromotionService(lambda:Session(engine), artifact_store=IngestionArtifactStore(Path(sys.argv[1])),
        vector_store=vectors).promote(sys.argv[3], tenant_id=1, user_id=2, now=NOW)
engine.dispose()
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(store.root), str(tmp_path / "vectors"), result.ingestion_job_id],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if corrupt:
        assert completed.returncode != 0 and "INDEX_READBACK_FAILED" in completed.stderr
        assert_not_ready(ready_case)
    else:
        assert completed.returncode == 0, completed.stderr
        assert promote(ready_case)["status"] == "ready"


@pytest.mark.parametrize("entity", [Document, Task])
def test_atomic_rollback(ready_case, entity):
    def fail(*args):
        raise RuntimeError("injected final state update failure")

    event.listen(entity, "before_update", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            promote(ready_case)
    finally:
        event.remove(entity, "before_update", fail)
    assert_not_ready(ready_case)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_parse",
        "quality",
        "missing_facts",
        "tree_incomplete",
        "tree_coverage",
        "missing_tree",
        "index_incomplete",
        "vector_missing",
        "index_integrity",
        "document",
        "source",
        "tree_version",
        "index_version",
    ],
)
def test_negative_matrix(ready_case, mutation):
    engine, _, store, vectors, result, sha, receipts = ready_case
    stage = "BUILDING_TREE"
    with Session(engine) as session, session.begin():
        task = session.scalar(select(Task).where(Task.public_id == result.ingestion_job_id))
        rows = {
            row.stage: row
            for row in session.scalars(select(TaskStageCheckpoint).where(TaskStageCheckpoint.task_id == task.id))
        }
        if mutation in {"missing_parse", "missing_facts"}:
            session.delete(rows["PARSING" if mutation == "missing_parse" else "BUILDING_FACTS"])
        elif mutation in {"tree_incomplete", "index_incomplete"}:
            rows["BUILDING_TREE" if mutation == "tree_incomplete" else "INDEXING"].status = "pending"
        elif mutation == "missing_tree":
            rows[stage].artifact_id = rows[stage].artifact_sha256 = "b" * 64
        elif mutation in {"vector_missing", "index_integrity"}:
            receipt = json.loads(store.read(1, sha, receipts["INDEXING"]))
            collection = vectors.client.get_collection(receipt["collection"])
            identifier = collection.get()["ids"][0]
            if mutation == "vector_missing":
                collection.delete(ids=[identifier])
            else:
                collection.update(ids=[identifier], embeddings=[[9.0, 0.5]])
        else:
            if mutation == "quality":
                stage = "QUALITY_CHECK"
            elif mutation == "index_version":
                stage = "INDEXING"
            payload = json.loads(store.read(1, sha, receipts[stage]))
            if mutation == "quality":
                payload["quality_status"] = "FAIL"
            elif mutation == "tree_coverage":
                payload["audit"]["source_block_coverage"] = 0.9
            elif mutation == "document":
                payload["document_id"] = 999
            elif mutation == "source":
                payload["source_sha256"] = "b" * 64
            elif mutation == "tree_version":
                payload["builder_version"] = "old"
            else:
                payload["index_policy_version"] = "old"
            digest = store.put(1, sha, json.dumps(payload, sort_keys=True).encode())
            rows[stage].artifact_id = rows[stage].artifact_sha256 = digest
    with pytest.raises((ValueError, FileNotFoundError)):
        promote(ready_case)
    assert_not_ready(ready_case)
