import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


from storage.embedding_store import EmbeddingStore
from storage.vector_models import SearchResult, VectorDocument


class MockEmbeddingStore(EmbeddingStore):
    def __init__(self):
        self._collections = {}
        self._documents = []

    def create_collection(self, collection_name: str) -> None:
        self._collections[collection_name] = []

    def delete_collection(self, collection_name: str) -> None:
        self._collections.pop(collection_name, None)

    def list_collections(self):
        return list(self._collections.keys())

    def add_documents(self, documents):
        self._documents.extend(documents)
        for doc in documents:
            col = doc.metadata.get("collection", "default")
            if col not in self._collections:
                self._collections[col] = []
            self._collections[col].append(doc)

    def similarity_search(self, query_embedding, top_k=5, tenant_id=None):
        documents = self._documents
        if tenant_id is not None:
            documents = [
                document
                for document in documents
                if document.metadata.get("tenant_id") == tenant_id
            ]
        return [
            SearchResult(
                document_id=doc.document_id,
                chunk_id=doc.chunk_id,
                score=0.95 - i * 0.05,
                content=doc.content,
                metadata=doc.metadata,
            )
            for i, doc in enumerate(documents[:top_k])
        ]

    def delete_document(
        self,
        document_id: str,
        *,
        tenant_id: int,
    ) -> None:
        self._documents = [
            document
            for document in self._documents
            if not (
                document.document_id == document_id
                and document.metadata.get("tenant_id") == tenant_id
            )
        ]

    def delete_by_tenant(self, tenant_id: int) -> None:
        self._documents = [
            document
            for document in self._documents
            if document.metadata.get("tenant_id") != tenant_id
        ]

    def count(self):
        return len(self._documents)


class TestEmbeddingStoreInterface:
    def test_create_collection(self):
        store = MockEmbeddingStore()
        store.create_collection("test_collection")
        assert "test_collection" in store.list_collections()

    def test_delete_collection(self):
        store = MockEmbeddingStore()
        store.create_collection("test_collection")
        store.delete_collection("test_collection")
        assert "test_collection" not in store.list_collections()

    def test_list_collections(self):
        store = MockEmbeddingStore()
        store.create_collection("a")
        store.create_collection("b")
        cols = store.list_collections()
        assert "a" in cols
        assert "b" in cols

    def test_count_empty(self):
        store = MockEmbeddingStore()
        assert store.count() == 0

    def test_count_after_add(self):
        store = MockEmbeddingStore()
        store.create_collection("default")
        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="Apple",
                content="Revenue grew 10%.",
                embedding=[0.1, 0.2, 0.3],
            )
        ])
        assert store.count() == 1

    def test_add_documents(self):
        store = MockEmbeddingStore()
        store.create_collection("default")
        doc = VectorDocument(
            document_id="doc_1",
            chunk_id="doc_1_0",
            company="Apple",
            content="Revenue grew 10%.",
            embedding=[0.1, 0.2, 0.3],
            metadata={"collection": "default"},
        )
        store.add_documents([doc])
        assert store.count() == 1

    def test_similarity_search(self):
        store = MockEmbeddingStore()
        store.create_collection("default")
        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="Apple",
                content="Revenue grew 10%.",
                embedding=[0.1, 0.2, 0.3],
            ),
            VectorDocument(
                document_id="doc_2",
                chunk_id="doc_2_0",
                company="NVIDIA",
                content="Data center revenue up 50%.",
                embedding=[0.4, 0.5, 0.6],
            ),
        ])
        results = store.similarity_search([0.1, 0.2, 0.3], top_k=5)
        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
        assert results[0].document_id == "doc_1"

    def test_delete_document(self):
        store = MockEmbeddingStore()
        store.create_collection("default")
        store.add_documents([
            VectorDocument(
                document_id="doc_1",
                chunk_id="doc_1_0",
                company="Apple",
                content="Revenue grew 10%.",
                embedding=[0.1, 0.2, 0.3],
                metadata={"tenant_id": 1},
            ),
        ])
        assert store.count() == 1
        store.delete_document("doc_1", tenant_id=1)
        assert store.count() == 0

    def test_delete_by_tenant(self):
        store = MockEmbeddingStore()
        store.add_documents(
            [
                VectorDocument(
                    document_id=f"doc_{tenant_id}",
                    chunk_id=f"doc_{tenant_id}_0",
                    company="Test",
                    content=f"Tenant {tenant_id}",
                    embedding=[0.1, 0.2, 0.3],
                    metadata={"tenant_id": tenant_id},
                )
                for tenant_id in (1, 2)
            ]
        )

        store.delete_by_tenant(1)

        assert [document.document_id for document in store._documents] == ["doc_2"]

    def test_similarity_search_top_k(self):
        store = MockEmbeddingStore()
        store.create_collection("default")
        for i in range(10):
            store.add_documents([
                VectorDocument(
                    document_id=f"doc_{i}",
                    chunk_id=f"doc_{i}_0",
                    company="Test",
                    content=f"Content {i}",
                    embedding=[float(i)] * 3,
                )
            ])
        results = store.similarity_search([0.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_similarity_search_empty_store(self):
        store = MockEmbeddingStore()
        results = store.similarity_search([0.0, 0.0, 0.0])
        assert len(results) == 0
