"""READY-bound financial artifact observations; no inference or DB writes."""

import re
from decimal import Decimal

from core.answer_synthesis_contracts import EvidenceSnapshot
from core.answer_synthesis_planner import locked_observation
from core.financial_metric_registry import FINANCIAL_METRIC_REGISTRY
from retrieval.adaptive_contract import Evidence, RetrievalMode


class ReadyFinancialFactEvidence:
    def __init__(self, ledger):
        self.ledger = ledger

    def retrieve(self, job_id, *, tenant_id, user_id, metric, scope, fiscal_year):
        if (FINANCIAL_METRIC_REGISTRY.get(metric) is None
                or scope not in {"CONSOLIDATED", "PARENT_COMPANY"}
                or not isinstance(fiscal_year, str) or not re.fullmatch(r"20\d{2}", fiscal_year)):
            raise ValueError("EXPLICIT_FINANCIAL_QUERY_REQUIRED")
        artifact = self.ledger.ready_facts(job_id, tenant_id, user_id)
        metadata = self.ledger.ready_document_metadata(job_id, tenant_id, user_id)
        if (metadata["document_id"] != artifact["document_id"]
                or metadata["source_sha256"] != artifact["source_sha256"]):
            raise ValueError("READY_FACT_DOCUMENT_METADATA_MISMATCH")
        result = []
        for fact in artifact["facts"]:
            if not isinstance(fact, dict):
                raise ValueError("INVALID_READY_FACT_SCHEMA")
            if (fact.get("metric_id"), fact.get("scope"), fact.get("fiscal_year")) != (metric, scope, fiscal_year):
                continue
            if (fact.get("document_id") != str(artifact["document_id"])
                    or fact.get("created_from") != "financial_table_row"
                    or fact.get("row_verification_status") != "VERIFIED"
                    or fact.get("mapping_status") not in {"EXACT", "SUPPORTED"}
                    or not fact.get("fact_id") or not fact.get("source_locator")
                    or type(fact.get("normalized_value")) is not str):
                raise ValueError("READY_FACT_PROVENANCE_INVALID")
            period = {"period_type": fact["period_type"], "period_start": fact["period_start"],
                      "period_end": fact["period_end"], "fiscal_year": fact["fiscal_year"]}
            row_provenance = fact.get("table_row_provenance")
            if row_provenance is not None:
                from services.financial_fact_provenance import validate_table_row

                validate_table_row(fact, tenant_id=tenant_id, document_id=artifact["document_id"],
                                   source_sha256=artifact["source_sha256"])
            evidence = Evidence(
                evidence_id="financial-fact:" + artifact["source_sha256"] + ":" + fact["fact_id"],
                evidence_type="STRUCTURED_FINANCIAL_FACT", document_id=fact["document_id"],
                text=fact["evidence_text"], retriever=RetrievalMode.FACT,
                source_kind="verified_financial_fact", source=metadata["filename"], company=fact["company"],
                page=fact["page"],
                source_locator={"page": fact["page"], "locator": fact["source_locator"],
                                "table_id": fact["table_id"], "row_id": fact["row_id"]},
                structured_value=Decimal(fact["normalized_value"]), metric=metric, period=period,
                scope=scope, statement=fact["statement_type"], confidence=1.0,
                provenance={"tenant_id": tenant_id, "structured_financial_fact": True,
                    "row_verification_status": fact["row_verification_status"],
                    "mapping_status": fact["mapping_status"], "content_sha256": artifact["source_sha256"],
                    "document_version": artifact["source_sha256"], "currency": fact["currency"],
                    "section": fact["section"],
                    "company_name_zh": fact.get("company_name") or fact["company"],
                    "unit": fact["unit"], "fact_artifact_source": artifact["source_sha256"],
                    "accounting_standard": fact.get("accounting_standard", "UNKNOWN"),
                    "accounting_standard_source": fact.get("accounting_standard_source")},
                citation={"page": fact["page"]},
            )
            if row_provenance is not None:
                evidence.provenance["table_row_provenance"] = row_provenance
            snapshot = EvidenceSnapshot.from_evidence(evidence, tenant_id=tenant_id)
            locked_observation(snapshot)
            result.append(snapshot)
        if len({item.evidence_id for item in result}) != len(result):
            raise ValueError("DUPLICATE_READY_FACT_IDENTITY")
        return tuple(result)
