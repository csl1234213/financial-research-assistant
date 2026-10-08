import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import app
from models.tenant import Tenant
from services.filing_discovery import DiscoveredFiling
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database(
    "test_knowledge_integration.db"
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
        "email": "knowledge-test@example.com",
        "password": "secure123",
    })
    assert resp.status_code == 201
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
class TestKnowledgeAPI:
    def test_knowledge_status_code(self, client, auth_headers):
        response = client.get("/api/v1/knowledge", headers=auth_headers)
        assert response.status_code == 200

    def test_knowledge_json_structure(self, client, auth_headers):
        response = client.get("/api/v1/knowledge", headers=auth_headers)
        data = response.json()
        assert isinstance(data, dict)
        assert "documents" in data
        assert "document_count" in data
        assert "companies" in data

    def test_knowledge_documents_is_list(self, client, auth_headers):
        response = client.get("/api/v1/knowledge", headers=auth_headers)
        data = response.json()
        assert isinstance(data["documents"], list)

    def test_knowledge_document_count_is_int(self, client, auth_headers):
        response = client.get("/api/v1/knowledge", headers=auth_headers)
        data = response.json()
        assert isinstance(data["document_count"], int)

    def test_knowledge_companies_is_list(self, client, auth_headers):
        response = client.get("/api/v1/knowledge", headers=auth_headers)
        data = response.json()
        assert isinstance(data["companies"], list)

    def test_discover_sec_filing_persists_source_and_queues_task(
        self,
        client,
        auth_headers,
        monkeypatch,
        tmp_path,
    ):
        filing = DiscoveredFiling(
            company="Microsoft Corporation",
            cik="0000789019",
            form="10-Q",
            filing_date="2025-02-01",
            report_date="2024-12-31",
            filename="Microsoft_10Q_2024-12-31_000078901925000001.html",
            source_url="https://www.sec.gov/Archives/edgar/data/789019/report.html",
            content=(
                b"<!doctype html><html><body><h1>Microsoft Corporation</h1>"
                b"<p>Quarterly report revenue table with sufficient text. "
                b"This mock filing contains enough public filing narrative for the parser contract test.</p>"
                b"</body></html>"
            ),
        )

        class Broker:
            enabled = False

        monkeypatch.setattr("api.routers.knowledge.UPLOAD_DIR", tmp_path)
        monkeypatch.setattr("api.routers.knowledge.can_upload", lambda *_: True)
        monkeypatch.setattr("api.routers.knowledge.record_usage", lambda **_: None)
        monkeypatch.setattr("api.routers.knowledge.get_broker", lambda: Broker())
        monkeypatch.setattr(
            "api.routers.knowledge.discover_latest_company_filing",
            lambda company: filing,
        )

        response = client.post(
            "/api/v1/knowledge/discover",
            json={"company": "Microsoft"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "downloaded"
        assert payload["source_type"] == "sec_edgar"
        assert payload["source_url"].startswith("https://www.sec.gov/")
        assert list(tmp_path.rglob(filing.filename))

        knowledge = client.get("/api/v1/knowledge", headers=auth_headers).json()
        assert knowledge["items"][0]["source_url"] == filing.source_url

    def test_discover_cninfo_annual_report_preserves_audit_provenance(
        self,
        client,
        auth_headers,
        monkeypatch,
        tmp_path,
    ):
        import fitz

        pdf = fitz.open()
        pdf.new_page().insert_text(
            (72, 72),
            "\u8d35\u5dde\u8305\u53f0 2025 \u5e74\u5e74\u5ea6\u62a5\u544a",
            fontname="china-s",
        )
        pdf.new_page().insert_text(
            (72, 72),
            "\u5ba1\u8ba1\u62a5\u544a \u5929\u5065\u5ba1\u30142026\u30158-346\u53f7",
            fontname="china-s",
        )
        content = pdf.tobytes()
        pdf.close()
        filing = DiscoveredFiling(
            company="贵州茅台",
            cik="600519",
            form="ANNUAL",
            filing_date="2026-04-17",
            report_date="2025-12-31",
            filename="贵州茅台_2025年度报告_审计_2026-04-17.pdf",
            source_url="https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
            content=content,
            source_type="cninfo",
            stock_code="600519",
            exchange="sse",
            report_type="annual",
            report_year=2025,
            audited=True,
        )

        class Broker:
            enabled = False

        monkeypatch.setattr("api.routers.knowledge.UPLOAD_DIR", tmp_path)
        monkeypatch.setattr("api.routers.knowledge.can_upload", lambda *_: True)
        monkeypatch.setattr("api.routers.knowledge.record_usage", lambda **_: None)
        monkeypatch.setattr("api.routers.knowledge.get_broker", lambda: Broker())
        monkeypatch.setattr(
            "api.routers.knowledge.discover_latest_company_filing",
            lambda company: filing,
        )

        response = client.post(
            "/api/v1/knowledge/discover",
            json={"company": "贵州茅台"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source_type"] == "cninfo"
        assert payload["source_stock_code"] == "600519"
        assert payload["source_exchange"] == "sse"
        assert payload["source_report_year"] == 2025
        assert payload["source_audited"] is True
        assert list(tmp_path.rglob(filing.filename))

        knowledge = client.get("/api/v1/knowledge", headers=auth_headers).json()
        assert knowledge["items"][0]["source_url"] == filing.source_url
        assert knowledge["items"][0]["source_type"] == "cninfo"

    def test_knowledge_statistics_status_code(self, client, auth_headers):
        response = client.get("/api/v1/knowledge/statistics", headers=auth_headers)
        assert response.status_code == 200

    def test_knowledge_statistics_json_structure(self, client, auth_headers):
        response = client.get("/api/v1/knowledge/statistics", headers=auth_headers)
        data = response.json()
        assert isinstance(data, dict)
        assert "documents" in data
        assert "companies" in data
        assert "chunks" in data
        assert "embeddings" in data

    def test_knowledge_statistics_values_are_int(self, client, auth_headers):
        response = client.get("/api/v1/knowledge/statistics", headers=auth_headers)
        data = response.json()
        assert isinstance(data["documents"], int)
        assert isinstance(data["companies"], int)
        assert isinstance(data["chunks"], int)
        assert isinstance(data["embeddings"], int)
