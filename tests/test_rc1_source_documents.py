"""Default delivery app source/session contracts with formal persistence."""

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from auth.dependencies import get_current_user
from auth.password import hash_password
from models.task import Task, TaskType
from models.tenant import Tenant
from models.user import User
from services.formal_ingestion_composition import FormalIngestionComposition
from services.upload_session_service import UploadSessionService
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import get_db
from tasks.models import TaskType as WorkerTaskType
from tasks.worker import _HANDLERS
from tests.formal_ingestion_test_harness import SOURCE, formal  # noqa: F401


@pytest.fixture
def source_case(formal, tmp_path, monkeypatch):  # noqa: F811
    _, repo, factory = formal
    service = UploadSessionService(repo, tmp_path / "uploads")
    delivery = SimpleNamespace(upload=service, repository=repo, ledger=object())
    monkeypatch.setattr("services.rc1_delivery.get_delivery", lambda: delivery)
    user = User(id=2, tenant_id=1)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        content = SOURCE.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        result = client.post("/api/v1/upload-sessions", json={
            "filename": "report.pdf", "mime_type": "application/pdf",
            "expected_size": len(content), "expected_sha256": digest,
        })
        assert result.status_code == 201
        upload_id = result.json()["upload_id"]
        assert client.post(f"/api/v1/upload-sessions/{upload_id}/content", files={
            "file": ("report.pdf", content, "application/pdf"),
        }).status_code == 200
        result = client.post(f"/api/v1/upload-sessions/{upload_id}/finalize")
        assert result.status_code == 200
        value = result.json()
        with factory() as db:
            task = db.scalar(select(Task).where(Task.public_id == value["ingestion_job_id"]))
            assert task.task_type == TaskType.FORMAL_READY_DOCUMENT.value
        yield client, value, digest, content, service, user
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_default_app_authenticated_pdf(source_case):
    client, value, digest, content, _, _ = source_case
    response = client.get(f"/api/v1/documents/{value['document_id']}/source?version={digest}&page=1")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-source-sha256"] == digest
    assert response.headers["content-disposition"].startswith("inline;")
    assert int(response.headers["x-pdf-page-count"]) > 0
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("version,page,status", [("0" * 64, 1, 409), (None, 0, 422), (None, 99999, 422)])
def test_source_version_and_page_rejected(source_case, version, page, status):
    client, value, digest, *_ = source_case
    response = client.get(f"/api/v1/documents/{value['document_id']}/source?version={version or digest}&page={page}")
    assert response.status_code == status


def test_source_cross_tenant_rejected(source_case):
    client, value, digest, *_ = source_case
    app.dependency_overrides[get_current_user] = lambda: User(id=2, tenant_id=99)
    response = client.get(f"/api/v1/documents/{value['document_id']}/source?version={digest}")
    assert response.status_code == 404


def test_source_unauthenticated_rejected(source_case):
    client, value, digest, *_ = source_case
    app.dependency_overrides.pop(get_current_user)
    response = client.get(f"/api/v1/documents/{value['document_id']}/source?version={digest}")
    assert response.status_code in (401, 403)


def test_source_modified_bytes_rejected(source_case):
    client, value, digest, content, service, user = source_case
    path = service.repository.stored_path(value["upload_id"], user.tenant_id, user.id)
    Path(path).write_bytes(content[:-1] + b"x")
    response = client.get(f"/api/v1/documents/{value['document_id']}/source?version={digest}")
    assert response.status_code == 409


def test_source_missing_file_rejected(source_case):
    client, value, digest, _, service, user = source_case
    path = Path(service.repository.stored_path(value["upload_id"], user.tenant_id, user.id))
    path.unlink()
    response = client.get(f"/api/v1/documents/{value['document_id']}/source?version={digest}")
    assert response.status_code == 404


def test_source_path_cannot_be_selected_by_client(source_case):
    client, value, digest, content, *_ = source_case
    response = client.get(f"/api/v1/documents/{value['document_id']}/source",
        params={"version": digest, "path": "../../secret.pdf", "filename": "secret.pdf"})
    assert response.status_code == 200
    assert response.content == content


def test_explicit_handler_does_not_replace_legacy():
    assert _HANDLERS[WorkerTaskType.PROCESS_DOCUMENT] == "tasks.knowledge_tasks:process_document_task"
    assert _HANDLERS[WorkerTaskType.FORMAL_READY_DOCUMENT] == "tasks.formal_ready_tasks:process_formal_ready_task"


def test_default_app_five_stage_ready_source(formal, tmp_path, monkeypatch, record_property):  # noqa: F811
    from tasks.formal_ready_tasks import process_formal_ready_task

    _, _, factory = formal
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        runtime = FormalIngestionComposition(factory, storage_root=tmp_path / "uploads",
            artifact_root=tmp_path / "artifacts", vectors=vectors,
            embedder=lambda texts: [[1.0, len(text) / 10000] for text in texts],
            embedding_identity="formal-offline-fixture")
        monkeypatch.setattr("services.rc1_delivery.get_delivery", lambda: runtime)
        with factory() as db, db.begin():
            db.get(User, 2).password_hash = hash_password("Isolated-Delivery-Password-2026")
            db.get(User, 2).email = "formal@example.com"
            db.add(Tenant(id=3, name="Other", slug="other"))
            db.flush()
            db.add(User(id=4, tenant_id=3, email="other@example.com",
                password_hash=hash_password("Isolated-Delivery-Password-2026")))

        def isolated_db():
            with factory() as db:
                yield db

        # DB isolation only: JWT verification/get_current_user are real.
        app.dependency_overrides[get_db] = isolated_db
        try:
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"email": "formal@example.com",
                "password": "Isolated-Delivery-Password-2026"})
            assert login.status_code == 200
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            assert client.get("/api/v1/auth/me").json()["id"] == 2
            data = SOURCE.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            created = client.post("/api/v1/upload-sessions", json={"filename": "report.pdf",
                "expected_size": len(data), "expected_sha256": digest}).json()
            path = "/api/v1/upload-sessions/" + created["upload_id"]
            assert client.post(path + "/content", files={"file": ("report.pdf", data)}).status_code == 200
            finalized = client.post(path + "/finalize").json()
            process_formal_ready_task(finalized["ingestion_job_id"])
            process_formal_ready_task(finalized["ingestion_job_id"])
            state = client.get(path + "/ingestion").json()
            assert state["status"] == "ready"
            assert len(state["completed_stages"]) == 5
            listed = client.get("/api/v1/upload-sessions/ready-documents").json()
            assert listed["items"][0]["content_sha256"] == digest
            from services.ready_fact_synthesis_source import ReadyFactSynthesisSource

            captured = []
            original_resolve = ReadyFactSynthesisSource.__call__

            def resolve(instance, **parameters):
                source_input = original_resolve(instance, **parameters)
                captured.append(source_input)
                return source_input

            monkeypatch.setattr(ReadyFactSynthesisSource, "__call__", resolve)
            provider_factory = Mock(side_effect=AssertionError("FACT_MUST_NOT_CREATE_PROVIDER"))
            monkeypatch.setattr("llm.factory.provider_factory.ProviderFactory.create", provider_factory)
            diagnostics = []

            def trace(frame, event, arg):
                if event == "exception" and any(part in frame.f_code.co_filename for part in (
                    "ready_fact_synthesis_source", "ingestion_fact_evidence", "grounded_answers",
                    "answer_synthesis_contracts", "answer_synthesis_workflow")):
                    kind, error, _ = arg
                    diagnostics.append((frame.f_code.co_name, frame.f_lineno, kind.__name__, str(error)))
                return trace

            if os.getenv("D13_FACT_DIAGNOSTIC") == "1":
                # Request runs on TestClient's worker threads; diagnostic only.
                import threading

                threading.settrace(trace)
            answer = client.post("/api/v1/grounded-chat", json={
                "ingestion_job_id": finalized["ingestion_job_id"],
                "question": "贵州茅台2025年总资产是多少？", "answer_language": "zh-CN"})
            if os.getenv("D13_FACT_DIAGNOSTIC") == "1":
                threading.settrace(None)
                record_property("fact_exception_trace", repr(diagnostics))
                print("FACT_EXCEPTION_TRACE", diagnostics)
            assert answer.status_code == 200, answer.text
            provider_factory.assert_not_called()
            artifact = runtime.ledger.ready_facts(finalized["ingestion_job_id"], 1, 2)
            matched = [fact for fact in artifact["facts"] if (
                fact["metric_id"], fact["fiscal_year"], fact["scope"]) == (
                "total_assets", "2025", "CONSOLIDATED")]
            assert len(matched) == 1
            fact = matched[0]
            assert fact["normalized_value"] == "303834844021.44"
            assert fact["unit"] == "CNY_YUAN" and fact["period_end"] == "2025-12-31"
            assert len(captured) == 1 and len(captured[0].evidence) == 1
            evidence = captured[0].evidence[0]
            assert evidence.payload["metric"] == "total_assets"
            assert str(evidence.payload["structured_value"]) == fact["normalized_value"]
            assert evidence.payload["provenance"]["document_version"] == digest
            citation = answer.json()["citations"][0]
            assert answer.json()["plan"]["verified"] is True
            assert str(citation["document_id"]) == str(finalized["document_id"])
            assert citation["content_sha256"] == digest
            assert citation["evidence_locator"]["page"] == citation["page"]
            assert citation["chunk_id"]
            assert citation["chunk_id"] == evidence.evidence_id
            assert citation["evidence_locator"]["locator"] == fact["source_locator"]
            record_property("requested_fact", repr({key: fact[key] for key in (
                "fact_id", "metric_id", "fiscal_year", "scope", "normalized_value", "unit", "page")}))
            record_property("actual_citation", repr(citation))
            linked_pdf = client.get(f"/api/v1/documents/{citation['document_id']}/source",
                params={"version": citation["content_sha256"], "page": citation["page"]})
            assert linked_pdf.status_code == 200 and linked_pdf.content == data
            source = client.get(f"/api/v1/documents/{finalized['document_id']}/source?version={digest}&page=1")
            assert source.status_code == 200 and source.content == data
            negative_results = {}
            for label, question in [
                ("UNKNOWN_METRIC", "贵州茅台2025年债务是多少？"),
                ("WRONG_PERIOD", "贵州茅台2022年总资产是多少？"),
                ("NO_MATCH", "贵州茅台2025年短期借款是多少？"),
            ]:
                rejected = client.post("/api/v1/grounded-chat", json={
                    "ingestion_job_id": finalized["ingestion_job_id"], "question": question,
                    "answer_language": "zh-CN"})
                assert rejected.status_code == 409, (label, rejected.text)
                assert rejected.json() == {"detail": "GROUNDED_ANSWER_NOT_AVAILABLE"}
                negative_results[label] = "SAFE_REFUSAL_NO_CITATION"
            ambiguous = client.post("/api/v1/grounded-chat", json={
                "ingestion_job_id": finalized["ingestion_job_id"],
                "question": "贵州茅台2025年总资产和总负债分别是多少？", "answer_language": "zh-CN"})
            assert ambiguous.status_code == 200, ambiguous.text
            assert ambiguous.json()["plan"]["answer_type"] == "AMBIGUOUS"
            assert ambiguous.json()["citations"] == []
            negative_results["AMBIGUOUS_METRIC"] = "CLARIFICATION_NO_CITATION"
            from retrieval.ingestion_fact_evidence import ReadyFinancialFactEvidence

            with pytest.raises(ValueError, match="EXPLICIT_FINANCIAL_QUERY_REQUIRED"):
                ReadyFinancialFactEvidence(runtime.ledger).retrieve(finalized["ingestion_job_id"],
                    tenant_id=1, user_id=2, metric="total_assets", scope="UNSUPPORTED", fiscal_year="2025")
            negative_results["WRONG_SCOPE"] = "EXPLICIT_SCOPE_REJECTED"
            provider_factory.assert_not_called()
            record_property("negative_structured_results", repr(negative_results))
            login_b = client.post("/api/v1/auth/login", json={"email": "other@example.com",
                "password": "Isolated-Delivery-Password-2026"})
            assert login_b.status_code == 200
            client.headers["Authorization"] = "Bearer " + login_b.json()["access_token"]
            assert client.get(path + "/ingestion").status_code == 404
            assert client.get(f"/api/v1/documents/{finalized['document_id']}/source?version={digest}").status_code == 404
            assert client.get("/api/v1/upload-sessions/ready-documents").json()["items"] == []
            proof = evidence.payload["provenance"]["table_row_provenance"]
            assert proof["source_kind"] == "FINANCIAL_TABLE_ROW"
            assert proof["document_id"] == citation["document_id"]
            assert proof["source_sha256"] == citation["content_sha256"]
            assert proof["page"] == citation["page"] == 57
            assert proof["table_id"] == citation["evidence_locator"]["table_id"]
            assert proof["row_id"] == citation["evidence_locator"]["row_id"]
            assert str(proof["row"]["value"]) == fact["normalized_value"]
            assert proof["row_digest"] == runtime.ledger.ready_facts(
                finalized["ingestion_job_id"], 1, 2)["facts"][artifact["facts"].index(fact)][
                    "table_row_provenance"]["row_digest"]
            record_property("table_row_authority", repr({key: proof[key] for key in (
                "source_kind", "table_id", "row_id", "page", "source_region", "row_digest")}))
        finally:
            app.dependency_overrides.pop(get_db, None)
