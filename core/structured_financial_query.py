"""Conservative routing helpers for persisted, source-backed financial facts."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Callable

from sqlalchemy.exc import SQLAlchemyError

from agent.reasoning_models import Evidence
from core.fact_ledger import FinancialFact, canonical_company
from core.financial_metric_registry import FINANCIAL_METRIC_REGISTRY
from core.persistent_financial_facts import SQLFinancialFactRepository
from models.document import Document
from storage.database import SessionLocal

logger = logging.getLogger(__name__)


class StructuredLookupStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    UNSUPPORTED_METRIC = "UNSUPPORTED_METRIC"
    UNSUPPORTED_QUERY = "UNSUPPORTED_QUERY"


@dataclass(frozen=True, slots=True)
class StructuredFinancialQueryResult:
    status: StructuredLookupStatus
    trace: dict[str, Any]
    answer: str = ""
    evidence: tuple[Evidence, ...] = ()
    terminal: bool = False


def _query_scope(query: str) -> tuple[str, str]:
    if re.search(r"母公司|母公司口径|单体报表|母公司报表|parent\s+company|standalone", query, re.I):
        return "PARENT_COMPANY", "explicit_parent_company"
    if re.search(r"合并口径|合并报表|consolidated", query, re.I):
        return "CONSOLIDATED", "explicit_consolidated"
    return "CONSOLIDATED", "default_consolidated"


def _is_full_fiscal_duration(fact: FinancialFact) -> bool:
    if fact.period_type.upper() != "DURATION" or not fact.period_start or not fact.period_end:
        return False
    try:
        start = date.fromisoformat(fact.period_start[:10])
        end = date.fromisoformat(fact.period_end[:10])
    except ValueError:
        return False
    return 300 <= (end - start).days <= 400


def _source_evidence(fact: FinancialFact, document: Document) -> Evidence | None:
    if fact.mapping_status not in {"EXACT", "SUPPORTED"}:
        return None
    if fact.row_verification_status != "VERIFIED":
        return None
    if not fact.page or not fact.source_locator or not fact.source_text or not fact.evidence_text:
        return None
    content = (
        f"Verified financial statement fact: company={fact.company_name or fact.company}; "
        f"metric={fact.metric_id}; original_label={fact.original_label or fact.metric_label}; "
        f"value={fact.normalized_value}; currency={fact.currency or 'unknown'}; unit={fact.unit}; "
        f"fiscal_year={fact.fiscal_year}; period_type={fact.period_type}; "
        f"period_start={fact.period_start or 'unknown'}; period_end={fact.period_end or 'unknown'}; "
        f"scope={fact.scope}; statement={fact.statement_type}; page={fact.page}.\n"
        f"Source row: {fact.source_text}"
    )
    return Evidence(
        content=content,
        source=document.filename,
        company=fact.company_name or fact.company,
        confidence=float(fact.confidence),
        metadata={
            "structured_financial_fact": True,
            "fact_id": fact.fact_id,
            "chunk_id": f"financial-fact:{fact.fact_id}",
            "document_id": fact.document_id,
            "document_version": document.content_sha256,
            "canonical_metric": fact.metric_id,
            "original_label": fact.original_label or fact.metric_label,
            "normalized_label": fact.normalized_label,
            "value": str(fact.normalized_value),
            "currency": fact.currency,
            "unit": fact.unit,
            "fiscal_year": fact.fiscal_year,
            "fiscal_quarter": fact.fiscal_quarter,
            "period_type": fact.period_type,
            "period_start": fact.period_start,
            "period_end": fact.period_end,
            "scope": fact.scope,
            "statement_type": fact.statement_type,
            "page": fact.page,
            "section": fact.section,
            "source_locator": fact.source_locator,
            "source_authority": "verified_financial_fact",
            "mapping_status": fact.mapping_status,
            "mapping_rule": fact.mapping_rule,
            "row_verification_status": fact.row_verification_status,
            "tenant_id": document.tenant_id,
        },
    )


def _fact_matches_request(
    fact: FinancialFact,
    document: Document,
    *,
    company: str,
    metric: str,
    fiscal_year: str,
    period_type: str,
    scope: str,
) -> bool:
    definition = FINANCIAL_METRIC_REGISTRY.get(metric)
    if definition is None or fact.statement_type not in definition.statement_types:
        return False
    if fact.metric_id != metric or str(fact.fiscal_year) != fiscal_year:
        return False
    if fact.period_type.upper() != period_type or fact.scope != scope:
        return False
    if canonical_company(fact.company_id or fact.company) != canonical_company(company):
        return False
    if document.company and document.company.casefold() != "unknown":
        if canonical_company(document.company) != canonical_company(company):
            return False
    if not fact.currency or not fact.unit:
        return False
    if period_type == "INSTANT":
        return bool(fact.period_end)
    return _is_full_fiscal_duration(fact)


def _render_answer(
    fact: FinancialFact,
    *,
    response_language: str | None,
) -> str:
    # Presentation only: never change the persisted observation or citation.
    from core.answer_synthesis_renderer import NumericPresentation

    value = format(fact.normalized_value, ",f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    label = fact.original_label or fact.metric_label or fact.metric_id
    company = fact.company_name or fact.company
    scope = "母公司" if fact.scope == "PARENT_COMPANY" else "合并"
    chinese = response_language == "zh-CN"
    if response_language is None:
        chinese = bool(re.search(r"[\u3400-\u9fff]", label + company))
    definition = FINANCIAL_METRIC_REGISTRY.get(fact.metric_id)
    if definition:
        aliases = definition.aliases_zh if chinese else definition.aliases_en
        if aliases:
            label = aliases[0]
    if not chinese:
        # Existing canonical company ontology aliases, not inferred translations.
        company = {
            "moutai": "Kweichow Moutai",
            "apple": "Apple",
            "tesla": "Tesla",
            "nvidia": "NVIDIA",
            "microsoft": "Microsoft",
        }.get(canonical_company(fact.company), fact.company)
    if definition and definition.value_type == "monetary":
        try:
            money = NumericPresentation.build(
                fact.normalized_value,
                currency=(fact.currency or "").upper(),
                unit=fact.unit,
                locale="zh-CN" if chinese else "en",
            ).text
        except ValueError:
            # Unsupported currencies/units retain the legacy exact projection;
            # never guess a conversion or scale.
            money = None
        if money is not None:
            return (
                f"{company} FY{fact.fiscal_year} {scope}口径的{label}为{money}。[1]"
                if chinese
                else f"{company} FY{fact.fiscal_year} "
                f"{'parent-company' if fact.scope == 'PARENT_COMPANY' else 'consolidated'} "
                f"{label} was {money}. [1]"
            )
    if chinese:
        currency = {"CNY": "人民币", "USD": "美元", "EUR": "欧元"}.get(
            (fact.currency or "").upper(), fact.currency or ""
        )
        unit = "元" if (fact.unit or "").upper() in {"CNY", "USD", "EUR", "CNY_YUAN"} else fact.unit
        return f"{company} FY{fact.fiscal_year} {scope}口径的“{label}”为 {value} {unit}{currency}。[1]"
    currency = (fact.currency or "").upper()
    unit = {"CNY_YUAN": "yuan", "USD_UNIT": "USD", "EUR_UNIT": "EUR"}.get((fact.unit or "").upper(), fact.unit)
    scope_en = "parent-company" if fact.scope == "PARENT_COMPANY" else "consolidated"
    return f"{company} FY{fact.fiscal_year} {scope_en} {label} was {currency} {value} ({unit}). [1]"


def lookup_persisted_financial_fact(
    *,
    query: str,
    company: str,
    canonical_metric: str,
    fiscal_year: str,
    period_semantics: str,
    tenant_id: int,
    response_language: str | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
) -> StructuredFinancialQueryResult:
    """Perform a tenant-scoped, fail-closed lookup and adapt its evidence."""

    scope, scope_policy = _query_scope(query)
    expected_period_type = "INSTANT" if period_semantics == "point_in_time" else "DURATION"
    trace: dict[str, Any] = {
        "route": "STRUCTURED_FINANCIAL_FACT",
        "raw_query": query,
        "resolved_company": company,
        "resolved_metric": canonical_metric,
        "fiscal_year": fiscal_year,
        "period_type": expected_period_type,
        "scope_policy": scope_policy,
        "scope": scope,
        "structured_lookup_status": StructuredLookupStatus.NOT_FOUND.value,
        "fact_id": None,
        "document_id": None,
        "fallback_reason": None,
        "citation_status": "NOT_CHECKED",
        "final_route": None,
        "vector_calls": 0,
        "bm25_calls": 0,
        "rerank_calls": 0,
    }

    if not canonical_metric:
        trace.update(
            structured_lookup_status=StructuredLookupStatus.UNSUPPORTED_METRIC.value,
            fallback_reason="query_metric_has_no_safe_registry_mapping",
            final_route="STRUCTURED_SAFE_FAILURE",
        )
        return StructuredFinancialQueryResult(
            StructuredLookupStatus.UNSUPPORTED_METRIC,
            trace,
            terminal=True,
        )

    if tenant_id <= 0 or not company or not fiscal_year:
        trace.update(
            structured_lookup_status=StructuredLookupStatus.UNSUPPORTED_QUERY.value,
            fallback_reason="explicit_tenant_company_or_period_missing",
            final_route="HYBRID_RAG",
        )
        return StructuredFinancialQueryResult(StructuredLookupStatus.UNSUPPORTED_QUERY, trace)

    try:
        session = session_factory()
    except SQLAlchemyError as exc:
        logger.warning("Structured financial fact store unavailable: %s", type(exc).__name__)
        trace.update(
            structured_lookup_status=StructuredLookupStatus.NOT_FOUND.value,
            fallback_reason="structured_fact_store_unavailable",
            final_route="HYBRID_RAG",
        )
        return StructuredFinancialQueryResult(StructuredLookupStatus.NOT_FOUND, trace)
    try:
        repository = SQLFinancialFactRepository(session, tenant_id=tenant_id)

        def candidates_for(selected_scope: str) -> tuple[FinancialFact, ...]:
            facts = repository.find(
                company=company,
                metric=canonical_metric,
                fiscal_year=fiscal_year,
                period_type=expected_period_type,
                scope=selected_scope,
            )
            if period_semantics == "duration":
                facts = tuple(fact for fact in facts if _is_full_fiscal_duration(fact))
            else:
                facts = tuple(
                    fact
                    for fact in facts
                    if fact.period_type.upper() == "INSTANT" and fact.period_end
                )
            wanted_company = canonical_company(company)
            return tuple(
                fact
                for fact in facts
                if canonical_company(fact.company_id or fact.company) == wanted_company
            )

        facts = candidates_for(scope)
        conflicts = tuple(
            conflict
            for conflict in repository.find_conflicts()
            if conflict.identity[1] == canonical_company(company)
            and conflict.identity[3] == canonical_metric
            and conflict.identity[5] == scope
            and str(fiscal_year) in conflict.identity[6]
            and conflict.identity[6].upper().startswith(f"{expected_period_type}:")
        )
        if conflicts:
            trace.update(
                structured_lookup_status=StructuredLookupStatus.CONFLICT.value,
                fallback_reason="persisted_fact_conflict",
                final_route="STRUCTURED_SAFE_FAILURE",
            )
            return StructuredFinancialQueryResult(StructuredLookupStatus.CONFLICT, trace, terminal=True)

        if len(facts) > 1:
            trace.update(
                structured_lookup_status=StructuredLookupStatus.AMBIGUOUS.value,
                fallback_reason="multiple_matching_facts_or_document_versions",
                final_route="STRUCTURED_CLARIFICATION",
            )
            return StructuredFinancialQueryResult(StructuredLookupStatus.AMBIGUOUS, trace, terminal=True)

        if not facts and scope == "CONSOLIDATED":
            parent_candidates = candidates_for("PARENT_COMPANY")
            if parent_candidates:
                trace.update(
                    structured_lookup_status=StructuredLookupStatus.NOT_FOUND.value,
                    fallback_reason="consolidated_scope_missing_parent_only_exists",
                    final_route="STRUCTURED_SAFE_FAILURE",
                )
                return StructuredFinancialQueryResult(
                    StructuredLookupStatus.NOT_FOUND,
                    trace,
                    answer=(
                        "当前只找到母公司口径数据，未找到合并口径；为避免把母公司数据误作公司整体数据，暂不提供数值。"
                        if response_language == "zh-CN"
                        or (response_language is None and re.search(r"[\u3400-\u9fff]", query))
                        else (
                            "Only parent-company figures were found; no consolidated fact is available, "
                            "so no company-wide value is reported."
                        )
                    ),
                    terminal=True,
                )

        if not facts:
            trace.update(
                structured_lookup_status=StructuredLookupStatus.NOT_FOUND.value,
                fallback_reason="no_matching_persisted_fact",
                final_route="HYBRID_RAG",
            )
            return StructuredFinancialQueryResult(StructuredLookupStatus.NOT_FOUND, trace)

        fact = facts[0]
        document = session.get(Document, int(fact.document_id or 0))
        if document is None or document.tenant_id != tenant_id:
            trace.update(
                structured_lookup_status=StructuredLookupStatus.NOT_FOUND.value,
                fallback_reason="fact_document_tenant_scope_validation_failed",
                final_route="STRUCTURED_SAFE_FAILURE",
            )
            return StructuredFinancialQueryResult(
                StructuredLookupStatus.NOT_FOUND, trace, terminal=True
            )
        if (
            fact.mapping_status not in {"EXACT", "SUPPORTED"}
            or fact.row_verification_status != "VERIFIED"
            or not _fact_matches_request(
                fact,
                document,
                company=company,
                metric=canonical_metric,
                fiscal_year=fiscal_year,
                period_type=expected_period_type,
                scope=scope,
            )
        ):
            trace.update(
                structured_lookup_status=StructuredLookupStatus.UNSUPPORTED_METRIC.value,
                fallback_reason="stored_fact_failed_company_period_scope_or_metric_validation",
                final_route="STRUCTURED_SAFE_FAILURE",
            )
            return StructuredFinancialQueryResult(
                StructuredLookupStatus.UNSUPPORTED_METRIC, trace, terminal=True
            )

        evidence = _source_evidence(fact, document)
        if evidence is None:
            trace.update(
                structured_lookup_status=StructuredLookupStatus.NOT_FOUND.value,
                fallback_reason="citation_provenance_incomplete",
                final_route="STRUCTURED_SAFE_FAILURE",
            )
            return StructuredFinancialQueryResult(StructuredLookupStatus.NOT_FOUND, trace, terminal=True)

        trace.update(
            structured_lookup_status=StructuredLookupStatus.FOUND.value,
            fact_id=fact.fact_id,
            document_id=fact.document_id,
            citation_status="VALIDATED",
            final_route="STRUCTURED_FINANCIAL_FACT",
            financial_presentation={
                "schema_version": "financial-presentation.v1",
                "fact_id": fact.fact_id,
                "canonical_metric": fact.metric_id,
                "company": fact.company,
                "scope": fact.scope,
                "period_type": fact.period_type,
                "period_start": fact.period_start,
                "period_end": fact.period_end,
                "exact_value": str(fact.normalized_value),
                "currency": fact.currency,
                "unit": fact.unit,
                "document_id": fact.document_id,
                "document_version": document.content_sha256,
                "page": fact.page,
                "citation_rank": 1,
                "rendered": {
                    "zh-CN": _render_answer(fact, response_language="zh-CN"),
                    "en": _render_answer(fact, response_language="en"),
                },
            },
        )
        return StructuredFinancialQueryResult(
            StructuredLookupStatus.FOUND,
            trace,
            answer=_render_answer(fact, response_language=response_language),
            evidence=(evidence,),
            terminal=True,
        )
    except SQLAlchemyError as exc:
        session.rollback()
        logger.warning("Structured financial fact lookup failed: %s", type(exc).__name__)
        trace.update(
            structured_lookup_status=StructuredLookupStatus.NOT_FOUND.value,
            fallback_reason="structured_fact_store_unavailable",
            final_route="HYBRID_RAG",
        )
        return StructuredFinancialQueryResult(StructuredLookupStatus.NOT_FOUND, trace)
    finally:
        session.close()
