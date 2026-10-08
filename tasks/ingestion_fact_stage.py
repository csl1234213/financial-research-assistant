"""Deterministic eligible fact artifacts, separate from production persistence."""

import json
import re
from dataclasses import asdict

from core.financial_facts import FinancialDocumentContext, financial_facts_from_rows, rows_from_json


def _calendar(chunks):
    matches = []
    for chunk in chunks:
        heading = f"{chunk['section']}\n{chunk['text'][:300]}"
        if not any(label in heading for label in ("利润表", "现金流量表", "所有者权益变动表")):
            continue
        for match in re.finditer(r"(20\d{2})\s*年\s*(\d{1,2})\s*[—–-]\s*(\d{1,2})\s*月",
                                 chunk["text"][:600]):
            matches.append((int(match[1]), int(match[2]), int(match[3]), chunk["page"], match[0]))
    if not matches or len({item[:3] for item in matches}) != 1 or matches[0][1:3] != (1, 12):
        return FinancialDocumentContext()
    year, _, _, page, label = matches[0]
    return FinancialDocumentContext(fiscal_year_start=f"{year}-01-01", fiscal_year_end=f"{year}-12-31",
                                    fiscal_calendar_source=f"PDF page {page}: {label}")


class FinancialFactStage:
    def __init__(self, artifact_store):
        self.store = artifact_store

    def execute(self, lease, *, parse_artifact_sha256, quality_artifact_sha256):
        if lease.stage != "BUILDING_FACTS":
            raise ValueError("FACT_STAGE_MISMATCH")
        parsed = json.loads(self.store.read(lease.tenant_id, lease.source_sha256, parse_artifact_sha256))
        quality = json.loads(self.store.read(lease.tenant_id, lease.source_sha256, quality_artifact_sha256))
        if (parsed.get("schema") != "financial-ingestion-parse.v1"
                or parsed.get("source_sha256") != lease.source_sha256
                or parsed.get("document_id") != lease.document_id
                or parsed.get("tenant_id") != lease.tenant_id
                or quality.get("schema") != "financial-ingestion-quality.v1"
                or quality.get("source_sha256") != lease.source_sha256
                or quality.get("parse_artifact_sha256") != parse_artifact_sha256
                or quality.get("quality_status") != "PASS"):
            raise ValueError("FACT_SOURCE_OR_QUALITY_GATE_FAILED")
        raw = [row for chunk in parsed["chunks"] for row in chunk["financial_table_rows"]]
        rows = tuple(dict.fromkeys(rows_from_json(json.dumps(raw))))
        if any(row.document_id != str(lease.document_id) for row in rows):
            raise ValueError("FACT_ROW_DOCUMENT_MISMATCH")
        facts = financial_facts_from_rows(rows, context=_calendar(parsed["chunks"]))
        payload = {"schema": "financial-ingestion-facts.v1", "source_sha256": lease.source_sha256,
                   "document_id": lease.document_id, "tenant_id": lease.tenant_id,
                   "parse_artifact_sha256": parse_artifact_sha256,
                   "quality_artifact_sha256": quality_artifact_sha256,
                   "rows_seen": len(rows), "facts": [asdict(fact) for fact in facts]}
        digest = self.store.put(lease.tenant_id, lease.source_sha256,
                                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode())
        return {"artifact_id": digest, "artifact_sha256": digest}
