"""Verified table-row authority, distinct from narrative canonical blocks."""

import hashlib
import json
from dataclasses import asdict

from core.financial_facts import FinancialFactFactory, rows_from_json


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def bind_table_rows(payload, parsed, *, context):
    """Prove existing fact creation from its exact immutable parse row; no writes."""
    identity = (payload["tenant_id"], payload["document_id"], payload["source_sha256"])
    if (parsed.get("schema") != "financial-ingestion-parse.v1"
            or (parsed.get("tenant_id"), parsed.get("document_id"), parsed.get("source_sha256")) != identity):
        raise ValueError("FACT_ROW_PARSE_BINDING_INVALID")
    rows = tuple(dict.fromkeys(rows_from_json(canonical_json(
        [row for chunk in parsed["chunks"] for row in chunk["financial_table_rows"]]))))
    factory = FinancialFactFactory()
    candidates = {}
    for row in rows:
        if not row.eligible_for_deterministic_fact:
            continue
        try:
            fact = factory.create(row, context=context)
        except ValueError:
            continue  # Unmapped/ineligible rows are not fact authority.
        key = canonical_json(asdict(fact))
        candidates.setdefault(key, []).append(row)
    bound = []
    for fact in payload["facts"]:
        matches = candidates.get(canonical_json(fact), [])
        if len(matches) != 1:
            raise ValueError("UNIQUE_VERIFIED_FACT_ROW_REQUIRED")
        row = matches[0]
        row_data = asdict(row)
        proof = {"source_kind": "FINANCIAL_TABLE_ROW", "tenant_id": identity[0],
            "document_id": str(identity[1]), "document_version": identity[2],
            "source_sha256": identity[2], "parse_artifact_sha256": payload["parse_artifact_sha256"],
            "fact_id": fact["fact_id"], "table_id": fact["table_id"], "row_id": fact["row_id"],
            "page": row.page, "source_locator": row.source_locator,
            "source_region": row.source_region, "verification_status": row.verification_status.value,
            "row": row_data, "row_digest": hashlib.sha256(canonical_json(row_data).encode()).hexdigest()}
        enriched = {**fact, "table_row_provenance": proof}
        validate_table_row(enriched, tenant_id=identity[0], document_id=identity[1], source_sha256=identity[2])
        bound.append(enriched)
    return {**payload, "facts": bound}


def validate_table_row(fact, *, tenant_id, document_id, source_sha256):
    proof = fact.get("table_row_provenance")
    if not isinstance(proof, dict) or not isinstance(proof.get("row"), dict):
        raise ValueError("VERIFIED_TABLE_ROW_PROVENANCE_REQUIRED")
    row = proof["row"]
    if (proof.get("source_kind") != "FINANCIAL_TABLE_ROW"
            or proof.get("tenant_id") != tenant_id or proof.get("document_id") != str(document_id)
            or proof.get("document_version") != source_sha256 or proof.get("source_sha256") != source_sha256
            or proof.get("fact_id") != fact.get("fact_id")
            or not proof.get("row_id") or not proof.get("table_id")
            or proof.get("table_id") != fact.get("table_id") or proof.get("row_id") != fact.get("row_id")
            or proof.get("page") != fact.get("page") or row.get("page") != fact.get("page")
            or row.get("document_id") != str(document_id)
            or proof.get("source_locator") != fact.get("source_locator")
            or row.get("source_locator") != fact.get("source_locator")
            or row.get("raw_value") != fact.get("raw_value")
            or row.get("source_text") != fact.get("source_text")
            or proof.get("verification_status") != "VERIFIED" or row.get("verification_status") != "VERIFIED"
            or not row.get("column_binding_proven")
            or proof.get("row_digest") != hashlib.sha256(canonical_json(row).encode()).hexdigest()):
        raise ValueError("VERIFIED_TABLE_ROW_PROVENANCE_INVALID")
    return proof
