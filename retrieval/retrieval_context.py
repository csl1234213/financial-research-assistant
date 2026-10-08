from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RetrievalContext:
    """
    Unified parameter object for all retrieval operations.

    Collapses the growing parameter list (question, chunks, embeddings,
    company, top_k, ...) into a single typed object.

    The Retriever only needs: store + context.

    Future filter examples:
        filters = {"year": "2025", "report": "10-K", "quarter": "Q3"}
    """

    question: str
    company: Optional[str] = None
    document_ids: Optional[List[str]] = None
    top_k: int = 5
    collection: str = "financial_reports"
    filters: Dict[str, str] = field(default_factory=dict)
    # A request must always be scoped to a tenant.  Tenant ``0`` is the
    # intentionally public/demo knowledge base; positive values are private
    # tenant workspaces.
    tenant_id: int = 0
    include_public: bool = False
