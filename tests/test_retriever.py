import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


import pytest

from retrieval.hybrid_retriever import HybridRetriever, extract_keyword, extract_local_context
from retrieval.retrieval_context import RetrievalContext
from storage.vector_models import SearchResult


class FakeModel:
    def encode(
        self,
        text,
        convert_to_tensor=False,
        normalize_embeddings=False,
    ):
        del text, normalize_embeddings
        import numpy as np
        arr = np.array([0.1] * 384)
        if convert_to_tensor:
            import torch
            return torch.tensor(arr)
        return arr


class FakeStore:
    def __init__(self, results=None):
        self.results = results or []
        self.tenant_scopes = []

    def similarity_search(self, query_embedding, top_k=5, tenant_id=None):
        self.tenant_scopes.append(tenant_id)
        return self.results[:top_k]


def _make_result(doc_id, chunk_id, score, content, company="Apple", source="test.pdf"):
    return SearchResult(
        document_id=doc_id,
        chunk_id=chunk_id,
        score=score,
        content=content,
        metadata={"company": company, "source": source},
    )


class TestHybridRetriever:
    @pytest.fixture
    def retriever(self):
        return HybridRetriever(model=FakeModel())

    def test_retrieve_basic(self, retriever):
        store = FakeStore(results=[
            _make_result("doc_1", "doc_1_0", 0.95, "Revenue grew 10%."),
            _make_result("doc_2", "doc_2_0", 0.80, "Data center revenue up 50%.", company="NVIDIA"),
        ])
        ctx = RetrievalContext(question="What is revenue?")
        results = retriever.retrieve(ctx, store)
        assert len(results) == 2
        assert results[0].document_id == "doc_1"
        assert store.tenant_scopes == [0]

    def test_retrieve_forwards_tenant_scope(self, retriever):
        store = FakeStore(
            results=[
                _make_result("doc_1", "doc_1_0", 0.95, "Tenant evidence."),
            ]
        )
        ctx = RetrievalContext(question="Revenue", tenant_id=42)

        retriever.retrieve(ctx, store)

        assert store.tenant_scopes == [42]

    def test_retrieve_company_filter(self, retriever):
        store = FakeStore(results=[
            _make_result("doc_1", "doc_1_0", 0.95, "Apple revenue.", company="Apple"),
            _make_result("doc_2", "doc_2_0", 0.80, "NVIDIA revenue.", company="NVIDIA"),
        ])
        ctx = RetrievalContext(question="Revenue", company="Apple")
        results = retriever.retrieve(ctx, store)
        assert len(results) == 1
        assert results[0].document_id == "doc_1"

    def test_retrieve_document_ids_filter(self, retriever):
        store = FakeStore(results=[
            _make_result("doc_1", "doc_1_0", 0.95, "Content A."),
            _make_result("doc_2", "doc_2_0", 0.80, "Content B."),
        ])
        ctx = RetrievalContext(question="Test", document_ids=["doc_1"])
        results = retriever.retrieve(ctx, store)
        assert len(results) == 1
        assert results[0].document_id == "doc_1"

    def test_retrieve_top_k(self, retriever):
        store = FakeStore(results=[
            _make_result("doc_1", "doc_1_0", 0.95, "Content 1"),
            _make_result("doc_2", "doc_2_0", 0.90, "Content 2"),
            _make_result("doc_3", "doc_3_0", 0.85, "Content 3"),
            _make_result("doc_4", "doc_4_0", 0.80, "Content 4"),
        ])
        ctx = RetrievalContext(question="Test", top_k=2)
        results = retriever.retrieve(ctx, store)
        assert len(results) == 2

    def test_retrieve_metadata_filter(self, retriever):
        store = FakeStore(results=[
            _make_result("doc_1", "doc_1_0", 0.95, "Content A.", company="Apple"),
            _make_result("doc_2", "doc_2_0", 0.80, "Content B.", company="Apple"),
        ])
        ctx = RetrievalContext(
            question="Test",
            company="Apple",
            filters={"year": "2025"},
        )
        results = retriever.retrieve(ctx, store)
        assert len(results) == 0

    def test_retrieve_evidence(self, retriever):
        store = FakeStore(results=[
            _make_result("doc_1", "doc_1_0", 0.95, "Revenue grew 10% year over year. Profit increased significantly."),
        ])
        ctx = RetrievalContext(question="What is revenue?")
        evidences = retriever.retrieve_evidence(ctx, store)
        assert len(evidences) == 1
        assert evidences[0].source == "test.pdf"
        assert evidences[0].company == "Apple"
        assert evidences[0].confidence == 0.95

    def test_retrieve_empty_store(self, retriever):
        store = FakeStore(results=[])
        ctx = RetrievalContext(question="Test")
        results = retriever.retrieve(ctx, store)
        assert len(results) == 0


class TestExtractKeyword:
    def test_simple(self):
        assert extract_keyword("What is the revenue of Apple") == "revenue"

    def test_short_words(self):
        assert extract_keyword("AI is the future") == "future"

    def test_single_word(self):
        assert extract_keyword("Revenue") == "revenue"


class TestExtractLocalContext:
    def test_finds_keyword(self):
        chunk = "The revenue grew 10%. Profit increased. Margins expanded."
        result = extract_local_context(chunk, "revenue")
        assert "revenue" in result.lower()

    def test_no_match_returns_full(self):
        chunk = "The company performed well."
        result = extract_local_context(chunk, "xyzabc")
        assert result == chunk
