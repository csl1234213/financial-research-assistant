"""Mandatory real formal PostgreSQL/tusd/Redis/Chroma durability acceptance."""

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import redis
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from api.routers.tus_gateway import build_tus_gateway_router
from api.routers.tus_hooks import build_tus_hook_router
from auth.jwt import create_access_token
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task
from models.tenant import Tenant
from models.user import User
from services.formal_ingestion_composition import FormalIngestionComposition
from services.tus_completed_upload import TusCompletedUpload
from services.tus_session_policy import TusSessionPolicy
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import get_db
from tasks.ingestion_stream_consumer import IngestionStreamConsumer
from tasks.ingestion_stream_publisher import IngestionStreamPublisher

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "tests/fixtures/moutai-standard-statements-2025.pdf"


@pytest.fixture
def migrated_postgres():
    url = os.environ.get("P23_ISOLATED_POSTGRES_URL")
    if not url:
        pytest.fail("D2-C real PostgreSQL E2E cannot skip")
    parsed = make_url(url)
    assert parsed.host == "127.0.0.1" and parsed.database == "p23_upload_test"
    schema = "p23_formal_live_" + uuid4().hex
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine.dispose()

    @event.listens_for(engine, "connect")
    def scope(connection, _):
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        connection.commit()

    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with Session(engine) as session, session.begin():
            session.add(Tenant(id=1, name="Formal live", slug="formal-live"))
            session.flush()
            session.add(User(id=2, tenant_id=1, email="formal-live@example.test", password_hash="fixture"))
        yield engine, schema
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def docker(*arguments):
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=True, timeout=40).stdout.strip()


def test_real_formal_tus_redis_restart_and_duplicate_delivery(migrated_postgres, tmp_path, record_property):
    assert tmp_path.drive.upper() == "D:"
    engine, schema = migrated_postgres
    factory = lambda: Session(engine)  # noqa: E731
    identity = uuid4().hex
    redis_name, tus_name = "p23-formal-redis-" + identity, "p23-formal-tus-" + identity
    containers = []
    redis_client, upstream, server, thread = None, None, None, None
    released, committed = threading.Event(), threading.Event()
    counts = {"experimental": 0, "enhancement": 0, "answer": 0, "index_embedding": 0}
    old_main, old_threads = sys.getprofile(), threading.getprofile()

    def observe(frame, event_name, _):
        if event_name != "call":
            return
        module = frame.f_globals.get("__name__", "")
        if module in {
            "storage.upload_session_pilot",
            "storage.upload_registration_sql",
            "storage.ingestion_sql_models",
            "tasks.ingestion_ledger",
            "tasks.upload_outbox",
            "tasks.ingestion_source",
        }:
            counts["experimental"] += 1
        if module in {"services.index_subject_enhancement", "document_compatibility.narrative_subject_context"}:
            counts["enhancement"] += 1
        if module.startswith("core.answer_synthesis"):
            counts["answer"] += 1

    sys.setprofile(observe)
    threading.setprofile(observe)
    try:
        image = docker("image", "inspect", "redis:7.4-alpine", "--format", "{{.Id}}")
        docker(
            "run",
            "-d",
            "--name",
            redis_name,
            "--label",
            "financial.test=p23-formal-d2c",
            "-p",
            "127.0.0.1::6379",
            image,
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        )
        containers.append(redis_name)
        port = int(docker("port", redis_name, "6379/tcp").split(":")[-1])
        redis_client = redis.Redis(
            host="127.0.0.1", port=port, decode_responses=True, socket_timeout=2, socket_connect_timeout=2
        )
        assert redis_client.ping()
        tus_root = tmp_path / "tus"
        tus_root.mkdir()
        with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:

            def embeddings(texts):
                counts["index_embedding"] += 1
                return [[1.0, len(text) / 10000] for text in texts]

            runtime = FormalIngestionComposition(
                factory,
                storage_root=tmp_path / "business",
                artifact_root=tmp_path / "artifacts",
                vectors=vectors,
                embedder=embeddings,
                embedding_identity="formal-live-fixture",
            )
            app = runtime.app(
                transport_protocol="tus", completed_transport=TusCompletedUpload(runtime.upload, tus_root)
            )
            policy = TusSessionPolicy(runtime.repository)
            upstream = httpx.Client(base_url="http://127.0.0.1:50263", timeout=20, trust_env=False)
            app.include_router(build_tus_gateway_router(policy, upstream))
            app.include_router(build_tus_hook_router(policy))

            def db():
                with factory() as session:
                    yield session

            app.dependency_overrides[get_db] = db

            class LostFinalizeResponse:
                def __init__(self, app):
                    self.app = app
                    self.used = False

                async def __call__(self, scope, receive, send):
                    inject = scope.get("path", "").endswith("/finalize") and not self.used
                    if inject:
                        self.used = True

                    async def delayed(message):
                        if inject and message["type"] == "http.response.start":
                            committed.set()
                            assert await asyncio.to_thread(released.wait, 20)
                        await send(message)

                    await self.app(scope, receive, delayed)

            app.add_middleware(LostFinalizeResponse)
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=50262, log_level="error"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                thread.join(0.05)
            docker(
                "run",
                "-d",
                "--name",
                tus_name,
                "--label",
                "financial.test=p23-formal-d2c",
                "-p",
                "127.0.0.1:50263:8080",
                "--mount",
                f"type=bind,source={tus_root},target=/test-data",
                "tusproject/tusd@sha256:d5e913b2c3884fcd1af7a9b1eb9262fa1d8e01e56db028ccd74b502530251e2e",
                "-host=0.0.0.0",
                "-upload-dir=/test-data",
                "-max-size=52428800",
                "-hooks-http=http://host.docker.internal:50262/internal/tus/hooks",
                "-hooks-http-forward-headers=Authorization",
                "-hooks-enabled-events=pre-create,post-create,pre-finish",
                "-hooks-http-retry=0",
            )
            containers.append(tus_name)
            deadline = time.monotonic() + 10
            while True:
                try:
                    if upstream.options("/files/").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline
                threading.Event().wait(0.1)
            headers = {"Authorization": "Bearer " + create_access_token({"sub": "2"})}
            data = PDF.read_bytes()
            with httpx.Client(base_url="http://127.0.0.1:50262", timeout=20, trust_env=False) as client:
                response = client.post(
                    "/upload-sessions",
                    headers=headers,
                    json={
                        "filename": "report.pdf",
                        "expected_size": len(data),
                        "expected_sha256": hashlib.sha256(data).hexdigest(),
                    },
                )
                assert response.status_code == 201, response.text
                upload_id = response.json()["upload_id"]
                path = "/upload-transport/" + upload_id
                tus_headers = {**headers, "Tus-Resumable": "1.0.0"}
                assert client.head(path).status_code in {401, 403}
                response = client.post(path, headers={**tus_headers, "Upload-Length": str(len(data))})
                assert response.status_code == 201, response.text
                midpoint = len(data) // 2
                for offset, chunk in ((0, data[:midpoint]), (midpoint, data[midpoint:])):
                    assert (
                        client.patch(
                            path,
                            headers={
                                **tus_headers,
                                "Upload-Offset": str(offset),
                                "Content-Type": "application/offset+octet-stream",
                            },
                            content=chunk,
                        ).status_code
                        == 204
                    )
                    assert int(client.head(path, headers=tus_headers).headers["Upload-Offset"]) == offset + len(chunk)
                business = "/upload-sessions/" + upload_id
                response = client.post(business + "/verify", headers=headers)
                assert response.status_code == 200 and response.json()["status"] == "VERIFIED", response.text
                wire = (
                    f"POST {business}/finalize HTTP/1.1\r\nHost: 127.0.0.1:50262\r\n"
                    f"Authorization: {headers['Authorization']}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                try:
                    with socket.create_connection(("127.0.0.1", 50262), timeout=10) as connection:
                        connection.sendall(wire.encode("ascii"))
                        assert committed.wait(10)
                        finalized = runtime.repository.get(upload_id, 1, 2)
                        assert finalized.state.value == "FINALIZED"
                        connection.settimeout(0.2)
                        with pytest.raises(socket.timeout):
                            connection.recv(1)
                finally:
                    released.set()
                response = client.post(business + "/finalize", headers=headers)
                assert response.status_code == 200
                assert response.json()["ingestion_job_id"] == finalized.ingestion_job_id
                assert client.post(business + "/finalize", headers=headers).json() == response.json()

            consumer = IngestionStreamConsumer(
                redis_client, factory, runtime.runner, namespace="p23:" + identity, consumer="formal-worker"
            )
            # Finalize committed before Redis outage; retry is a durable Task obligation.
            docker("stop", redis_name)

            publish = IngestionStreamPublisher(redis_client, namespace="p23:" + identity)

            now = datetime.now(timezone.utc)
            assert runtime.dispatcher.dispatch_one(publish, now=now) == "not_delivered"
            with factory() as session:
                obligation = session.scalar(select(Task))
                assert obligation.public_id == finalized.ingestion_job_id
                assert obligation.status == "pending" and obligation.dispatch_state == "pending"
            docker("start", redis_name)
            # Docker may allocate a new host port when restarting an ephemeral
            # publication; refresh the test transport, not the durable Task.
            redis_client.close()
            port = int(docker("port", redis_name, "6379/tcp").split(":")[-1])
            redis_client = redis.Redis(
                host="127.0.0.1", port=port, decode_responses=True, socket_timeout=2, socket_connect_timeout=2
            )
            consumer.redis = redis_client
            publish.redis = redis_client
            deadline = time.monotonic() + 15
            while True:
                try:
                    if redis_client.ping():
                        break
                except (redis.ConnectionError, redis.TimeoutError):
                    pass
                assert time.monotonic() < deadline, "isolated Redis did not recover"
                threading.Event().wait(0.1)
            consumer.initialize()
            assert runtime.dispatcher.dispatch_one(publish, now=now + timedelta(seconds=10)) == "delivered"
            message_id, fields = redis_client.xreadgroup(
                consumer.group, consumer.consumer, {consumer.stream: ">"}, count=1, block=1000
            )[0][1][0]
            # Execute genuine operators; stop strictly before formal promotion.
            for _ in range(5):
                assert runtime.executor.run_one(finalized.ingestion_job_id) == "completed"
            assert runtime.ledger.status(finalized.ingestion_job_id, 1, 2)["status"] != "ready"
            with factory() as session:
                before = [
                    (row.checkpoint_id, row.artifact_id, row.artifact_sha256)
                    for row in session.scalars(select(TaskStageCheckpoint).order_by(TaskStageCheckpoint.checkpoint_id))
                ]
                fact_checkpoint = session.scalar(select(TaskStageCheckpoint).where(
                    TaskStageCheckpoint.stage == "BUILDING_FACTS"))
                facts = json.loads(runtime.artifacts.read(1, hashlib.sha256(data).hexdigest(),
                                                           fact_checkpoint.artifact_sha256))
                assert facts["rows_seen"] > 0 and len(facts["facts"]) > 0
                record_property("REAL_RECONSTRUCTED_ROWS", facts["rows_seen"])
                record_property("REAL_ELIGIBLE_FACTS", len(facts["facts"]))
            artifact_files_before = sorted(
                str(path.relative_to(tmp_path / "artifacts"))
                for path in (tmp_path / "artifacts").rglob("*")
                if path.is_file()
            )
            child = """
import os, sys, json
import importlib.abc
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from services.ready_promotion import ReadyPromotionService
from storage.ingestion_artifacts import IngestionArtifactStore
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import _import_models
from storage.upload_session_repository import UploadSessionRepository
_import_models()
class RejectExperimental(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'storage.upload_session_pilot','storage.upload_registration_sql',
                        'storage.ingestion_sql_models','tasks.ingestion_ledger','tasks.upload_outbox'}:
            raise AssertionError('Experimental READY import: ' + fullname)
sys.meta_path.insert(0, RejectExperimental())
counts={'model':0,'embedding':0,'rebuild':0,'experimental':0,'enhancement':0}
def observe(frame,event,arg):
    if event != 'call': return
    module=frame.f_globals.get('__name__','')
    if module.startswith('llm'): counts['model']+=1
    if module.startswith('chromadb.utils.embedding_functions') and frame.f_code.co_name == '__call__':
        counts['embedding']+=1
    if module == 'tasks.ingestion_index_stage' and frame.f_code.co_name == 'execute': counts['rebuild']+=1
    if module in {'storage.upload_session_pilot','storage.upload_registration_sql',
                  'storage.ingestion_sql_models','tasks.ingestion_ledger','tasks.upload_outbox'}:
        counts['experimental']+=1
    if module in {'services.index_subject_enhancement','document_compatibility.narrative_subject_context'}:
        counts['enhancement']+=1
engine = create_engine(os.environ['P23_ISOLATED_POSTGRES_URL'],
    execution_options={'schema_translate_map': {None: os.environ['P23_READY_SCHEMA']}})
root=Path(sys.argv[1])
value=UploadSessionRepository(lambda: Session(engine)).finalize(
    sys.argv[3],1,2,datetime.now(timezone.utc))
assert value.ingestion_job_id == sys.argv[2]
print('PROCESS_RESTART_AFTER_COMMIT=PASS')
with ChromaEmbeddingStore(root/'vectors', host='') as vectors:
    sys.setprofile(observe)
    ReadyPromotionService(lambda: Session(engine), artifact_store=IngestionArtifactStore(root/'artifacts'),
        vector_store=vectors).promote(sys.argv[2],tenant_id=1,user_id=2,now=datetime.now(timezone.utc))
    sys.setprofile(None)
assert not any(counts.values()), counts
print('READY_CALL_COUNTERS='+json.dumps(counts))
print('POST_INDEX_RESTART_READY=PASS')
"""
            environment = dict(os.environ, P23_READY_SCHEMA=schema)
            result = subprocess.run(
                [sys.executable, "-c", child, str(tmp_path), finalized.ingestion_job_id, upload_id],
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "POST_INDEX_RESTART_READY=PASS" in result.stdout
            assert "PROCESS_RESTART_AFTER_COMMIT=PASS" in result.stdout
            ready_counts = json.loads(
                next(
                    line.split("=", 1)[1]
                    for line in result.stdout.splitlines()
                    if line.startswith("READY_CALL_COUNTERS=")
                )
            )
            for key, value in ready_counts.items():
                record_property("READY_" + key.upper() + "_CALLS", value)
            assert consumer.handle(message_id, fields) == "ready"
            publish(finalized.ingestion_job_id, 1, "process_document")
            assert consumer.consume_one() == "ready"
            with factory() as session:
                assert [
                    (row.checkpoint_id, row.artifact_id, row.artifact_sha256)
                    for row in session.scalars(select(TaskStageCheckpoint).order_by(TaskStageCheckpoint.checkpoint_id))
                ] == before
                assert len(session.scalars(select(Document)).all()) == 1
                tasks = session.scalars(select(Task)).all()
                assert len(tasks) == 1
                task = tasks[0]
                assert task.status == "success" and task.dispatch_state == "delivered"
            assert (
                sorted(
                    str(path.relative_to(tmp_path / "artifacts"))
                    for path in (tmp_path / "artifacts").rglob("*")
                    if path.is_file()
                )
                == artifact_files_before
            )
            assert counts["index_embedding"] > 0
            assert counts["experimental"] == counts["enhancement"] == counts["answer"] == 0
            with httpx.Client(base_url="http://127.0.0.1:50262", timeout=20, trust_env=False) as client:
                progress = client.get(business + "/ingestion", headers=headers)
                assert progress.status_code == 200 and progress.json()["status"] == "ready"
                reports = client.get("/upload-sessions/ready-documents", headers=headers)
                assert reports.status_code == 200 and len(reports.json()["items"]) == 1
                assert reports.json()["items"][0]["document_id"] == int(finalized.document_id)
            for key, value in counts.items():
                record_property(key.upper() + "_CALLS", value)
            record_property("MOCKED_EXTERNAL_COMPONENTS", "deterministic indexing embeddings only")
    finally:
        released.set()
        sys.setprofile(old_main)
        threading.setprofile(old_threads)
        if server:
            server.should_exit = True
        if thread:
            thread.join(10)
        if upstream:
            upstream.close()
        if redis_client:
            redis_client.close()
        for name in reversed(containers):
            docker("stop", name)
