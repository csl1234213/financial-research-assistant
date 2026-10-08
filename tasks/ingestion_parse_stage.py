"""Real canonical PDF parsing into isolated, source-bound durable artifacts."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import fitz

from core.ingestion_contracts import StageLease
from document_compatibility.adapters import NativePDFAdapter, normalized
from document_compatibility.engine import inspect_pdf
from document_loader import (
    CHUNKER_VERSION,
    PARSER_VERSION,
    DocumentChunk,
    DocumentProcessingError,
    load_pdf_chunks,
)


class PDFParseStage:
    def __init__(self, artifact_store, *, ocr=None):
        self.artifact_store = artifact_store
        self.ocr = ocr

    def execute(self, lease: StageLease, source_path: Path):
        if lease.stage != "PARSING":
            raise ValueError("PARSER_STAGE_MISMATCH")
        content = Path(source_path).read_bytes()
        if hashlib.sha256(content).hexdigest() != lease.source_sha256:
            raise ValueError("PARSER_SOURCE_IDENTITY_CHANGED")
        # Parse a durable snapshot, not the mutable upload path.
        snapshot = self.artifact_store.put(lease.tenant_id, lease.source_sha256, content)
        path = self.artifact_store._path(lease.tenant_id, lease.source_sha256, snapshot)
        try:
            chunks = load_pdf_chunks(path, ocr_enabled=False, document_id=str(lease.document_id))
        except DocumentProcessingError:
            if self.ocr is None:
                raise
            # A scan-only PDF legitimately has no native chunks. Do not suppress
            # parser errors for documents with native text or without image data.
            with fitz.open(path) as scanned:
                if (not any(page.get_image_info() for page in scanned)
                        or any(page.get_text().strip() for page in scanned)):
                    raise
            chunks = []
        repairs = []
        native = NativePDFAdapter()
        with fitz.open(path) as document:
            for page in document:
                for span in native.parse_page(page, str(lease.document_id)):
                    if not span.valid or not normalized(span.text):
                        continue
                    if any(chunk.page == span.page and normalized(span.text) in normalized(chunk.text)
                           for chunk in chunks):
                        continue
                    # Preserve omitted labels/headings verbatim, never manufacture values
                    # or promote these spans to verified financial table rows.
                    chunks.append(DocumentChunk(
                        text=span.text, page=span.page, section="Native source coverage",
                        ocr_used=False, chunk_index=len(chunks), content_type="native_coverage",
                        source_locator=f"PDF page {span.page}, bbox {span.bbox}",
                    ))
                    repairs.append({"source_id": span.span_id, "page": span.page,
                                    "bbox": span.bbox, "text": span.text,
                                    "reason": "NATIVE_SPAN_ABSENT_FROM_CANONICAL_CHUNKS"})
        ocr_sources = []
        if self.ocr is not None:
            _, report = inspect_pdf(path, ocr=self.ocr)
            for block in report.blocks:
                if block.source != "OCR":
                    continue
                # OCR text is searchable evidence, never a verified financial row.
                chunks.append(DocumentChunk(
                    text=block.text, page=block.page, section="Image region OCR",
                    ocr_used=True, chunk_index=len(chunks), content_type="ocr_coverage",
                    source_locator=f"PDF page {block.page}, bbox {block.bbox}",
                ))
                ocr_sources.append({"source_ids": block.source_ids, "page": block.page,
                                    "bbox": block.bbox, "text": block.text,
                                    "parser_version": block.parser_version})
        self.artifact_store.read(lease.tenant_id, lease.source_sha256, snapshot)
        from document_loader import get_document_company, get_document_period

        identity = {"company": get_document_company(chunks), "report_period": get_document_period(chunks),
                    "source_pages": sorted({chunk.page for chunk in chunks[:8]}),
                    "method": "opening_content_parser", "source_sha256": lease.source_sha256}
        payload = {
            "schema": "financial-ingestion-parse.v1",
            "source_sha256": lease.source_sha256,
            "tenant_id": lease.tenant_id,
            "document_id": lease.document_id,
            "document_identity": identity,
            "parser_version": PARSER_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "ocr_enabled": self.ocr is not None,
            "ocr_configuration": ocr_configuration(self.ocr),
            "ocr_sources": ocr_sources,
            "native_coverage_repairs": repairs,
            "chunks": [asdict(chunk) for chunk in chunks],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        digest = self.artifact_store.put(lease.tenant_id, lease.source_sha256, encoded)
        return {"artifact_id": digest, "artifact_sha256": digest}


def ocr_configuration(adapter):
    """Bind parse and quality operators to the same explicit OCR configuration."""
    if adapter is None:
        return None
    return {"parser_id": adapter.parser_id, "parser_version": adapter.parser_version,
            "language": adapter.language, "dpi": adapter.dpi}
