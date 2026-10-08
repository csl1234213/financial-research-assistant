"""Lossless adapters around existing retrievers, with explicit source isolation."""

from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Any, Callable

from retrieval.adaptive_contract import Evidence, RetrievalMode, RetrievalRequest, RetrievalResult, RetrievalStatus
from retrieval.retrieval_context import RetrievalContext


def evidence_from_source(
    *,
    request: RetrievalRequest,
    metadata: dict,
    text: str,
    source: str,
    document_id: str,
    evidence_id: str,
    route: RetrievalMode,
    confidence: float | None,
) -> Evidence:
    scoped = request.scoped
    tenant = metadata.get("tenant_id")
    allowed = {scoped.tenant_id, 0} if scoped.include_public else {scoped.tenant_id}
    if isinstance(tenant, bool) or not isinstance(tenant, int) or tenant not in allowed:
        raise ValueError("evidence tenant scope missing or mismatched")
    if scoped.document_ids and document_id not in scoped.document_ids:
        raise ValueError("evidence document outside requested scope")
    if not text.strip() or not source or not document_id or not evidence_id:
        raise ValueError("evidence requires source identity and text")
    data = deepcopy(metadata)
    data["document_id"] = document_id
    data.setdefault("chunk_id", evidence_id)
    structured = route == RetrievalMode.FACT
    if structured:
        if request.metric and data.get("canonical_metric") != request.metric:
            raise ValueError("fact metric mismatch")
        if request.fiscal_year and str(data.get("fiscal_year")) != str(request.fiscal_year):
            raise ValueError("fact fiscal year mismatch")
        if request.scope and data.get("scope") != request.scope:
            raise ValueError("fact financial scope mismatch")
        if request.period in {"INSTANT", "DURATION"} and data.get("period_type") != request.period:
            raise ValueError("fact period type mismatch")
    evidence_type = "STRUCTURED_FINANCIAL_FACT" if structured else "VECTOR_TEXT"
    if not structured and data.get("retrieval_strategy") == "hybrid_rrf":
        evidence_type = "LEXICAL_TEXT" if data.get("vector_rank") is None else "VECTOR_TEXT"
    return Evidence(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        document_id=document_id,
        text=text,
        retriever=route,
        source_kind=data.get("source_authority", "unknown"),
        source=source,
        company=data.get("company", scoped.company or ""),
        page=data.get("page"),
        bbox=deepcopy(data.get("bbox")),
        source_locator=deepcopy(data.get("source_locator")),
        source_block_ids=tuple(data.get("source_block_ids", ())),
        structured_value=data.get("value"),
        metric=data.get("canonical_metric"),
        scope=data.get("scope"),
        statement=data.get("statement_type"),
        period={
            key: data[key]
            for key in ("fiscal_year", "fiscal_quarter", "period_type", "period_start", "period_end")
            if key in data
        },
        confidence=confidence,
        provenance=data,
        citation={
            key: deepcopy(data[key]) for key in ("document_id", "chunk_id", "page", "source_locator") if key in data
        },
    )


class HybridEvidenceAdapter:
    def __init__(self, retriever: Any, store: Any):
        self.retriever, self.store = retriever, store

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        start = perf_counter()
        scoped = request.scoped
        rows = self.retriever.retrieve(
            RetrievalContext(
                question=scoped.query,
                company=scoped.company,
                document_ids=list(scoped.document_ids) or None,
                top_k=scoped.top_k,
                filters=dict(scoped.filters),
                tenant_id=scoped.tenant_id,
                include_public=scoped.include_public,
            ),
            self.store,
        )
        evidence = tuple(
            evidence_from_source(
                request=request,
                metadata=row.metadata,
                text=row.content,
                source=row.metadata.get("source", ""),
                document_id=row.document_id,
                evidence_id=row.chunk_id,
                route=RetrievalMode.HYBRID,
                confidence=self.retriever._evidence_confidence(row),
            )
            for row in rows
        )
        return RetrievalResult(
            status=RetrievalStatus.FOUND if evidence else RetrievalStatus.NOT_FOUND,
            route=RetrievalMode.HYBRID,
            evidence=evidence,
            latency_ms=(perf_counter() - start) * 1000,
            cost_metadata={"llm_calls": 0, "estimated_cost": None},
        )


class FinancialFactEvidenceAdapter:
    def __init__(self, lookup: Callable[[RetrievalRequest], Any]):
        self.lookup = lookup

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        start = perf_counter()
        result = self.lookup(request)
        status = str(result.status)
        mapped = RetrievalStatus.UNSUPPORTED if status.startswith("UNSUPPORTED") else RetrievalStatus(status)
        evidence = tuple(
            evidence_from_source(
                request=request,
                metadata={**ev.metadata, "company": ev.company},
                text=ev.content,
                source=ev.source,
                document_id=ev.metadata.get("document_id", ""),
                evidence_id=ev.metadata.get("fact_id", ""),
                route=RetrievalMode.FACT,
                confidence=ev.confidence,
            )
            for ev in result.evidence
        )
        return RetrievalResult(
            status=mapped,
            route=RetrievalMode.FACT,
            evidence=evidence,
            deterministic=True,
            latency_ms=(perf_counter() - start) * 1000,
            trace=deepcopy(result.trace),
            cost_metadata={"llm_calls": 0, "estimated_cost": 0.0},
        )
