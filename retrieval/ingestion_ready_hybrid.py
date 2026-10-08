"""READY-bound store adapter for the existing HybridRetriever, not a new ranker."""

from core.answer_synthesis_contracts import EvidenceSnapshot
from retrieval.adaptive_contract import Evidence, RetrievalMode
from retrieval.ingestion_ready_retriever import IngestionReadyRetriever
from retrieval.retrieval_context import RetrievalContext
from storage.vector_models import SearchResult


class _ReadyCollectionStore:
    def __init__(self, ready, task, tenant, user, manifest, display):
        self.ready, self.task, self.tenant, self.user = ready, task, tenant, user
        self.manifest, self.display = manifest, display

    def check(self, tenant):
        if type(tenant) is not int or tenant != self.tenant:
            raise PermissionError("READY_HYBRID_TENANT_MISMATCH")
        if self.ready.ledger.ready_index(self.task, tenant, self.user) != self.manifest:
            raise ValueError("READY_HYBRID_READINESS_CHANGED")

    def row(self, identifier, text, metadata, score):
        if (type(metadata.get("tenant_id")) is not int or metadata["tenant_id"] != self.tenant
                or metadata.get("document_id") != str(self.manifest["document_id"])
                or metadata.get("source_sha256") != self.manifest["source_sha256"]
                or metadata.get("embedding_identity") != self.ready.embedding_identity
                or not isinstance(identifier, str) or not identifier.strip()
                or not isinstance(text, str) or not text.strip()):
            raise ValueError("READY_HYBRID_SOURCE_CHANGED")
        return SearchResult(str(self.manifest["document_id"]), identifier, score, text,
            {**metadata, "company": metadata.get("report_company", ""),
             "company_semantics": "REPORT_ISSUER_NOT_STATEMENT_SUBJECT",
             "source": self.display["filename"]})

    def similarity_search(self, *, query_embedding, top_k, tenant_id):
        self.check(tenant_id)
        hits = self.ready.search(self.task, tenant_id=tenant_id, user_id=self.user,
                                 query_embedding=query_embedding, top_k=min(top_k, 50))
        return [self.row(hit["chunk_id"], hit["text"],
                         {**hit["metadata"], "score_semantics": "distance"}, hit["distance"])
                for hit in hits]

    def lexical_corpus(self, *, tenant_id):
        self.check(tenant_id)
        collection = self.ready.vectors.client.get_collection(self.manifest["collection"])
        if collection.count() != self.manifest["verified_chunk_count"]:
            raise ValueError("READY_HYBRID_COUNT_CHANGED")
        result = collection.get(where={"$and": [{"tenant_id": tenant_id},
            {"document_id": str(self.manifest["document_id"])},
            {"source_sha256": self.manifest["source_sha256"]}]}, include=["documents", "metadatas"])
        if (len({len(result[key]) for key in ("ids", "documents", "metadatas")}) != 1
                or len(result["ids"]) != self.manifest["verified_chunk_count"]
                or len(set(result["ids"])) != len(result["ids"])):
            raise ValueError("READY_HYBRID_CORPUS_CHANGED")
        rows = [self.row(identifier, text, metadata, 0.0) for identifier, text, metadata
                in zip(result["ids"], result["documents"], result["metadatas"])]
        self.check(tenant_id)
        return rows


class IngestionReadyHybridRetriever:
    retrieval_component = "hybrid_bm25_vector_rrf"

    def __init__(self, ledger, vector_store, *, embedding_identity, hybrid_retriever):
        if (not hybrid_retriever.config.enabled or hybrid_retriever.config.lexical_weight <= 0
                or hybrid_retriever.config.vector_weight <= 0):
            raise ValueError("ENABLED_HYBRID_CHANNELS_REQUIRED")
        self.ledger = ledger
        self.ready = IngestionReadyRetriever(ledger, vector_store, embedding_identity=embedding_identity)
        self.hybrid = hybrid_retriever

    def search_question_evidence(self, task_id, *, tenant_id, user_id, question, top_k=5):
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise ValueError("INVALID_QUERY_LIMIT")
        manifest = self.ledger.ready_index(task_id, tenant_id, user_id)
        if manifest["embedding_identity"] != self.ready.embedding_identity:
            raise ValueError("QUERY_EMBEDDING_VERSION_MISMATCH")
        display = self.ledger.ready_document_metadata(task_id, tenant_id, user_id)
        if (display["document_id"], display["source_sha256"]) != (
                manifest["document_id"], manifest["source_sha256"]):
            raise ValueError("QUERY_DISPLAY_SOURCE_CHANGED")
        store = _ReadyCollectionStore(self.ready, task_id, tenant_id, user_id, manifest, display)
        # Full lexical validation before ranker: its legacy lexical fallback must
        # never swallow a source-integrity failure and return vector-only output.
        store.lexical_corpus(tenant_id=tenant_id)
        rows = self.hybrid.retrieve(RetrievalContext(question=question,
            document_ids=[str(manifest["document_id"])], tenant_id=tenant_id,
            include_public=False, top_k=top_k), store)
        if len({row.chunk_id for row in rows}) != len(rows):
            raise ValueError("READY_HYBRID_DUPLICATE_IDENTITY")
        evidence = []
        for row in rows:
            checked = store.row(row.chunk_id, row.content, row.metadata, row.score)
            page = checked.metadata.get("page")
            if type(page) is not int or page < 1:
                raise ValueError("QUERY_SOURCE_PAGE_REQUIRED")
            evidence.append(EvidenceSnapshot.from_evidence(Evidence(
                "indexed-text:" + manifest["source_sha256"] + ":" + row.chunk_id,
                "NARRATIVE_TEXT", checked.document_id, checked.content, RetrievalMode.HYBRID,
                "ready_indexed_text", display["filename"], company=checked.metadata["company"],
                page=page, section=checked.metadata.get("section"),
                source_locator={"page": page, "locator": checked.metadata.get("source_locator")
                                or "chunk:" + row.chunk_id},
                provenance={**checked.metadata, "content_sha256": manifest["source_sha256"],
                            "document_version": manifest["source_sha256"],
                            "retrieval_component": (self.retrieval_component
                                if checked.metadata.get("retrieval_strategy") == "hybrid_rrf" else "vector_only"),
                            "structured_financial_fact": False}, citation={"page": page}), tenant_id=tenant_id))
        store.check(tenant_id)
        return tuple(evidence)
