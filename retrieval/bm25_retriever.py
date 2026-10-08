"""Deterministic lexical retrieval used by the hybrid RAG pipeline."""

from __future__ import annotations

import re
from collections.abc import Sequence

from rank_bm25 import BM25Okapi

from storage.vector_models import SearchResult

_TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """Retain exact terms and expose adjacent Han pairs without a dictionary.

    Chinese prose has no word spaces. Keeping only whole Unicode runs makes a
    question sentence unable to match even its exact metric label in a table.
    Pairs improve lexical overlap without inventing aliases or financial meaning;
    English, numbers, punctuation boundaries and existing exact terms are kept.
    Single-character expansion is deliberately avoided to limit noisy matches.
    """
    terms = _TOKEN_PATTERN.findall(text.casefold())
    output = []
    for term in terms:
        output.append(term)
        for match in _HAN_RUN.finditer(term):
            run = match.group()
            if len(run) > 2:
                output.extend(run[index:index + 2] for index in range(len(run) - 1))
            elif len(run) == 2 and run != term:
                output.append(run)
    return output


class BM25Retriever:
    """Rank an already tenant-scoped corpus using BM25.

    Corpus acquisition and authorization remain storage/orchestration
    concerns.  This class is deliberately stateless so document refreshes are
    visible immediately and no cross-tenant index can leak through a cache.
    """

    def search(
        self,
        *,
        query: str,
        documents: Sequence[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        if top_k <= 0 or not documents:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        indexed_documents: list[SearchResult] = []
        corpus: list[list[str]] = []
        for document in documents:
            tokens = tokenize(document.content)
            if not tokens:
                continue
            indexed_documents.append(document)
            corpus.append(tokens)

        if not corpus:
            return []

        scores = BM25Okapi(corpus).get_scores(query_tokens)
        query_terms = set(query_tokens)
        ranked = [
            (document, float(score))
            for document, tokens, score in zip(
                indexed_documents,
                corpus,
                scores,
                strict=True,
            )
            # BM25Okapi can assign zero or negative IDF in very small
            # corpora. Token overlap is therefore the relevance gate; the raw
            # score still controls ranking among matching documents.
            if query_terms.intersection(tokens)
        ]
        ranked.sort(
            key=lambda item: (
                -item[1],
                item[0].document_id,
                item[0].chunk_id,
            )
        )

        results: list[SearchResult] = []
        for document, score in ranked[:top_k]:
            metadata = dict(document.metadata)
            metadata["bm25_score"] = score
            metadata["score_semantics"] = "bm25"
            results.append(
                SearchResult(
                    document_id=document.document_id,
                    chunk_id=document.chunk_id,
                    score=score,
                    content=document.content,
                    metadata=metadata,
                )
            )
        return results


# Backward-compatible helpers retained for callers from earlier project
# versions.  New production code uses ``BM25Retriever.search``.
def build_bm25(chunks):
    corpus = [tokenize(chunk["text"]) for chunk in chunks]
    return BM25Okapi(corpus)


def bm25_search(bm25, query, chunks, top_k=5):
    query_tokens = tokenize(query)
    query_terms = set(query_tokens)
    scores = bm25.get_scores(query_tokens)
    ranked = [
        (chunk, float(score))
        for chunk, score in zip(chunks, scores, strict=True)
        if query_terms.intersection(tokenize(chunk["text"]))
    ]
    ranked.sort(
        key=lambda item: (
            -item[1],
            str(item[0].get("document_id", "")),
            str(item[0].get("chunk_id", "")),
        )
    )
    return [item[0] for item in ranked[:top_k]]
