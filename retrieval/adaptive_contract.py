"""Shadow retrieval contracts; production composition remains independent."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from agent.reasoning_models import Evidence as AgentEvidence
from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest


class RetrievalStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


class RetrievalMode(StrEnum):
    FACT = "FACT"
    TREE = "TREE"
    HYBRID = "HYBRID"


@dataclass(frozen=True)
class RetrievalRequest:
    scoped: ScopedRequest
    conversation_context: tuple[str, ...] = ()
    metric: str | None = None
    fiscal_year: str | None = None
    period: str | None = None
    scope: str | None = None
    intent: str | None = None
    query_precision: str | None = None
    query_breadth: str | None = None
    query_class: str | None = None
    preferred_retrievers: tuple[RetrievalMode, ...] = ()
    required_aspects: tuple[str, ...] = ()

    def __post_init__(self):
        if (not isinstance(self.required_aspects, tuple)
                or any(not isinstance(aspect, str) or not aspect.strip() for aspect in self.required_aspects)
                or len(set(self.required_aspects)) != len(self.required_aspects)):
            raise ValueError("required_aspects must contain unique nonempty identities")
        if isinstance(self.scoped.tenant_id, bool) or not isinstance(self.scoped.tenant_id, int):
            raise ValueError("tenant_id must be an integer")
        if self.scoped.tenant_id < 0 or not self.scoped.query.strip():
            raise ValueError("valid tenant and query required")
        if (
            isinstance(self.scoped.top_k, bool)
            or not isinstance(self.scoped.top_k, int)
            or not 1 <= self.scoped.top_k <= 20
        ):
            raise ValueError("max_evidence must be between 1 and 20")


@dataclass(frozen=True)
class CoverageReport:
    required_aspects: tuple[str, ...] = ()
    covered_aspects: tuple[str, ...] = ()
    missing_aspects: tuple[str, ...] = ()
    coverage_ratio: float | None = None
    complete: bool | None = None


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    evidence_type: str
    document_id: str
    text: str
    retriever: RetrievalMode
    source_kind: str
    source: str
    company: str = ""
    page: int | str | None = None
    bbox: Any = None
    source_locator: Any = None
    source_block_ids: tuple[str, ...] = ()
    structured_value: Any = None
    metric: str | None = None
    period: dict[str, Any] = field(default_factory=dict)
    scope: str | None = None
    statement: str | None = None
    confidence: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    citation: dict[str, Any] = field(default_factory=dict)
    section: str | None = None

    def to_agent(self) -> AgentEvidence:
        return AgentEvidence(
            content=self.text,
            source=self.source,
            company=self.company,
            confidence=self.confidence or 0.0,
            metadata=deepcopy(self.provenance),
        )


@dataclass(frozen=True)
class RetrievalResult:
    status: RetrievalStatus
    route: RetrievalMode
    evidence: tuple[Evidence, ...] = ()
    coverage: CoverageReport = field(default_factory=CoverageReport)
    deterministic: bool = False
    latency_ms: float = 0.0
    cost_metadata: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)


class RetrieverProtocol(Protocol):
    def retrieve(self, request: RetrievalRequest) -> RetrievalResult: ...
