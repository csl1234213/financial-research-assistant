from __future__ import annotations

from retrieval.hybrid_retriever import HybridRetriever
from retrieval.retrieval_context import RetrievalContext
from storage.vector_models import SearchResult


class _Embedding(list):
    def tolist(self):
        return list(self)


class _EmbeddingModel:
    def encode(self, _text, *, convert_to_tensor=False, normalize_embeddings=False):
        del convert_to_tensor, normalize_embeddings
        return _Embedding([0.1, 0.2])


class _VectorAndEmptyLexicalStore:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results

    def similarity_search(self, *, query_embedding, top_k, tenant_id):
        del query_embedding, tenant_id
        return self.results[:top_k]

    def lexical_corpus(self, tenant_id=None):
        del tenant_id
        # A non-empty corpus is important: it exercises the branch where BM25
        # runs successfully but has no token-overlap results.
        return [
            SearchResult(
                document_id="other",
                chunk_id="no-lexical-match",
                score=0.0,
                content="unrelated operating outlook",
                metadata={"tenant_id": 7, "company": "Tesla"},
            )
        ]


def _result(chunk_id: str, content_type: str, content: str) -> SearchResult:
    return SearchResult(
        document_id="filing",
        chunk_id=chunk_id,
        score=0.1,
        content=content,
        metadata={
            "tenant_id": 7,
            "company": "Tesla",
            "content_type": content_type,
            "score_semantics": "similarity",
        },
    )


def test_empty_bm25_still_isolates_reranks_and_filters_final_evidence(monkeypatch):
    quarantined = _result(
        "ambiguous-table-row",
        "unverified_table",
        "Revenue 2025 100 2024 90",
    )
    narrative = _result(
        "safe-narrative",
        "narrative",
        "The filing discusses the revenue trend without an unsupported value.",
    )
    verified_table = _result(
        "verified-table-row",
        "table",
        "Financial table row — Metric: Revenue | FY2025: 100 | FY2024: 90",
    )
    retriever = HybridRetriever(_EmbeddingModel())
    rerank_calls: list[list[str]] = []
    original_rerank = retriever.coverage_aware_rerank

    def observe_rerank(results, question, *, top_k, company=None):
        rerank_calls.append([item.chunk_id for item in results])
        return original_rerank(
            results,
            question,
            top_k=top_k,
            company=company,
        )

    monkeypatch.setattr(retriever, "coverage_aware_rerank", observe_rerank)
    results = retriever.retrieve(
        RetrievalContext(
            question="Tesla revenue",
            company="Tesla",
            top_k=3,
            tenant_id=7,
        ),
        _VectorAndEmptyLexicalStore([quarantined, narrative, verified_table]),
    )

    assert rerank_calls, "empty BM25 results must not bypass shared reranking"
    assert "ambiguous-table-row" not in rerank_calls[0]
    assert [item.chunk_id for item in results] == [
        "safe-narrative",
        "verified-table-row",
    ]
    assert all(item.metadata["content_type"] != "unverified_table" for item in results)
    assert all(isinstance(item, SearchResult) for item in results)
