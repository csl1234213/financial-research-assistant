"""Immutable compatibility inventory and decisions, independent of fact eligibility."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum

BBox = tuple[float, float, float, float]


class DocumentState(StrEnum):
    DOWNLOADED = "DOWNLOADED"
    FINGERPRINTED = "FINGERPRINTED"
    PARSING = "PARSING"
    QUALITY_CHECK = "QUALITY_CHECK"
    RECOVERY = "RECOVERY"
    READY = "READY"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


class FailureClass(StrEnum):
    NO_NATIVE_TEXT = "NO_NATIVE_TEXT"
    OCR_REQUIRED = "OCR_REQUIRED"
    LAYOUT_LOSS = "LAYOUT_LOSS"
    MULTICOLUMN_READING_ORDER_ERROR = "MULTICOLUMN_READING_ORDER_ERROR"
    TABLE_STRUCTURE_LOSS = "TABLE_STRUCTURE_LOSS"
    CROSS_PAGE_TABLE_HEADER_LOSS = "CROSS_PAGE_TABLE_HEADER_LOSS"
    MERGED_CELL_AMBIGUITY = "MERGED_CELL_AMBIGUITY"
    TABLE_COLUMN_SHIFT = "TABLE_COLUMN_SHIFT"
    ORPHAN_TEXT = "ORPHAN_TEXT"
    CRITICAL_FINANCIAL_CONTENT_LOSS = "CRITICAL_FINANCIAL_CONTENT_LOSS"
    PERIOD_CONTEXT_LOSS = "PERIOD_CONTEXT_LOSS"
    UNIT_CONTEXT_LOSS = "UNIT_CONTEXT_LOSS"
    SCOPE_CONTEXT_LOSS = "SCOPE_CONTEXT_LOSS"
    SERIALIZATION_LOSS = "SERIALIZATION_LOSS"
    CHUNK_BLOCK_LOSS = "CHUNK_BLOCK_LOSS"
    PAGE_PARSE_FAILURE = "PAGE_PARSE_FAILURE"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"
    UNKNOWN_DOCUMENT_PROFILE = "UNKNOWN_DOCUMENT_PROFILE"
    NATIVE_OCR_NUMERIC_CONFLICT = "NATIVE_OCR_NUMERIC_CONFLICT"
    PROVENANCE_LOSS = "PROVENANCE_LOSS"


class FormatFamily(StrEnum):
    CAS_ANNUAL_REPORT = "CAS_ANNUAL_REPORT"
    CAS_INTERIM_REPORT = "CAS_INTERIM_REPORT"
    SEC_10K = "SEC_10K"
    SEC_10Q = "SEC_10Q"
    IFRS_ANNUAL_REPORT = "IFRS_ANNUAL_REPORT"
    NATIVE_TEXT_PDF = "NATIVE_TEXT_PDF"
    SCANNED_PDF = "SCANNED_PDF"
    HYBRID_PDF = "HYBRID_PDF"
    MULTICOLUMN_REPORT = "MULTICOLUMN_REPORT"
    COMPLEX_TABLE_REPORT = "COMPLEX_TABLE_REPORT"
    UNKNOWN = "UNKNOWN"


def stable_id(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class SourceSpan:
    span_id: str
    page: int
    text: str
    bbox: BBox
    source: str = "NATIVE_PDF"
    parser_id: str = "pymupdf-native"
    valid: bool = True


@dataclass(frozen=True)
class RecoveryProvenance:
    failure_class: str
    recovery_policy: str
    recovery_version: str
    old_source: str
    new_source: str
    reason: str
    source_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class TableCellGeometry:
    row: int
    column: int
    text: str
    bbox: BBox
    row_span: int
    column_span: int
    source_ids: tuple[str, ...] = ()
    source_binding_proven: bool = False


@dataclass(frozen=True)
class ContextRequirement:
    block_id: str
    page: int
    failure_class: FailureClass
    source_id: str
    text: str


@dataclass(frozen=True)
class ReadingOrderConstraint:
    page: int
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class DocumentBlock:
    block_id: str
    document_id: str
    page: int
    block_type: str
    text: str
    bbox: BBox | None
    source: str
    parser_id: str
    parser_version: str
    policy_version: str
    confidence: float = 1.0
    reading_order: int = 0
    parent_block_id: str | None = None
    source_ids: tuple[str, ...] = ()
    recovered: bool = False
    recovery_reason: str | None = None
    provenance: tuple[RecoveryProvenance, ...] = ()
    table_header: str = ""
    table_columns: tuple[float, ...] = ()
    continuation: bool = False
    section: str = ""
    table_cells: tuple[TableCellGeometry, ...] = ()
    context_text: str = ""
    context_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageFeatures:
    page: int
    native_text_density: float = 0.0
    image_ratio: float = 0.0
    table_density: float = 0.0
    column_count: int = 1
    layout_complexity: str = "LOW"
    native_text_quality: float = 1.0
    ocr_required: bool = False
    table_structure_confidence: float = 1.0
    reading_order_confidence: float = 1.0
    blank: bool = False
    has_native: bool = False
    scan_quality: float | None = None
    width: float = 0.0
    height: float = 0.0
    complex_table: bool = False


@dataclass(frozen=True)
class DocumentFingerprint:
    document_id: str
    page_count: int
    native_text_page_ratio: float
    image_only_page_ratio: float
    mixed_page_ratio: float
    table_density: float
    multi_column_ratio: float
    ocr_required_ratio: float
    language: tuple[str, ...]
    accounting_hints: tuple[str, ...]
    financial_statement_presence: tuple[str, ...]
    layout_complexity: str
    native_text_quality: float
    scan_quality: float | None
    source_format: str


@dataclass(frozen=True)
class DocumentProfile:
    fingerprint: DocumentFingerprint
    format_families: tuple[FormatFamily, ...]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FailureSignature:
    failure_class: FailureClass
    page: int
    source_ids: tuple[str, ...] = ()
    block_ids: tuple[str, ...] = ()
    features: tuple[tuple[str, str], ...] = ()
    critical: bool = False


@dataclass(frozen=True)
class DiscardRecord:
    block_id: str
    reason: str
    retained_block_id: str | None = None


@dataclass(frozen=True)
class TracedChunk:
    chunk_id: str
    page: int
    text: str
    source_block_ids: tuple[str, ...]
    policy_version: str


@dataclass(frozen=True)
class ExtractionInventory:
    document_id: str
    profile: DocumentProfile
    page_features: tuple[PageFeatures, ...]
    native_spans: tuple[SourceSpan, ...]
    ocr_spans: tuple[SourceSpan, ...]
    canonical_blocks: tuple[DocumentBlock, ...]
    parser_failures: tuple[FailureSignature, ...] = ()
    table_candidates: int = 0
    table_cells: int = 0
    parsed_document: object | None = field(default=None, repr=False, compare=False)
    timings: dict[str, float] = field(default_factory=dict, compare=False)
    context_requirements: tuple[ContextRequirement, ...] = ()
    reading_order_constraints: tuple[ReadingOrderConstraint, ...] = ()


@dataclass(frozen=True)
class PageQualityReport:
    page: int
    document_profile: tuple[str, ...]
    parser_policy_version: str
    primary_parser: str
    shadow_parser: str | None
    native_span_count: int
    ocr_span_count: int
    canonical_block_count: int
    orphan_count: int
    critical_orphan_count: int
    geometry_coverage: float
    missing_regions: tuple[BBox, ...]
    reading_order_status: str
    table_status: str
    failure_classes: tuple[str, ...]
    recovery_required: bool
    quality_status: str


@dataclass(frozen=True)
class CompatibilityReport:
    document_id: str
    profile: DocumentProfile
    parsed_with_policy_version: str
    state: DocumentState
    pages: tuple[PageQualityReport, ...]
    failures_before: tuple[FailureSignature, ...]
    failures: tuple[FailureSignature, ...]
    blocks: tuple[DocumentBlock, ...]
    chunks: tuple[TracedChunk, ...]
    discards: tuple[DiscardRecord, ...]
    quality_contract: tuple[str, ...]
    counters: dict[str, int]
    timings: dict[str, float]
    transition_trace: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)
