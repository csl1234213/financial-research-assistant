"""Retrieval-only A/B evaluation with explicit reviewed source ground truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from retrieval.adaptive_contract import RetrievalRequest, RetrievalResult, RetrieverProtocol

QUERY_CLASSES = (
    "EXACT_FACT",
    "EXACT_PHRASE",
    "LOCAL_SEMANTIC",
    "SECTION_LOOKUP",
    "EXHAUSTIVE",
    "CAUSAL",
    "CROSS_SECTION",
    "TREND",
    "AMBIGUOUS",
    "MULTI_DOCUMENT",
)


@dataclass(frozen=True)
class ReferenceSpan:
    document_id: str
    block_id: str
    page: int
    text: str
    section: str = ""
    metric: str | None = None
    fiscal_year: str | None = None
    scope: str | None = None


@dataclass(frozen=True)
class BenchmarkCase:
    query_id: str
    request: RetrievalRequest
    expected: tuple[ReferenceSpan, ...]
    gold_reviewed: bool = False
    reference_answer: str | None = None


def measure(result: RetrievalResult, case: BenchmarkCase, sources: Mapping[tuple[str, str], ReferenceSpan]) -> dict:
    """No gold means unavailable metrics; source existence alone does not imply relevance."""
    valid = 0
    valid_evidence = []
    matches = set()
    wrong_metric = wrong_period = wrong_scope = 0
    expected_ids = {(span.document_id, span.block_id) for span in case.expected}
    for ev in result.evidence:
        ids = ev.source_block_ids or (ev.evidence_id,)
        ev_valid = False
        for block_id in ids:
            source = sources.get((ev.document_id, block_id))
            if source and ev.page == source.page and ev.text.strip() and ev.text in source.text:
                ev_valid = True
                if (source.document_id, source.block_id) in expected_ids:
                    matches.add((source.document_id, source.block_id))
                # Different source blocks may faithfully contain the same audited span.
                for expected in case.expected:
                    if expected.document_id == ev.document_id and expected.page == ev.page and expected.text in ev.text:
                        matches.add((expected.document_id, expected.block_id))
                wrong_metric += bool(source.metric and ev.metric and source.metric != ev.metric)
                wrong_period += bool(
                    source.fiscal_year
                    and ev.period.get("fiscal_year")
                    and str(source.fiscal_year) != str(ev.period["fiscal_year"])
                )
                wrong_scope += bool(source.scope and ev.scope and source.scope != ev.scope)
        valid += ev_valid
        if ev_valid:
            valid_evidence.append(ev)
    scored = case.gold_reviewed and bool(case.expected)
    relevant = sum(
        any(
            expected.document_id == ev.document_id and expected.page == ev.page and expected.text in ev.text
            for expected in case.expected
        )
        for ev in valid_evidence
    )
    return {
        "status": str(result.status),
        "found": bool(result.evidence),
        "answer_accuracy": "NOT_EVALUATED",
        "gold_status": "REVIEWED" if case.gold_reviewed else "UNREVIEWED",
        "evidence_recall": len(matches) / len(expected_ids) if scored else None,
        "evidence_precision": relevant / len(result.evidence)
        if scored and result.evidence
        else (0 if scored else None),
        "citation_accuracy": valid / len(result.evidence) if result.evidence else None,
        "coverage": len(matches) / len(expected_ids) if scored else None,
        "citation_mismatch_count": len(result.evidence) - valid,
        "wrong_metric_count": wrong_metric,
        "wrong_period_count": wrong_period,
        "wrong_scope_count": wrong_scope,
        "wrong_metric_rate": wrong_metric / len(result.evidence)
        if result.evidence and any(s.metric for s in sources.values())
        else None,
        "wrong_period_rate": wrong_period / len(result.evidence)
        if result.evidence and any(s.fiscal_year for s in sources.values())
        else None,
        "wrong_scope_rate": wrong_scope / len(result.evidence)
        if result.evidence and any(s.scope for s in sources.values())
        else None,
        "hallucinated_evidence_rate": (len(result.evidence) - valid) / len(result.evidence)
        if result.evidence
        else None,
        "latency_ms": result.latency_ms,
        "llm_calls": result.cost_metadata.get("llm_calls"),
        "input_tokens": result.cost_metadata.get("input_tokens"),
        "output_tokens": result.cost_metadata.get("output_tokens"),
        "estimated_cost": result.cost_metadata.get("estimated_cost"),
    }


class FinancialRetrievalBenchmark:
    def __init__(self, sources: tuple[ReferenceSpan, ...]):
        self.sources = {(span.document_id, span.block_id): span for span in sources}
        if len(self.sources) != len(sources):
            raise ValueError("duplicate authoritative source identity")

    def run_case(
        self,
        case: BenchmarkCase,
        hybrid: RetrieverProtocol,
        tree: RetrieverProtocol,
        fact: RetrieverProtocol | None = None,
    ) -> dict:
        if case.request.query_class not in QUERY_CLASSES:
            raise ValueError("unknown benchmark query class")
        if any(self.sources.get((span.document_id, span.block_id)) != span for span in case.expected):
            raise ValueError("ground truth must match authoritative source")
        a = measure(hybrid.retrieve(case.request), case, self.sources)
        b = measure(tree.retrieve(case.request), case, self.sources)
        fact_result = measure(fact.retrieve(case.request), case, self.sources) if fact is not None else None
        winner, reason = "NOT_EVALUATED", "Reviewed evidence gold required"
        if case.gold_reviewed and case.expected:
            # Missing cost prevents a production winner decision. Evidence comparison remains useful.
            def evidence_rank(metrics):
                trustworthy = all(
                    metrics[field] == 0
                    for field in (
                        "citation_mismatch_count",
                        "wrong_metric_count",
                        "wrong_period_count",
                        "wrong_scope_count",
                    )
                )
                return trustworthy, metrics["evidence_recall"], metrics["evidence_precision"]

            rank_a = evidence_rank(a)
            rank_b = evidence_rank(b)
            winner = "TIE" if rank_a == rank_b else ("HYBRID" if rank_a > rank_b else "TREE")
            reason = "Retrieval-only evidence validity, recall, precision; not a production promotion decision"
            if case.request.query_class == "EXACT_FACT" and fact_result is not None:
                if (
                    fact_result["evidence_recall"] == 1
                    and fact_result["citation_mismatch_count"] == 0
                    and evidence_rank(fact_result)[0]
                ):
                    winner = "FACT"
                    reason = "Source-validated exact fact; deterministic route remains preferred"
        return {
            "query_id": case.query_id,
            "query_class": case.request.query_class,
            "hybrid": a,
            "tree": b,
            "fact": fact_result,
            "winner": winner,
            "winner_reason": reason,
            "production_promote": False,
            "adaptive_c": "NOT_IMPLEMENTED",
        }
