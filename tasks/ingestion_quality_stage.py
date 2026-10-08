"""Compatibility audit plus coverage of the actual persisted parser output."""

import json

from document_compatibility.adapters import normalized
from document_compatibility.engine import inspect_pdf
from document_compatibility.models import DocumentState
from tasks.ingestion_parse_stage import ocr_configuration


class PDFQualityStage:
    def __init__(self, artifact_store, *, ocr=None):
        self.artifact_store = artifact_store
        self.ocr = ocr

    def execute(self, lease, *, parse_artifact_sha256):
        if lease.stage != "QUALITY_CHECK":
            raise ValueError("QUALITY_STAGE_MISMATCH")
        store = self.artifact_store
        payload = json.loads(store.read(lease.tenant_id, lease.source_sha256, parse_artifact_sha256))
        if (payload.get("schema") != "financial-ingestion-parse.v1"
                or payload.get("source_sha256") != lease.source_sha256
                or payload.get("tenant_id") != lease.tenant_id
                or payload.get("document_id") != lease.document_id):
            raise ValueError("QUALITY_PARSE_IDENTITY_MISMATCH")
        if (payload.get("ocr_configuration") != ocr_configuration(self.ocr)
                or payload.get("ocr_enabled") is not (self.ocr is not None)):
            raise ValueError("QUALITY_OCR_CONFIGURATION_MISMATCH")
        store.read(lease.tenant_id, lease.source_sha256, lease.source_sha256)
        source = store._path(lease.tenant_id, lease.source_sha256, lease.source_sha256)
        inventory, report = inspect_pdf(source, ocr=self.ocr)
        rendered = {}
        for chunk in payload["chunks"]:
            rendered.setdefault(chunk["page"], []).append(normalized(chunk["text"]))
        missing = [span.span_id for span in inventory.native_spans
                   if span.valid and normalized(span.text)
                   and not any(normalized(span.text) in text for text in rendered.get(span.page, []))]
        missing_ocr = [sid for block in report.blocks if block.source == "OCR"
                       and not any(normalized(block.text) in text for text in rendered.get(block.page, []))
                       for sid in block.source_ids]
        passed = report.state == DocumentState.READY and bool(payload["chunks"]) and not missing and not missing_ocr
        result = {"schema": "financial-ingestion-quality.v1", "source_sha256": lease.source_sha256,
                  "parse_artifact_sha256": parse_artifact_sha256, "compatibility": report.to_dict(),
                  "missing_native_source_ids": missing, "missing_ocr_source_ids": missing_ocr,
                  "quality_status": "PASS" if passed else "FAIL"}
        store.read(lease.tenant_id, lease.source_sha256, lease.source_sha256)
        digest = store.put(lease.tenant_id, lease.source_sha256,
                           json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode())
        return {"artifact_id": digest, "artifact_sha256": digest, "quality_status": result["quality_status"]}
