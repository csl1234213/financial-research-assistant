"""Shared retrieval diagnostics, separate from production routing policy."""

from dataclasses import dataclass, field
from enum import StrEnum

from retrieval.adaptive_contract import RetrievalMode, RetrievalResult


class RetrievalFailure(StrEnum):
    FACT_NOT_FOUND = "FACT_NOT_FOUND"
    TREE_NODE_MISS = "TREE_NODE_MISS"
    TREE_WRONG_BRANCH = "TREE_WRONG_BRANCH"
    TREE_LOW_QUALITY = "TREE_LOW_QUALITY"
    TREE_SOURCE_BLOCK_MISSING = "TREE_SOURCE_BLOCK_MISSING"
    LEXICAL_MISS = "LEXICAL_MISS"
    VECTOR_SEMANTIC_MISS = "VECTOR_SEMANTIC_MISS"
    RRF_RANKING_MISS = "RRF_RANKING_MISS"
    EVIDENCE_DUPLICATION = "EVIDENCE_DUPLICATION"
    CITATION_MISMATCH = "CITATION_MISMATCH"
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
    AMBIGUOUS_QUERY = "AMBIGUOUS_QUERY"
    COST_EXCESSIVE = "COST_EXCESSIVE"
    LATENCY_EXCESSIVE = "LATENCY_EXCESSIVE"


@dataclass(frozen=True)
class RetrievalTrace:
    query_id: str
    query_class: str | None
    selected_mode: RetrievalMode
    primary_retriever: str
    shadow_retrievers: tuple[str, ...] = ()
    fact_status: str | None = None
    tree_nodes_considered: tuple[str, ...] = ()
    tree_nodes_selected: tuple[str, ...] = ()
    bm25_candidates: int | None = None
    vector_candidates: int | None = None
    final_evidence_count: int = 0
    coverage: float | None = None
    citations: tuple[dict, ...] = ()
    latency_ms: float = 0
    llm_calls: int | None = None
    tokens: dict = field(default_factory=dict)
    cost: float | None = None
    final_status: str = "NOT_FOUND"

    @classmethod
    def from_result(cls, query_id: str, query_class: str | None, result: RetrievalResult):
        return cls(
            query_id,
            query_class,
            result.route,
            str(result.route),
            fact_status=str(result.status) if result.route == RetrievalMode.FACT else None,
            tree_nodes_considered=tuple(result.trace.get("nodes_considered", ())),
            tree_nodes_selected=tuple(result.trace.get("nodes_selected", ())),
            final_evidence_count=len(result.evidence),
            coverage=result.coverage.coverage_ratio,
            citations=tuple(ev.citation for ev in result.evidence),
            latency_ms=result.latency_ms,
            llm_calls=result.cost_metadata.get("llm_calls"),
            tokens={k: result.cost_metadata.get(k) for k in ("input_tokens", "output_tokens")},
            cost=result.cost_metadata.get("estimated_cost"),
            final_status=str(result.status),
        )


ROUTE_HYPOTHESES = {
    "EXACT_FACT": "FACT",
    "EXACT_PHRASE": "BM25",
    "LOCAL_SEMANTIC": "HYBRID",
    "SECTION_LOOKUP": "TREE",
    "EXHAUSTIVE": "TREE",
    "CAUSAL": "FACT+TREE",
    "CROSS_SECTION": "TREE+PLANNER",
    "TREND": "MULTI_FACT",
    "AMBIGUOUS": "FUTURE_NORMALIZATION",
    "MULTI_DOCUMENT": "FUTURE_CROSS_DOCUMENT_PLANNER",
}
