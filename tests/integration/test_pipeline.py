import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import app
from models.tenant import Tenant
from models.user import User
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database(
    "test_pipeline_integration.db"
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        existing = db.query(Tenant).filter(Tenant.slug == "default").first()
        if existing is None:
            db.add(Tenant(name="Default Workspace", slug="default"))
            db.commit()
    finally:
        db.close()

    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    resp = client.post("/api/v1/auth/register", json={
        "email": "pipeline-test@example.com",
        "password": "secure123",
    })
    assert resp.status_code == 201
    token = resp.json()["token"]
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "pipeline-test@example.com").one()
        user.role = "admin"
        db.commit()
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
    b"startxref\n190\n"
    b"%%EOF"
)


def _fake_run_agent(question, company=None, **_request_scope):
    return {
        "answer": "# Pipeline Test Report\n\nAll systems operational.",
        "citations": [
            {"rank": 1, "source": "pipeline_test.pdf", "chunk_id": "pt_0", "similarity": 0.99, "preview": "OK"},
        ],
        "research_mode": "default",
        "evidence_count": 1,
        "intent": {"intent": "SINGLE_COMPANY", "companies": ["TestCorp"]},
        "plan": {"intent": "single_company", "task_count": 0, "tasks": []},
        "routing": {"provider": "openai", "model": "gpt-4o"},
        "planning": {"task_type": "document_qa", "complexity": "low"},
        "execution": {"strategy": "rag"},
        "workflow": {"type": "rag", "status": "DONE", "completed_steps": 3},
    }


@pytest.mark.integration
class TestPipeline:
    def test_full_pipeline_upload_refresh_chat(self, client, auth_headers):
        with patch("api.routers.refresh.refresh_knowledge_base"):
            upload_response = client.post(
                "/api/v1/upload",
                files={"file": ("pipeline_test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
                headers=auth_headers,
            )
        assert upload_response.status_code == 200
        assert upload_response.json()["message"] == "upload success"

        with patch("api.routers.refresh.refresh_knowledge_base"):
            refresh_response = client.post("/api/v1/refresh", headers=auth_headers)
        assert refresh_response.status_code == 200
        assert refresh_response.json()["status"] == "ok"

        with patch("api.services.chat_service.run_agent", side_effect=_fake_run_agent):
            chat_response = client.post("/api/v1/chat", json={
                "question": "Is the system operational?",
            })
        assert chat_response.status_code == 200
        chat_data = chat_response.json()
        assert chat_data["report"] != ""
        assert len(chat_data["citations"]) >= 1
        assert chat_data["citations"][0]["source"] == "pipeline_test.pdf"

    def test_pipeline_knowledge_after_upload(self, client, auth_headers):
        with patch("api.routers.refresh.refresh_knowledge_base"):
            client.post(
                "/api/v1/upload",
                files={"file": ("knowledge_test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
                headers=auth_headers,
            )

        knowledge_response = client.get("/api/v1/knowledge", headers=auth_headers)
        assert knowledge_response.status_code == 200
        data = knowledge_response.json()
        assert isinstance(data["documents"], list)
        assert isinstance(data["document_count"], int)
        assert isinstance(data["companies"], list)

    def test_pipeline_health_after_operations(self, client, auth_headers):
        with patch("api.routers.refresh.refresh_knowledge_base"):
            client.post(
                "/api/v1/upload",
                files={"file": ("health_test.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
                headers=auth_headers,
            )

        health_response = client.get("/api/v1/health")
        assert health_response.status_code == 200
        assert health_response.json()["status"] in {"ok", "degraded"}
