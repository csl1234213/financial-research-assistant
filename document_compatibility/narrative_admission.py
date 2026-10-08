"""Page-local narrative admission, separate from whole-document/fact readiness."""
from __future__ import annotations

from dataclasses import dataclass

from .models import CompatibilityReport, DocumentBlock, DocumentState, PageQualityReport

POLICY_VERSION = "clean-native-narrative-shadow-v1"


def eligible_pages(report: CompatibilityReport) -> tuple[int, ...]:
    """Conservative whole-page exclusion; no claim of regional table recovery."""
    if report.state not in {DocumentState.READY, DocumentState.QUARANTINED}:
        return ()
    if any(f.page <= 0 for f in report.failures):
        return ()
    failed = {f.page for f in report.failures}
    table_pages = {b.page for b in report.blocks if b.block_type == "TABLE" or b.continuation}
    return tuple(p.page for p in report.pages
                 if p.page not in failed | table_pages and p.quality_status == "PASS"
                 and p.reading_order_status == "PASS" and p.table_status == "PASS"
                 and p.native_span_count > 0 and p.ocr_span_count == 0
                 and p.orphan_count == 0 and p.critical_orphan_count == 0
                 and p.geometry_coverage >= 0.999999 and not p.missing_regions
                 and not p.failure_classes and not p.recovery_required)


def eligible_blocks(report: CompatibilityReport) -> tuple[DocumentBlock, ...]:
    pages = set(eligible_pages(report))
    return tuple(b for b in report.blocks if b.page in pages and b.block_type in {"TEXT", "TITLE"}
                 and b.document_id == report.document_id and b.source == "NATIVE_PDF"
                 and b.source_ids and b.bbox is not None and b.text.strip()
                 and not b.recovered and not b.provenance and not b.continuation
                 and not b.table_header and not b.table_cells)


@dataclass(frozen=True)
class NarrativeAdmission:
    """Not a CompatibilityReport and never eligible for FactLedger ingestion."""
    source_report: CompatibilityReport
    blocks: tuple[DocumentBlock, ...]
    pages: tuple[PageQualityReport, ...]
    state: str = "READY_FOR_NARRATIVE_SHADOW"
    policy_version: str = POLICY_VERSION

    @property
    def document_id(self):
        return self.source_report.document_id

    @property
    def parsed_with_policy_version(self):
        return self.source_report.parsed_with_policy_version + ":" + self.policy_version

    def validate(self):
        expected = eligible_blocks(self.source_report)
        expected_pages = tuple(p for p in self.source_report.pages if p.page in {b.page for b in expected})
        if (not expected or self.blocks != expected or self.pages != expected_pages
                or self.state != "READY_FOR_NARRATIVE_SHADOW" or self.policy_version != POLICY_VERSION):
            raise ValueError("invalid or forged narrative admission")

    def provenance(self):
        return {"admission_scope": "NARRATIVE_SHADOW_ONLY", "admission_policy": self.policy_version,
                "whole_document_state": str(self.source_report.state),
                "admitted_pages": [p.page for p in self.pages],
                "excluded_pages": [p.page for p in self.source_report.pages if p not in self.pages],
                "whole_document_block_count": len(self.source_report.blocks),
                "admitted_block_count": len(self.blocks),
                "excluded_block_count": len(self.source_report.blocks) - len(self.blocks),
                "fact_eligible": False}


def admit_narrative(report: CompatibilityReport) -> NarrativeAdmission:
    blocks = eligible_blocks(report)
    pages = tuple(p for p in report.pages if p.page in {b.page for b in blocks})
    admission = NarrativeAdmission(report, blocks, pages)
    admission.validate()
    return admission
