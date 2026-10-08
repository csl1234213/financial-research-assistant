from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import app
from models.document import Document
from models.tenant import Tenant
from models.user import User
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_knowledge_iso.db")
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


@pytest.fixture()
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


REGISTER_URL = "/api/v1/auth/register"
AUTH_ME_URL = "/api/v1/auth/me"
TENANT_ME_URL = "/api/v1/tenant/me"
KNOWLEDGE_URL = "/api/v1/knowledge"


class RecordingVectorStore:
    calls: list[tuple[str, int]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def delete_document(self, document_id: str, *, tenant_id: int) -> None:
        self.calls.append((document_id, tenant_id))


def _register_and_get_token(client: TestClient, email: str = "test@example.com") -> str:
    resp = client.post(REGISTER_URL, json={"email": email, "password": "secure123"})
    assert resp.status_code == 201
    return resp.json()["token"]


class TestDocumentModel:
    def test_create_document_with_tenant(self, db_session):
        tenant = db_session.query(Tenant).filter(Tenant.slug == "default").first()
        doc = Document(
            filename="test_report.pdf",
            company="Tesla",
            report_type="Financial Report",
            period="Q2_2025",
            tenant_id=tenant.id,
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)

        assert doc.id is not None
        assert doc.filename == "test_report.pdf"
        assert doc.tenant_id == tenant.id
        assert doc.status == "indexed"

    def test_document_tenant_relationship(self, db_session):
        tenant = db_session.query(Tenant).filter(Tenant.slug == "default").first()
        doc = Document(
            filename="rel_doc.pdf",
            company="NVIDIA",
            period="Q3_2025",
            tenant_id=tenant.id,
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)

        assert doc.tenant is not None
        assert doc.tenant.id == tenant.id

        db_session.refresh(tenant)
        assert len(tenant.documents) >= 1


class TestTenantDocumentIsolation:
    def test_tenant_a_cannot_see_tenant_b_documents(self, db_session):
        tenant_a = db_session.query(Tenant).filter(Tenant.slug == "default").first()
        tenant_b = Tenant(name="Tenant B", slug="tenant-b")
        db_session.add(tenant_b)
        db_session.commit()
        db_session.refresh(tenant_b)

        doc_a = Document(
            filename="a_secret.pdf",
            company="Tesla",
            period="Q2_2025",
            tenant_id=tenant_a.id,
        )
        doc_b = Document(
            filename="b_secret.pdf",
            company="NVIDIA",
            period="Q3_2025",
            tenant_id=tenant_b.id,
        )
        db_session.add_all([doc_a, doc_b])
        db_session.commit()

        a_docs = (
            db_session.query(Document)
            .filter(Document.tenant_id == tenant_a.id)
            .all()
        )
        b_docs = (
            db_session.query(Document)
            .filter(Document.tenant_id == tenant_b.id)
            .all()
        )

        assert len(a_docs) == 1
        assert a_docs[0].filename == "a_secret.pdf"
        assert len(b_docs) == 1
        assert b_docs[0].filename == "b_secret.pdf"

    def test_knowledge_endpoint_requires_auth(self, client):
        response = client.get(KNOWLEDGE_URL)
        assert response.status_code == 401

    def test_knowledge_endpoint_tenant_scoped(self, client, db_session):
        token = _register_and_get_token(client, "knowledge-test@example.com")

        tenant = db_session.query(Tenant).filter(Tenant.slug == "default").first()
        doc = Document(
            filename="visible_doc.pdf",
            company="Tesla",
            period="Q2_2025",
            tenant_id=tenant.id,
        )
        db_session.add(doc)
        db_session.commit()

        response = client.get(
            KNOWLEDGE_URL, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "visible_doc.pdf" in data["documents"]
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["id"] == doc.id
        assert item["filename"] == "visible_doc.pdf"
        assert item["company"] == "Tesla"
        assert item["period"] == "Q2_2025"
        assert item["status"] == "indexed"
        assert item["chunk_count"] == 0
        assert item["byte_size"] is None
        assert item["content_sha256"] is None
        assert item["can_delete"] is True
        assert isinstance(item["uploaded_at"], str)

    def test_knowledge_statistics_tenant_scoped(self, client, db_session):
        token = _register_and_get_token(client, "stats-test@example.com")

        tenant = db_session.query(Tenant).filter(Tenant.slug == "default").first()
        doc = Document(
            filename="stats_doc.pdf",
            company="Apple",
            period="Q1_2025",
            tenant_id=tenant.id,
        )
        db_session.add(doc)
        db_session.commit()

        response = client.get(
            "/api/v1/knowledge/statistics",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["documents"] >= 1

    def test_delete_document_is_tenant_scoped(
        self,
        client,
        db_session,
        monkeypatch,
        tmp_path: Path,
    ):
        token = _register_and_get_token(client, "delete-scope@example.com")
        default_tenant = (
            db_session.query(Tenant)
            .filter(Tenant.slug == "default")
            .one()
        )
        other_tenant = Tenant(name="Other Tenant", slug="delete-other")
        db_session.add(other_tenant)
        db_session.flush()
        foreign_document = Document(
            filename="foreign.pdf",
            company="NVIDIA",
            period="Q1_2027",
            status="indexed",
            tenant_id=other_tenant.id,
        )
        db_session.add(foreign_document)
        db_session.commit()

        RecordingVectorStore.calls = []
        monkeypatch.setattr(
            "api.routers.knowledge.ChromaEmbeddingStore",
            RecordingVectorStore,
        )
        monkeypatch.setattr(
            "api.routers.knowledge.UPLOAD_DIR",
            tmp_path,
        )

        response = client.delete(
            f"{KNOWLEDGE_URL}/{foreign_document.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Document not found"}
        assert RecordingVectorStore.calls == []
        db_session.expire_all()
        assert db_session.get(Document, foreign_document.id) is not None
        assert default_tenant.id != other_tenant.id

    def test_delete_document_removes_exact_vectors_and_upload_directory(
        self,
        client,
        db_session,
        monkeypatch,
        tmp_path: Path,
    ):
        token = _register_and_get_token(client, "delete-own@example.com")
        owner = (
            db_session.query(User)
            .filter(User.email == "delete-own@example.com")
            .one()
        )
        tenant = (
            db_session.query(Tenant)
            .filter(Tenant.slug == "default")
            .one()
        )
        document = Document(
            filename="owned.pdf",
            company="Tesla",
            period="Q2_2025",
            status="indexed",
            tenant_id=tenant.id,
            content_sha256="a" * 64,
            byte_size=16,
            indexed_chunk_count=2,
            uploaded_by_user_id=owner.id,
        )
        db_session.add(document)
        db_session.commit()
        db_session.refresh(document)
        document_id = document.id

        upload_directory = (
            tmp_path / str(tenant.id) / f"{document_id}-test-upload"
        )
        upload_directory.mkdir(parents=True)
        (upload_directory / document.filename).write_bytes(b"test-pdf-content")
        unrelated_directory = (
            tmp_path / str(tenant.id) / "999-test-upload"
        )
        unrelated_directory.mkdir()
        (unrelated_directory / "keep.pdf").write_bytes(b"keep")

        RecordingVectorStore.calls = []
        monkeypatch.setattr(
            "api.routers.knowledge.ChromaEmbeddingStore",
            RecordingVectorStore,
        )
        monkeypatch.setattr(
            "api.routers.knowledge.UPLOAD_DIR",
            tmp_path,
        )

        response = client.delete(
            f"{KNOWLEDGE_URL}/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "deleted": True,
            "document_id": document_id,
        }
        assert RecordingVectorStore.calls == [
            (f"tenant_{tenant.id}_document_{document_id}", tenant.id)
        ]
        assert not upload_directory.exists()
        assert unrelated_directory.is_dir()
        db_session.expire_all()
        assert db_session.get(Document, document_id) is None

    def test_processing_document_cannot_be_deleted(
        self,
        client,
        db_session,
        monkeypatch,
        tmp_path: Path,
    ):
        token = _register_and_get_token(client, "delete-active@example.com")
        owner = (
            db_session.query(User)
            .filter(User.email == "delete-active@example.com")
            .one()
        )
        tenant = (
            db_session.query(Tenant)
            .filter(Tenant.slug == "default")
            .one()
        )
        document = Document(
            filename="active.pdf",
            company="Tesla",
            period="Q2_2025",
            status="processing",
            tenant_id=tenant.id,
            uploaded_by_user_id=owner.id,
        )
        db_session.add(document)
        db_session.commit()

        RecordingVectorStore.calls = []
        monkeypatch.setattr(
            "api.routers.knowledge.ChromaEmbeddingStore",
            RecordingVectorStore,
        )
        monkeypatch.setattr(
            "api.routers.knowledge.UPLOAD_DIR",
            tmp_path,
        )

        response = client.delete(
            f"{KNOWLEDGE_URL}/{document.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 409
        assert RecordingVectorStore.calls == []
        db_session.expire_all()
        assert db_session.get(Document, document.id) is not None

    def test_workspace_member_can_delete_document_owned_by_another_user(
        self,
        client,
        db_session,
        monkeypatch,
        tmp_path: Path,
    ):
        token = _register_and_get_token(
            client,
            "delete-denied-other-owner@example.com",
        )
        tenant = (
            db_session.query(Tenant)
            .filter(Tenant.slug == "default")
            .one()
        )
        other_user = User(
            email="other-owner@example.com",
            password_hash="not-used",
            tenant_id=tenant.id,
        )
        db_session.add(other_user)
        db_session.flush()
        document = Document(
            filename="other-user.pdf",
            company="Tesla",
            period="Q2_2025",
            status="indexed",
            tenant_id=tenant.id,
            uploaded_by_user_id=other_user.id,
        )
        db_session.add(document)
        db_session.commit()
        document_id = document.id

        RecordingVectorStore.calls = []
        monkeypatch.setattr(
            "api.routers.knowledge.ChromaEmbeddingStore",
            RecordingVectorStore,
        )
        monkeypatch.setattr(
            "api.routers.knowledge.UPLOAD_DIR",
            tmp_path,
        )

        response = client.delete(
            f"{KNOWLEDGE_URL}/{document.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "deleted": True,
            "document_id": document_id,
        }
        assert RecordingVectorStore.calls == [
            (f"tenant_{tenant.id}_document_{document_id}", tenant.id)
        ]
        db_session.expire_all()
        assert db_session.get(Document, document_id) is None

    def test_user_can_delete_legacy_document_without_owner(
        self,
        client,
        db_session,
        monkeypatch,
        tmp_path: Path,
    ):
        token = _register_and_get_token(client, "delete-legacy@example.com")
        tenant = (
            db_session.query(Tenant)
            .filter(Tenant.slug == "default")
            .one()
        )
        document = Document(
            filename="legacy.pdf",
            company="Tesla",
            period="Q2_2025",
            status="indexed",
            tenant_id=tenant.id,
            uploaded_by_user_id=None,
        )
        db_session.add(document)
        db_session.commit()
        db_session.refresh(document)
        document_id = document.id

        monkeypatch.setattr(
            "api.routers.knowledge.ChromaEmbeddingStore",
            RecordingVectorStore,
        )
        monkeypatch.setattr("api.routers.knowledge.UPLOAD_DIR", tmp_path)

        response = client.delete(
            f"{KNOWLEDGE_URL}/{document_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "deleted": True,
            "document_id": document_id,
        }
        db_session.expire_all()
        assert db_session.get(Document, document_id) is None
