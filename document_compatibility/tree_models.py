"""Shared tree artifact schema; no query-time dependencies."""
from __future__ import annotations

from dataclasses import dataclass

from document_compatibility.models import CompatibilityReport
from document_compatibility.narrative_admission import NarrativeAdmission


@dataclass(frozen=True)
class TreeNode:
    node_id: str
    document_id: str
    parent_id: str | None
    title: str
    level: int
    start_page: int
    end_page: int
    source_block_ids: tuple[str, ...]
    child_ids: tuple[str, ...] = ()
    summary: str = ""
    source_kind: str = "CANONICAL_BLOCKS"
    tree_version: str = "1"
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentTree:
    tenant_id: int
    document_id: str
    content_sha256: str
    nodes: tuple[TreeNode, ...]
    report: CompatibilityReport | NarrativeAdmission
    policy_version: str = "page-tree-v1"
    schema_version: str = "1"
    builder_version: str = "1"
    summary_model: str | None = None
    quality: str = "LOW"
    source_type: str = "FALLBACK_PAGE_TREE"


@dataclass(frozen=True)
class TreeQualityReport:
    node_count: int
    max_depth: int
    heading_coverage: float
    page_coverage: float
    orphan_pages: tuple[int, ...]
    source_block_coverage: float
    summary_coverage: float
    invalid_ranges: tuple[str, ...]
    overlapping_ranges: tuple[tuple[str, str], ...]
    errors: tuple[str, ...]
    tree_quality: str
