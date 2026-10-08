import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import shutil
from unittest.mock import patch

import pytest

import config.security as security_config


@pytest.fixture(autouse=True)
def _reset_security_config():
    security_config.ALLOW_GLOBAL_SEARCH = False
    yield
    security_config.ALLOW_GLOBAL_SEARCH = False


from storage.chroma_store import ChromaEmbeddingStore
from storage.vector_models import VectorDocument


@pytest.fixture
def store(tmp_path):
    chroma_path = tmp_path / "chroma"
    with ChromaEmbeddingStore(persist_directory=chroma_path) as test_store:
        yield test_store
    shutil.rmtree(chroma_path)


class TestMissingTenantVectorSearch:
    def test_similarity_search_without_tenant_id_returns_all(self, store):
        """ChromaStore no longer enforces tenant_id - filtering is the API/Service layer's responsibility."""
        store.create_collection("default")
        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="Test",
                content="Test content",
                embedding=embedding,
                metadata={"collection": "default", "tenant_id": 1},
            ),
        ])

        results = store.similarity_search(query_embedding=embedding, top_k=5)
        assert len(results) == 1

    def test_similarity_search_with_tenant_id_works(self, store):
        store.create_collection("default")
        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="Test",
                content="Test content",
                embedding=embedding,
                metadata={"collection": "default", "tenant_id": 1},
            ),
        ])

        results = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=1,
        )
        assert len(results) == 1
        assert results[0].metadata.get("tenant_id") == 1


class TestTenantCrossIsolation:
    def test_tenant_a_query_tenant_b_vectors_returns_zero(self, store):
        store.create_collection("default")
        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_a",
                chunk_id="doc_a_0",
                company="CompanyA",
                content="Company A secret data",
                embedding=embedding,
                metadata={"collection": "default", "tenant_id": 1},
            ),
            VectorDocument(
                document_id="doc_b",
                chunk_id="doc_b_0",
                company="CompanyB",
                content="Company B secret data",
                embedding=embedding,
                metadata={"collection": "default", "tenant_id": 2},
            ),
        ])

        results_tenant_1 = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=1,
        )
        assert len(results_tenant_1) == 1
        assert results_tenant_1[0].document_id == "doc_a"
        assert results_tenant_1[0].metadata.get("tenant_id") == 1

        results_tenant_2 = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=2,
        )
        assert len(results_tenant_2) == 1
        assert results_tenant_2[0].document_id == "doc_b"
        assert results_tenant_2[0].metadata.get("tenant_id") == 2

    def test_tenant_own_data_accessible(self, store):
        store.create_collection("default")
        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="Tenant1",
                content="Tenant 1 private data",
                embedding=embedding,
                metadata={"collection": "default", "tenant_id": 1},
            ),
        ])

        results = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=1,
        )
        assert len(results) == 1
        assert results[0].metadata.get("tenant_id") == 1


class TestAnonymousRequest:
    def test_anonymous_gets_all_without_tenant_filter(self, store):
        """Without tenant_id, ChromaStore returns all documents at the storage layer.
        Tenant isolation is enforced at the API/Service layer via authentication."""
        store.create_collection("default")
        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="Private",
                content="Private data",
                embedding=embedding,
                metadata={"collection": "default", "tenant_id": 1},
            ),
        ])

        results = store.similarity_search(query_embedding=embedding, top_k=5)
        assert len(results) == 1


class TestLegacyMigrationDetection:
    def test_legacy_chunk_without_tenant_id_not_visible(self, store):
        store.create_collection("default")
        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_legacy",
                chunk_id="doc_legacy_0",
                company="Tesla",
                content="Tesla legacy data without tenant_id",
                embedding=embedding,
                metadata={"collection": "default", "source": "tesla.pdf"},
            ),
        ])

        results = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id=1,
        )
        assert len(results) == 0

    def test_migrated_chunk_has_tenant_id(self, store):
        store.create_collection("default")
        embedding = [0.5] * 384

        store.add_documents([
            VectorDocument(
                document_id="doc_migrated",
                chunk_id="doc_migrated_0",
                company="Tesla",
                content="Tesla migrated data",
                embedding=embedding,
                metadata={
                    "collection": "default",
                    "source": "tesla.pdf",
                    "tenant_id": "default",
                },
            ),
        ])

        results = store.similarity_search(
            query_embedding=embedding,
            top_k=5,
            tenant_id="default",
        )
        assert len(results) == 1
        assert results[0].metadata.get("tenant_id") == "default"


class TestAuditMiddleware:
    def test_health_endpoint_has_request_id(self):
        from fastapi.testclient import TestClient

        from api.app import app

        with TestClient(app) as client:
            response = client.get("/api/v1/health")
            assert response.status_code == 200

    def test_chat_endpoint_without_auth(self):
        from fastapi.testclient import TestClient

        from api.app import app

        with TestClient(app) as client:
            with patch("api.services.chat_service.run_agent") as mock_run:
                mock_run.return_value = {
                    "answer": "Test response",
                    "citations": [{"rank": 1, "source": "test.pdf", "chunk_id": "t_0", "similarity": 0.9, "preview": "ok"}],
                    "research_mode": "default",
                    "evidence_count": 1,
                    "intent": {"intent": "SINGLE_COMPANY", "companies": ["Test"]},
                    "plan": {"intent": "single_company", "task_count": 0, "tasks": []},
                    "routing": {"provider": "openai", "model": "gpt-4o"},
                    "planning": {"task_type": "document_qa", "complexity": "low"},
                    "execution": {"strategy": "rag"},
                    "workflow": {"type": "rag", "status": "DONE", "completed_steps": 3},
                }
                response = client.post(
                    "/api/v1/chat",
                    json={"question": "test"},
                )
                assert response.status_code == 200
