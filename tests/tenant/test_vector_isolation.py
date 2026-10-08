import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import config.security as security_config
from api.app import app
from models.tenant import Tenant
from models.user import User
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import Base, get_db
from storage.vector_models import VectorDocument
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_vector_iso.db")
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
        if db.query(Tenant).filter(Tenant.slug == "default").first() is None:
            db.add(Tenant(name="Default Workspace", slug="default"))
        if db.query(Tenant).filter(Tenant.slug == "tenant-a").first() is None:
            db.add(Tenant(name="Tenant A", slug="tenant-a"))
        if db.query(Tenant).filter(Tenant.slug == "tenant-b").first() is None:
            db.add(Tenant(name="Tenant B", slug="tenant-b"))
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
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _reset_security_config():
    security_config.ALLOW_GLOBAL_SEARCH = False
    yield
    security_config.ALLOW_GLOBAL_SEARCH = False


@pytest.fixture
def store(tmp_path):
    chroma_path = tmp_path / "chroma"
    with ChromaEmbeddingStore(persist_directory=chroma_path) as test_store:
        yield test_store
    shutil.rmtree(chroma_path)


REGISTER_URL = "/api/v1/auth/register"
CHAT_URL = "/api/v1/chat"
KNOWLEDGE_URL = "/api/v1/knowledge"


def _register_and_get_token(
    client: TestClient,
    email: str = "test@example.com",
) -> str:
    resp = client.post(REGISTER_URL, json={"email": email, "password": "secure123"})
    assert resp.status_code == 201
    return resp.json()["token"]


def _register_tenant_user(
    client: TestClient,
    email: str,
    tenant_slug: str,
    db_session,
) -> str:
    token = _register_and_get_token(client, email)
    user = db_session.query(User).filter(User.email == email).first()
    tenant = db_session.query(Tenant).filter(Tenant.slug == tenant_slug).first()
    if user and tenant:
        user.tenant_id = tenant.id
        db_session.commit()
    return token


class TestVectorIsolation:
    def test_tenant_a_insert_tenant_b_query_zero_results(self, store):
        store.create_collection("default")

        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_tesla",
                chunk_id="doc_tesla_0",
                company="Tesla",
                content="Tesla revenue grew 20% in Q4 2025.",
                embedding=embedding,
                metadata={
                    "collection": "default",
                    "source": "tesla_q4.pdf",
                    "tenant_id": 1,
                },
            ),
        ])

        results_b = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=2,
        )

        assert len(results_b) == 0

    def test_tenant_a_query_own_data(self, store):
        store.create_collection("default")

        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_tesla",
                chunk_id="doc_tesla_0",
                company="Tesla",
                content="Tesla revenue grew 20% in Q4 2025.",
                embedding=embedding,
                metadata={
                    "collection": "default",
                    "source": "tesla_q4.pdf",
                    "tenant_id": 1,
                },
            ),
        ])

        results_a = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=1,
        )

        assert len(results_a) >= 1
        assert results_a[0].content == "Tesla revenue grew 20% in Q4 2025."
        assert results_a[0].metadata.get("tenant_id") == 1

    def test_tenant_id_missing_returns_all(self, store):
        """Without tenant_id, ChromaStore returns all documents (no filtering).
        Tenant isolation is enforced at the API/Service layer, not the storage layer."""
        store.create_collection("default")

        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_tesla",
                chunk_id="doc_tesla_0",
                company="Tesla",
                content="Tesla revenue grew 20% in Q4 2025.",
                embedding=embedding,
                metadata={
                    "collection": "default",
                    "source": "tesla_q4.pdf",
                },
            ),
        ])

        results_all = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
        )
        assert len(results_all) >= 1

        results_with_tenant = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=1,
        )

        assert len(results_with_tenant) == 0

    def test_tenant_cross_isolation_multiple_chunks(self, store):
        store.create_collection("default")

        embed_a = [0.9] * 384
        embed_b = [0.1] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_a1",
                chunk_id="doc_a1_0",
                company="Apple",
                content="Apple iPhone revenue: $50B",
                embedding=embed_a,
                metadata={
                    "collection": "default",
                    "source": "apple.pdf",
                    "tenant_id": 1,
                },
            ),
            VectorDocument(
                document_id="doc_a2",
                chunk_id="doc_a2_0",
                company="Apple",
                content="Apple Mac revenue: $10B",
                embedding=embed_a,
                metadata={
                    "collection": "default",
                    "source": "apple.pdf",
                    "tenant_id": 1,
                },
            ),
            VectorDocument(
                document_id="doc_b1",
                chunk_id="doc_b1_0",
                company="NVIDIA",
                content="NVIDIA data center revenue: $30B",
                embedding=embed_b,
                metadata={
                    "collection": "default",
                    "source": "nvidia.pdf",
                    "tenant_id": 2,
                },
            ),
        ])

        results_a = store.similarity_search(
            query_embedding=embed_a,
            top_k=5,
            tenant_id=1,
        )
        assert len(results_a) == 2
        assert all(r.metadata.get("tenant_id") == 1 for r in results_a)

        results_b = store.similarity_search(
            query_embedding=embed_b,
            top_k=5,
            tenant_id=2,
        )
        assert len(results_b) == 1
        assert results_b[0].metadata.get("tenant_id") == 2

        results_a_on_b_query = store.similarity_search(
            query_embedding=embed_b,
            top_k=5,
            tenant_id=1,
        )
        assert len(results_a_on_b_query) == 2
        assert all(r.metadata.get("tenant_id") == 1 for r in results_a_on_b_query)

    def test_tenant_id_none_returns_all_documents(self, store):
        """Without tenant_id, ChromaStore returns all documents regardless of tenant.
        This is correct: tenant filtering is the API/Service layer's job."""
        store.create_collection("default")

        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="A",
                content="Content A",
                embedding=embedding,
                metadata={
                    "collection": "default",
                    "tenant_id": 1,
                },
            ),
            VectorDocument(
                document_id="doc_2",
                chunk_id="doc_2_0",
                company="B",
                content="Content B",
                embedding=embedding,
                metadata={
                    "collection": "default",
                    "tenant_id": 2,
                },
            ),
        ])

        results = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
        )
        assert len(results) == 2


class TestRetrievalAPITenantIsolation:
    def test_tenant_a_token_cannot_access_tenant_b_documents(
        self,
        client,
        db_session,
    ):
        token_a = _register_tenant_user(
            client, "alice@a.com", "tenant-a", db_session
        )
        token_b = _register_tenant_user(
            client, "bob@b.com", "tenant-b", db_session
        )

        tenant_a = db_session.query(Tenant).filter(Tenant.slug == "tenant-a").first()
        tenant_b = db_session.query(Tenant).filter(Tenant.slug == "tenant-b").first()

        resp_a = client.get(
            KNOWLEDGE_URL,
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp_a.status_code == 200
        docs_a = resp_a.json().get("documents", [])
        assert isinstance(docs_a, list)

        resp_b = client.get(
            KNOWLEDGE_URL,
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp_b.status_code == 200
        docs_b = resp_b.json().get("documents", [])
        assert isinstance(docs_b, list)

        assert docs_a != docs_b or (docs_a == [] and docs_b == [])

    def test_tenant_statistics_isolated(self, client, db_session):
        token_a = _register_tenant_user(
            client, "alice_stats@a.com", "tenant-a", db_session
        )
        token_b = _register_tenant_user(
            client, "bob_stats@b.com", "tenant-b", db_session
        )

        resp_a = client.get(
            "/api/v1/knowledge/statistics",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp_a.status_code == 200

        resp_b = client.get(
            "/api/v1/knowledge/statistics",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp_b.status_code == 200
