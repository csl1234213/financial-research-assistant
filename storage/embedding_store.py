from abc import ABC, abstractmethod
from typing import List, Optional

from storage.vector_models import (
    SearchResult,
    VectorDocument,
)


class EmbeddingStore(ABC):
    """
    Abstract interface for all vector databases.

    Future implementations:
    - ChromaDB
    - Qdrant
    - Milvus
    - Pinecone
    - PGVector
    """

    @abstractmethod
    def create_collection(self, collection_name: str) -> None:
        pass

    @abstractmethod
    def delete_collection(self, collection_name: str) -> None:
        pass

    @abstractmethod
    def list_collections(self) -> List[str]:
        pass

    @abstractmethod
    def add_documents(self, documents: List[VectorDocument]) -> None:
        pass

    @abstractmethod
    def similarity_search(
        self,
        query_embedding,
        top_k: int = 5,
        tenant_id: Optional[int] = None,
    ) -> List[SearchResult]:
        """Return best-first vector results within the requested tenant.

        Implementations may expose similarity or distance in ``score`` but
        should set ``metadata["score_semantics"]`` accordingly. Callers rely
        on this method's ordering rather than inferring direction from the
        numeric value.
        """
        pass

    def lexical_corpus(
        self,
        tenant_id: Optional[int] = None,
    ) -> List[SearchResult]:
        """Return tenant-scoped text documents for optional lexical retrieval.

        Vector stores that cannot expose a lexical corpus may keep this
        default.  ``HybridRetriever`` treats an empty corpus as an explicit
        signal to preserve the vector-only result instead of failing the
        request.
        """
        return []

    @abstractmethod
    def delete_document(self, document_id: str, *, tenant_id: int) -> None:
        """Delete a document only within the trusted tenant scope."""
        pass

    @abstractmethod
    def delete_by_tenant(self, tenant_id: int) -> None:
        pass

    @abstractmethod
    def count(self) -> int:
        pass
