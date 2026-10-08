from typing import Dict, List, Optional


class DocumentFilter:
    """
    Builds document filter conditions from RetrievalContext.

    Used by HybridRetriever._apply_filters() for post-filtering.
    """

    def build(
        self,
        document_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        return {
            "document_ids": document_ids or [],
        }
