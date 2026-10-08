from retrieval.hybrid_retriever import HybridRetriever
from retrieval.retrieval_context import RetrievalContext
from storage.vector_models import SearchResult


class _EmbeddingModel:
    def encode(
        self,
        _question,
        convert_to_tensor=False,
        normalize_embeddings=False,
    ):
        del convert_to_tensor, normalize_embeddings
        return _Embedding([0.1, 0.2])


class _Embedding(list):
    def tolist(self):
        return list(self)


class _TenantStore:
    def __init__(self):
        self.calls = []
        self._results = {
            0: [_result("public_1", 0.20, 0)],
            7: [_result("tenant_7_1", 0.10, 7)],
            99: [_result("tenant_99_1", 0.01, 99)],
        }

    def similarity_search(self, *, query_embedding, top_k, tenant_id):
        self.calls.append(tenant_id)
        return self._results.get(tenant_id, [])[:top_k]


def _result(chunk_id, score, tenant_id):
    return SearchResult(
        document_id=chunk_id.rsplit("_", 1)[0],
        chunk_id=chunk_id,
        score=score,
        content="Revenue increased during the quarter.",
        metadata={"tenant_id": tenant_id, "company": "Tesla", "source": "report.pdf"},
    )


def test_authenticated_retrieval_only_queries_own_and_explicit_public_scope():
    store = _TenantStore()
    retriever = HybridRetriever(_EmbeddingModel())

    results = retriever.retrieve(
        RetrievalContext(
            question="Analyze Tesla revenue growth",
            tenant_id=7,
            include_public=True,
        ),
        store,
    )

    assert store.calls == [7, 0]
    assert [result.chunk_id for result in results] == ["tenant_7_1", "public_1"]
    assert all(result.metadata["tenant_id"] != 99 for result in results)


def test_anonymous_retrieval_is_limited_to_the_public_scope():
    store = _TenantStore()
    retriever = HybridRetriever(_EmbeddingModel())

    results = retriever.retrieve(
        RetrievalContext(question="Analyze Tesla revenue growth", tenant_id=0),
        store,
    )

    assert store.calls == [0]
    assert [result.chunk_id for result in results] == ["public_1"]
