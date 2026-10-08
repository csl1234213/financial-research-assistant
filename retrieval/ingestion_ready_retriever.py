"""Isolated retrieval admission; never scans unready collections."""

import math

from core.answer_synthesis_contracts import EvidenceSnapshot
from retrieval.adaptive_contract import Evidence, RetrievalMode


class IngestionReadyRetriever:
    def __init__(self, ledger, vector_store, *, embedding_identity):
        self.ledger, self.vectors = ledger, vector_store
        self.embedding_identity = embedding_identity

    def search(self, task_id, *, tenant_id, user_id, query_embedding, top_k=5):
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 50:
            raise ValueError("INVALID_QUERY_LIMIT")
        if not query_embedding or any(not math.isfinite(value) for value in query_embedding):
            raise ValueError("INVALID_QUERY_EMBEDDING")
        manifest = self.ledger.ready_index(task_id, tenant_id, user_id)
        if manifest["embedding_identity"] != self.embedding_identity:
            raise ValueError("QUERY_EMBEDDING_VERSION_MISMATCH")
        collection = self.vectors.client.get_collection(manifest["collection"])
        if collection.count() != manifest["verified_chunk_count"]:
            raise ValueError("QUERY_INDEX_COUNT_CHANGED")
        result = collection.query(query_embeddings=[query_embedding],
                                  n_results=min(top_k, manifest["verified_chunk_count"]),
                                  where={"$and": [{"tenant_id": tenant_id},
                                         {"document_id": str(manifest["document_id"])},
                                         {"source_sha256": manifest["source_sha256"]}]},
                                  include=["documents", "metadatas", "distances"])
        output = []
        columns = (result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0])
        if len({len(column) for column in columns}) != 1:
            raise ValueError("QUERY_INDEX_RESULT_SHAPE_CHANGED")
        for identifier, text, metadata, distance in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]):
            if metadata.get("embedding_identity") != self.embedding_identity:
                raise ValueError("QUERY_INDEX_VERSION_CHANGED")
            if (type(metadata.get("tenant_id")) is not int or metadata["tenant_id"] != tenant_id
                    or metadata.get("document_id") != str(manifest["document_id"])
                    or metadata.get("source_sha256") != manifest["source_sha256"]):
                raise ValueError("QUERY_INDEX_SOURCE_BINDING_CHANGED")
            if (not isinstance(identifier, str) or not identifier.strip()
                    or not isinstance(text, str) or not text.strip()
                    or isinstance(distance, bool) or not isinstance(distance, (int, float))
                    or not math.isfinite(distance)):
                raise ValueError("QUERY_INDEX_RESULT_INVALID")
            output.append({"chunk_id": identifier, "text": text, "metadata": metadata, "distance": distance})
        if len({item["chunk_id"] for item in output}) != len(output):
            raise ValueError("QUERY_INDEX_DUPLICATE_IDENTITY")
        # A concurrent quarantine during vector I/O must invalidate this response.
        if self.ledger.ready_index(task_id, tenant_id, user_id) != manifest:
            raise ValueError("QUERY_READINESS_CHANGED")
        return output

    def search_evidence(self, task_id, *, tenant_id, user_id, query_embedding, top_k=5):
        """READY index -> narrative Evidence, without promoting text to facts.

        Missing company/section/period remain unknown. A vector distance is not
        semantic confidence or proof of coverage/entailment.
        """
        manifest = self.ledger.ready_index(task_id, tenant_id, user_id)
        display = self.ledger.ready_document_metadata(task_id, tenant_id, user_id)
        hits = self.search(task_id, tenant_id=tenant_id, user_id=user_id,
                           query_embedding=query_embedding, top_k=top_k)
        if (display["document_id"] != manifest["document_id"]
                or display["source_sha256"] != manifest["source_sha256"]):
            raise ValueError("QUERY_DISPLAY_SOURCE_CHANGED")
        evidence = []
        for hit in hits:
            page = hit["metadata"].get("page")
            if type(page) is not int or page < 1:
                raise ValueError("QUERY_SOURCE_PAGE_REQUIRED")
            item = Evidence(
                evidence_id="indexed-text:" + manifest["source_sha256"] + ":" + hit["chunk_id"],
                evidence_type="NARRATIVE_TEXT", document_id=str(manifest["document_id"]),
                text=hit["text"], retriever=RetrievalMode.HYBRID,
                source_kind="ready_indexed_text", source=display["filename"], page=page,
                company=hit["metadata"].get("report_company", ""),
                section=hit["metadata"].get("section"),
                source_locator={"page": page, "locator": hit["metadata"].get("source_locator")
                                or "chunk:" + hit["chunk_id"]},
                provenance={"tenant_id": tenant_id, "content_sha256": manifest["source_sha256"],
                            "document_version": manifest["source_sha256"],
                            "embedding_identity": self.embedding_identity,
                            "retrieval_component": "vector_only",
                            **{key: hit["metadata"][key] for key in ("section", "content_type", "source_format",
                               "parser_version", "chunker_version", "report_company", "report_period")
                               if key in hit["metadata"]},
                            "structured_financial_fact": False, "distance": hit["distance"]},
                citation={"page": page},
            )
            evidence.append(EvidenceSnapshot.from_evidence(item, tenant_id=tenant_id))
        if self.ledger.ready_index(task_id, tenant_id, user_id) != manifest:
            raise ValueError("QUERY_READINESS_CHANGED")
        return tuple(evidence)
