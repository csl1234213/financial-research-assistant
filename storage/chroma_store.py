import gc
import os
from pathlib import Path
from typing import Any, List, Optional

import chromadb

from storage.embedding_store import EmbeddingStore
from storage.exceptions import EmbeddingStoreError
from storage.vector_models import SearchResult, VectorDocument


class ChromaEmbeddingStore(EmbeddingStore):
    """Chroma-backed vector store for local development and Docker deployments.

    ``CHROMA_HOST`` selects Chroma's HTTP service.  When it is absent, the
    store uses a persistent local client so unit tests and local development do
    not require another process.  Explicit constructor arguments make the
    client selection deterministic and straightforward to test.
    """

    def __init__(
        self,
        persist_directory: str | Path | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
        ssl: bool | None = None,
    ):
        try:
            resolved_host = _resolve_host(host)
            if resolved_host:
                self.mode = "http"
                self.client = chromadb.HttpClient(
                    host=resolved_host,
                    port=_resolve_port(port),
                    ssl=_resolve_ssl(ssl),
                )
            else:
                _ensure_local_mode_is_safe()
                self.mode = "persistent"
                path = persist_directory or os.getenv("CHROMA_PATH", "./chroma_db")
                self.client = chromadb.PersistentClient(path=str(path))
        except Exception as e:
            raise EmbeddingStoreError(f"Failed to init Chroma: {e}")

    def close(self) -> None:
        """Release client resources, including local SQLite file handles.

        Chroma's persistent client keeps its SQLite/Rust resources open until
        explicitly closed.  Exposing the lifecycle here lets short-lived
        callers and test fixtures clean up their storage directory reliably,
        especially on Windows.
        """

        client = getattr(self, "client", None)
        if client is None:
            return

        close_client = getattr(client, "close", None)
        try:
            if callable(close_client):
                close_client()
        finally:
            # Chroma 1.5.x can retain its Rust SQLite binding while the closed
            # Python client remains reachable.  Detaching it makes ``close``
            # an actual resource boundary on Windows instead of waiting for
            # interpreter shutdown.
            self.client = None
            del close_client
            del client
            gc.collect()

    def __enter__(self) -> "ChromaEmbeddingStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback
        self.close()

    # =========================
    # Collection
    # =========================

    def create_collection(self, collection_name: str) -> None:
        try:
            self.client.get_or_create_collection(name=collection_name)
        except Exception as e:
            raise EmbeddingStoreError(f"Create collection failed: {e}")

    def delete_collection(self, collection_name: str) -> None:
        try:
            self.client.delete_collection(name=collection_name)
        except Exception as e:
            raise EmbeddingStoreError(f"Delete collection failed: {e}")

    def list_collections(self) -> List[str]:
        try:
            return [c.name for c in self.client.list_collections()]
        except Exception as e:
            raise EmbeddingStoreError(f"List collections failed: {e}")

    # =========================
    # Documents
    # =========================

    def add_documents(self, documents: List[VectorDocument]) -> None:
        try:
            documents_by_collection: dict[str, list[VectorDocument]] = {}
            for document in documents:
                collection_name = str(
                    document.metadata.get("collection", "default")
                )
                documents_by_collection.setdefault(
                    collection_name,
                    [],
                ).append(document)

            for collection_name, collection_documents in documents_by_collection.items():
                collection = self.client.get_or_create_collection(
                    name=collection_name
                )
                # Deterministic chunk IDs make worker retries safe. ``upsert``
                # replaces a partially written prior attempt instead of
                # failing on duplicate IDs.
                collection.upsert(
                    ids=[
                        document.chunk_id
                        for document in collection_documents
                    ],
                    documents=[
                        document.content
                        for document in collection_documents
                    ],
                    embeddings=[
                        document.embedding
                        for document in collection_documents
                    ],
                    metadatas=[
                        {
                            "document_id": document.document_id,
                            "company": document.company,
                            **document.metadata,
                        }
                        for document in collection_documents
                    ],
                )
        except Exception as e:
            raise EmbeddingStoreError(f"Add documents failed: {e}")

    # =========================
    # Query
    # =========================

    def similarity_search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        tenant_id: Optional[int] = None,
    ) -> List[SearchResult]:
        try:
            collections = self.client.list_collections()
            results: List[SearchResult] = []

            for c in collections:
                query_kwargs: dict[str, Any] = {
                    "query_embeddings": [query_embedding],
                    "n_results": top_k,
                }
                if tenant_id is not None:
                    query_kwargs["where"] = {"tenant_id": tenant_id}

                res = c.query(**query_kwargs)

                if not res["ids"][0]:
                    continue

                for i in range(len(res["ids"][0])):
                    metadata = dict(res["metadatas"][0][i])
                    # Chroma returns a distance, not a similarity/confidence.
                    # The retriever uses this explicit marker when exposing a
                    # normalized Evidence confidence.
                    metadata["score_semantics"] = "distance"
                    results.append(
                        SearchResult(
                            document_id=metadata["document_id"],
                            chunk_id=res["ids"][0][i],
                            score=res["distances"][0][i],
                            content=res["documents"][0][i],
                            metadata=metadata,
                        )
                    )

            results.sort(key=lambda x: x.score)
            return results[:top_k]

        except Exception as e:
            raise EmbeddingStoreError(f"Search failed: {e}")

    def lexical_corpus(
        self,
        tenant_id: Optional[int] = None,
    ) -> List[SearchResult]:
        """Load the text corpus visible to one tenant for BM25 retrieval.

        Chroma applies the tenant predicate before returning documents.  This
        keeps the lexical channel on the same isolation boundary as vector
        search; the hybrid orchestrator never builds an unscoped BM25 index.
        """
        try:
            results: List[SearchResult] = []
            for collection in self.client.list_collections():
                get_kwargs: dict[str, Any] = {
                    "include": ["documents", "metadatas"],
                }
                if tenant_id is not None:
                    get_kwargs["where"] = {"tenant_id": tenant_id}

                response = collection.get(**get_kwargs)
                ids = response.get("ids") or []
                documents = response.get("documents") or []
                metadatas = response.get("metadatas") or []

                for index, chunk_id in enumerate(ids):
                    metadata = metadatas[index] or {}
                    content = documents[index] or ""
                    document_id = metadata.get("document_id")
                    if not document_id or not content:
                        continue
                    results.append(
                        SearchResult(
                            document_id=str(document_id),
                            chunk_id=str(chunk_id),
                            score=0.0,
                            content=str(content),
                            metadata=dict(metadata),
                        )
                    )

            return sorted(
                results,
                key=lambda item: (item.document_id, item.chunk_id),
            )
        except Exception as e:
            raise EmbeddingStoreError(f"Lexical corpus load failed: {e}")

    # =========================
    # Utils
    # =========================

    def delete_document(self, document_id: str, *, tenant_id: int) -> None:
        """Delete one tenant's vectors without affecting another tenant.

        ``document_id`` is not assumed to be globally unique.  Requiring the
        trusted tenant scope here makes destructive callers provide both
        identity dimensions explicitly.
        """
        try:
            for c in self.client.list_collections():
                c.delete(
                    where={
                        "$and": [
                            {"tenant_id": {"$eq": tenant_id}},
                            {"document_id": {"$eq": document_id}},
                        ]
                    }
                )
        except Exception as e:
            raise EmbeddingStoreError(f"Delete document failed: {e}")

    def delete_by_tenant(self, tenant_id: int) -> None:
        """Delete only one tenant's chunks across collections.

        Demo refreshes use this instead of deleting every collection, which
        would otherwise remove private tenant knowledge bases.
        """
        try:
            for collection in self.client.list_collections():
                collection.delete(where={"tenant_id": tenant_id})
        except Exception as e:
            raise EmbeddingStoreError(f"Delete tenant documents failed: {e}")

    def count(self) -> int:
        try:
            total = 0
            for c in self.client.list_collections():
                total += c.count()
            return total
        except Exception as e:
            raise EmbeddingStoreError(f"Count failed: {e}")


def _resolve_host(explicit_host: str | None) -> str:
    if explicit_host is not None:
        return explicit_host.strip()
    return os.getenv("CHROMA_HOST", "").strip()


def _resolve_port(explicit_port: int | None) -> int:
    if explicit_port is not None:
        return explicit_port

    raw_port = os.getenv("CHROMA_PORT", "8000").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("CHROMA_PORT must be an integer") from exc

    if not 1 <= port <= 65535:
        raise ValueError("CHROMA_PORT must be between 1 and 65535")
    return port


def _resolve_ssl(explicit_ssl: bool | None) -> bool:
    if explicit_ssl is not None:
        return explicit_ssl
    return os.getenv("CHROMA_SSL", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _ensure_local_mode_is_safe() -> None:
    app_env = os.getenv("APP_ENV", "").strip().lower()
    if app_env in {"production", "prod"}:
        raise EmbeddingStoreError(
            "CHROMA_HOST must be set in production; "
            "PersistentClient is not supported in production mode"
        )
