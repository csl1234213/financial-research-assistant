"""P2.2 opt-in synthesis contracts; no provider, storage or runtime side effects."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from agent.reasoning_models import Evidence as AgentEvidence
from retrieval.adaptive_contract import CoverageReport, Evidence, RetrievalMode, RetrievalResult


class AnswerType(StrEnum):
    FACT = "FACT"
    COMPARISON = "COMPARISON"
    TREND = "TREND"
    CAUSAL_ANALYSIS = "CAUSAL_ANALYSIS"
    EXPLANATION = "EXPLANATION"
    EXHAUSTIVE_LIST = "EXHAUSTIVE_LIST"
    RISK_ANALYSIS = "RISK_ANALYSIS"
    CROSS_SECTION = "CROSS_SECTION"
    CROSS_DOCUMENT = "CROSS_DOCUMENT"
    AMBIGUOUS = "AMBIGUOUS"


class ClaimType(StrEnum):
    FACT = "FACT"
    INTERPRETATION = "INTERPRETATION"
    COMPARISON = "COMPARISON"
    TREND = "TREND"
    CONTRIBUTING_FACTOR = "CONTRIBUTING_FACTOR"
    UNCERTAINTY = "UNCERTAINTY"


class CausalStrength(StrEnum):
    DIRECTLY_STATED = "DIRECTLY_STATED"
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    PLAUSIBLE_ASSOCIATION = "PLAUSIBLE_ASSOCIATION"
    UNSUPPORTED = "UNSUPPORTED"


class RelationType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRASTS = "CONTRASTS"
    CAUSE_CANDIDATE = "CAUSE_CANDIDATE"
    CONTRIBUTING_FACTOR = "CONTRIBUTING_FACTOR"
    TREND_COMPONENT = "TREND_COMPONENT"
    EXPLAINS = "EXPLAINS"


class VerificationFailure(StrEnum):
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    UNSUPPORTED_NUMBER = "UNSUPPORTED_NUMBER"
    NUMERIC_MUTATION = "NUMERIC_MUTATION"
    PERIOD_MISMATCH = "PERIOD_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    METRIC_MISMATCH = "METRIC_MISMATCH"
    CITATION_MISSING = "CITATION_MISSING"
    CITATION_WRONG_SOURCE = "CITATION_WRONG_SOURCE"
    OVERCLAIMED_CAUSALITY = "OVERCLAIMED_CAUSALITY"
    EVIDENCE_NOT_USED = "EVIDENCE_NOT_USED"


def _freeze(value: Any) -> Any:
    """Detach metadata recursively, rather than relying on shallow frozen dataclasses."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool, Decimal)):
        return value
    raise ValueError(f"unsupported evidence metadata type: {type(value).__name__}")


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Lossless immutable snapshot of the existing unified evidence fields."""

    evidence_id: str
    document_id: str
    payload: Mapping[str, Any]

    @classmethod
    def from_evidence(cls, evidence: Evidence, *, tenant_id: int) -> EvidenceSnapshot:
        owner = evidence.provenance.get("tenant_id")
        if type(owner) is not int or owner != tenant_id:
            raise ValueError("evidence tenant mismatch or missing tenant")
        if not evidence.evidence_id or not evidence.document_id:
            raise ValueError("stable evidence/document identity required")
        payload = {name: getattr(evidence, name) for name in evidence.__dataclass_fields__}
        return cls(evidence.evidence_id, evidence.document_id, _freeze(payload))


@dataclass(frozen=True)
class SynthesisInput:
    query: str
    tenant_id: int
    answer_type: AnswerType
    locale: str
    evidence: tuple[EvidenceSnapshot, ...]
    retrieval_status: str
    retrieval_route: str
    coverage: Mapping[str, Any]
    schema_version: str = "p2.2.v1"
    required_dimensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "coverage", _freeze(self.coverage))
        object.__setattr__(self, "required_dimensions", _freeze(self.required_dimensions))
        if type(self.tenant_id) is not int or self.tenant_id < 0 or not self.query.strip():
            raise ValueError("valid query and tenant required")
        if not isinstance(self.answer_type, AnswerType) or self.locale not in {"zh-CN", "zh-TW", "en"}:
            raise ValueError("explicit answer type and supported UI locale required")
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate evidence identity")
        allowed = {"company", "metric", "scope", "currency", "unit", "statement", "period"}
        if set(self.required_dimensions) - allowed:
            raise ValueError("unknown required financial dimension")


def adapt_retrieval_result(
    result: RetrievalResult, *, query: str, tenant_id: int, answer_type: AnswerType, locale: str
) -> SynthesisInput:
    """Preserve status and unknown coverage; never promote retrieved data to verified facts."""
    coverage = {name: getattr(result.coverage, name) for name in CoverageReport.__dataclass_fields__}
    return SynthesisInput(
        query,
        tenant_id,
        answer_type,
        locale,
        tuple(EvidenceSnapshot.from_evidence(item, tenant_id=tenant_id) for item in result.evidence),
        result.status.value,
        result.route.value,
        _freeze(coverage),
    )


def legacy_evidence_id(*, tenant_id: int, document_id: str, content_sha256: str, locator: Mapping) -> str:
    """Versioned source identity; rank, filename and answer language are deliberately absent."""
    if type(tenant_id) is not int or tenant_id < 0 or not document_id or not locator:
        raise ValueError("tenant, document and source locator required")
    if len(content_sha256) != 64 or any(char not in "0123456789abcdef" for char in content_sha256):
        raise ValueError("authoritative SHA256 required")
    material = json.dumps([tenant_id, document_id, content_sha256, dict(locator)], sort_keys=True, ensure_ascii=False)
    return "source:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def adapt_legacy_evidence(evidence: AgentEvidence, *, tenant_id: int, route: RetrievalMode) -> EvidenceSnapshot:
    """Strict legacy bridge: missing version/locator fails instead of inventing provenance."""
    metadata = evidence.metadata
    document_id = metadata.get("document_id")
    digest = metadata.get("content_sha256")
    locator = metadata.get("source_locator")
    if not isinstance(document_id, str) or not isinstance(digest, str) or not isinstance(locator, Mapping):
        raise ValueError("legacy evidence requires document version and source locator")
    identity = legacy_evidence_id(tenant_id=tenant_id, document_id=document_id, content_sha256=digest, locator=locator)
    unified = Evidence(
        evidence_id=identity,
        evidence_type=str(metadata.get("evidence_type", "legacy")),
        document_id=document_id,
        text=evidence.content,
        retriever=route,
        source_kind=str(metadata.get("source_kind", "unknown")),
        source=evidence.source,
        company=evidence.company,
        page=metadata.get("page"),
        bbox=metadata.get("bbox"),
        source_locator=locator,
        source_block_ids=tuple(metadata.get("source_block_ids", ())),
        structured_value=metadata.get("value"),
        metric=metadata.get("canonical_metric"),
        period=metadata.get("period_context", {}),
        scope=metadata.get("scope"),
        statement=metadata.get("statement_type"),
        confidence=evidence.confidence,
        provenance=metadata,
        citation=metadata.get("citation", {}),
        section=metadata.get("section"),
    )
    return EvidenceSnapshot.from_evidence(unified, tenant_id=tenant_id)


@dataclass(frozen=True)
class GroundedClaim:
    claim_id: str
    claim_type: ClaimType
    semantic_content: str
    evidence_ids: tuple[str, ...] = ()
    confidence: float | None = None
    fact_status: str = "UNVERIFIED"
    relation_type: RelationType | None = None
    causal_strength: CausalStrength = CausalStrength.UNSUPPORTED
    caveat: str | None = None
    observation: Mapping[str, Any] | None = None
    claim_subject: Mapping[str, Any] | None = None

    def __post_init__(self):
        if self.claim_subject is not None:
            object.__setattr__(self, "claim_subject", _freeze(self.claim_subject))
        if self.observation is not None:
            object.__setattr__(self, "observation", _freeze(self.observation))
        if not self.claim_id.strip() or not self.semantic_content.strip() or not isinstance(self.claim_type, ClaimType):
            raise ValueError("claim identity, content and explicit type required")
        if self.claim_type != ClaimType.UNCERTAINTY and not self.evidence_ids:
            raise ValueError("substantive claims require evidence")
        if self.confidence is not None and (not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1):
            raise ValueError("confidence must be finite and between zero and one")
        if self.claim_type == ClaimType.CONTRIBUTING_FACTOR:
            if self.causal_strength == CausalStrength.UNSUPPORTED:
                raise ValueError("unsupported contributing factor")
            if not self.caveat:
                raise ValueError("causal evidence strength must be disclosed")


@dataclass(frozen=True)
class ClaimEdge:
    source_claim_id: str
    target_claim_id: str
    relation: RelationType


@dataclass(frozen=True)
class AnswerPlan:
    answer_type: AnswerType
    claims: tuple[GroundedClaim, ...]
    relationships: tuple[ClaimEdge, ...] = ()
    evidence_requirements: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    output_structure: tuple[str, ...] = ("direct_answer", "basis", "sources")
    direct_answer_required: bool = True

    def validate_bindings(self, source: SynthesisInput) -> None:
        if self.answer_type != source.answer_type:
            raise ValueError("answer type mismatch")
        ids = {claim.claim_id for claim in self.claims}
        evidence_ids = {item.evidence_id for item in source.evidence}
        if len(ids) != len(self.claims):
            raise ValueError("duplicate claim identity")
        for claim in self.claims:
            if not set(claim.evidence_ids) <= evidence_ids:
                raise ValueError("unknown evidence identity")
        for edge in self.relationships:
            if edge.source_claim_id not in ids or edge.target_claim_id not in ids:
                raise ValueError("dangling claim graph edge")
        if self.answer_type == AnswerType.EXHAUSTIVE_LIST and source.coverage.get("complete") is not True:
            if not self.caveats:
                raise ValueError("unknown/incomplete exhaustive coverage requires caveat")


@dataclass(frozen=True)
class VerificationResult:
    failures: tuple[VerificationFailure, ...] = ()
    reviewed_claim_ids: tuple[str, ...] = ()
    semantic_review_complete: bool = False

    @property
    def passed(self) -> bool:
        # 结构检查成功不能自动升级为语义审核通过。
        return self.semantic_review_complete and not self.failures


@dataclass(frozen=True)
class RevisionPolicy:
    max_revisions: int = 1

    def __post_init__(self):
        if type(self.max_revisions) is not int or not 0 <= self.max_revisions <= 2:
            raise ValueError("revision limit must be an integer from zero to two")


class ResponseSynthesizer(Protocol):
    def synthesize(self, source: SynthesisInput, plan: AnswerPlan) -> AnswerPlan: ...


class AnswerPlanner(Protocol):
    def plan(self, source: SynthesisInput) -> AnswerPlan: ...


class AnswerVerifier(Protocol):
    def verify(self, source: SynthesisInput, plan: AnswerPlan, draft: str) -> VerificationResult: ...
