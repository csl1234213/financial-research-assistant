from typing import Any, Dict, List

from retrieval.hybrid_retriever import extract_local_context


def build_context(result, question):
    """
    Legacy: build context from RetrievalResult.
    """
    chunks = result.chunks
    scores = result.scores
    top_k_indices = result.top_k

    context = ""
    citations = []

    max_len = len(chunks)

    for rank, idx in enumerate(top_k_indices):
        if idx >= max_len:
            continue

        score = scores[idx].item() if idx < len(scores) else 0.0

        chunk = chunks[idx]

        local_context = extract_local_context(chunk["text"], question)

        citations.append(
            {
                "rank": rank + 1,
                "source": chunk["source"],
                "chunk_id": chunk["chunk_id"],
                "similarity": round(score, 4),
                "preview": local_context[:150],
            }
        )

        context += f"""
[Evidence {rank + 1}]
Source: {chunk["source"]}
Chunk: {chunk["chunk_id"]}

{local_context}

"""

    return context, citations


def build_context_from_evidence(evidences) -> tuple:
    """
    V3: Build context and citations from Evidence list.

    Agent Runtime calls this after execution.
    Belongs to core/ (presentation layer), not agent/ (orchestration layer).
    """
    context = ""
    citations: List[Dict[str, Any]] = []

    for i, ev in enumerate(evidences):
        citation = {
            "rank": i + 1,
            "source": ev.source,
            "chunk_id": ev.metadata.get("chunk_id", ""),
            "similarity": ev.confidence,
            "preview": ev.content[:150],
        }
        for field in (
            "page",
            "section",
            "ocr_used",
            "parser_version",
            "chunker_version",
            "table_context",
            "source_locator",
            "page_label",
            "content_type",
            "source_format",
            "source_authority",
            "embedding_model",
            "embedding_revision",
            "content_sha256",
            "semantic_support",
            "semantic_support_reason",
            "claim_support",
            "claim_support_reason",
            "structured_financial_fact",
            "fact_id",
            "document_id",
            "document_version",
            "canonical_metric",
            "original_label",
            "normalized_label",
            "value",
            "currency",
            "unit",
            "fiscal_year",
            "fiscal_quarter",
            "period_type",
            "period_start",
            "period_end",
            "scope",
            "statement_type",
            "mapping_status",
            "mapping_rule",
            "row_verification_status",
            "tenant_id",
        ):
            value = ev.metadata.get(field)
            if value is not None:
                citation[field] = value
        citations.append(citation)
        location = ev.metadata.get("source_locator") or ev.metadata.get("page_label")
        location_text = f"Location: {location}\n" if location else ""
        context += f"""
[Evidence {i + 1}]
Source: {ev.source}
Chunk: {ev.metadata.get("chunk_id", "")}
{location_text}

{ev.content}

"""

    return context, citations
