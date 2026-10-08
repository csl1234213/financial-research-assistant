from retrieval.adaptive_contract import RetrievalMode, RetrievalResult, RetrievalStatus
from retrieval.adaptive_observability import ROUTE_HYPOTHESES, RetrievalFailure, RetrievalTrace


def test_trace_distinguishes_unknown_cost_and_candidate_counts_from_zero():
    result = RetrievalResult(
        RetrievalStatus.FOUND,
        RetrievalMode.TREE,
        cost_metadata={"llm_calls": 2, "input_tokens": 10, "estimated_cost": 0.1},
        trace={"nodes_considered": ["root"], "nodes_selected": []},
    )
    trace = RetrievalTrace.from_result("q", "EXHAUSTIVE", result)
    assert trace.llm_calls == 2 and trace.cost == 0.1
    assert trace.bm25_candidates is None and trace.vector_candidates is None
    assert trace.tokens["output_tokens"] is None
    assert trace.tree_nodes_considered == ("root",)


def test_fact_hypothesis_does_not_change_primary_result():
    result = RetrievalResult(RetrievalStatus.FOUND, RetrievalMode.FACT, deterministic=True)
    trace = RetrievalTrace.from_result("q", "EXACT_FACT", result)
    assert trace.selected_mode == RetrievalMode.FACT
    assert ROUTE_HYPOTHESES["EXACT_FACT"] == "FACT"
    assert len(ROUTE_HYPOTHESES) == 10
    assert RetrievalFailure.TREE_SOURCE_BLOCK_MISSING == "TREE_SOURCE_BLOCK_MISSING"
