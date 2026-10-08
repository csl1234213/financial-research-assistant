from typing import Any, Dict, Optional


class MetadataFilter:
    """
    Builds metadata filter conditions from RetrievalContext.

    Used by HybridRetriever._apply_filters() for post-filtering.
    """

    def build(
        self,
        company: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return {
            "company": company,
            "filters": filters or {},
        }
