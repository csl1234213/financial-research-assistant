"""Bounded structured-fact shadow evaluation; no provider, database or answer writes."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, replace
from datetime import date
from types import SimpleNamespace
from typing import Mapping, Sequence

from agent.reasoning_models import Evidence
from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from core.answer_synthesis_contracts import AnswerType, adapt_retrieval_result
from core.answer_synthesis_planner import DeterministicAnswerPlanner
from core.answer_synthesis_renderer import RestrictedOutputVerifier
from core.answer_synthesis_workflow import BoundedSynthesisWorkflow
from core.fact_ledger import canonical_company
from retrieval.adaptive_adapters import FinancialFactEvidenceAdapter
from retrieval.adaptive_contract import RetrievalRequest

SHADOW_FLAG = "P2_2_STRUCTURED_SYNTHESIS_SHADOW"


@dataclass(frozen=True)
class ShadowOutcome:
    status: str
    reason: str
    query_sha256: str | None = None
    failure_codes: tuple[str, ...] = ()


def evaluate_structured_shadow(
    *,
    query: str,
    tenant_id: int,
    locale: str | None,
    intent: Mapping,
    evidence: Sequence[Evidence],
    enabled: bool | None = None,
) -> ShadowOutcome:
    """Consume the existing result, never retrieve again or change primary answer/citations."""
    active = os.environ.get(SHADOW_FLAG) == "1" if enabled is None else enabled is True
    if not active:
        return ShadowOutcome("DISABLED", "feature_flag_off")
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if type(tenant_id) is not int or tenant_id <= 0 or locale not in {"zh-CN", "en"}:
        return ShadowOutcome("SKIPPED", "identity_or_locale_missing", digest)
    if len(evidence) != 1 or len(query) > 20000:
        return ShadowOutcome("SKIPPED", "bounded_exact_fact_required", digest)
    try:
        companies = intent.get("companies", ())
        trace = intent.get("structured_fact_lookup", {})
        metric, year = intent.get("canonical_metric"), str(intent.get("fiscal_year", ""))
        if (
            intent.get("intent") != "FINANCIAL_FACT_QUERY"
            or len(companies) != 1
            or trace.get("structured_lookup_status") != "FOUND"
            or trace.get("citation_status") != "VALIDATED"
        ):
            return ShadowOutcome("SKIPPED", "validated_query_semantics_required", digest)
        if not metric or len(year) != 4 or not year.isascii() or not year.isdigit():
            return ShadowOutcome("SKIPPED", "explicit_metric_and_year_required", digest)
        scope = trace.get("scope")
        if scope not in {"CONSOLIDATED", "PARENT_COMPANY"}:
            return ShadowOutcome("SKIPPED", "scope_policy_missing", digest)
        expected_kind = {"point_in_time": "INSTANT", "duration": "DURATION"}.get(intent.get("period_semantics"))
        if expected_kind is None:
            return ShadowOutcome("SKIPPED", "period_semantics_missing", digest)
        metadata = evidence[0].metadata
        if (
            canonical_company(evidence[0].company) != canonical_company(companies[0])
            or str(metadata.get("fiscal_year")) != year
            or metadata.get("period_type") != expected_kind
        ):
            return ShadowOutcome("REJECTED", "company_or_period_mismatch", digest)
        if expected_kind == "DURATION":
            days = (date.fromisoformat(metadata["period_end"]) - date.fromisoformat(metadata["period_start"])).days
            if not 300 <= days <= 400:
                return ShadowOutcome("REJECTED", "annual_duration_mismatch", digest)
        elif str(metadata.get("period_end", ""))[:4] != year:
            return ShadowOutcome("REJECTED", "instant_year_mismatch", digest)
        request = RetrievalRequest(
            ScopedRequest(query=query, tenant_id=tenant_id),
            metric=metric,
            fiscal_year=year,
            scope=scope,
            period=expected_kind,
        )
        result = FinancialFactEvidenceAdapter(
            lambda _: SimpleNamespace(status="FOUND", evidence=tuple(evidence), trace={})
        ).retrieve(request)
        source = adapt_retrieval_result(
            result, query=query, tenant_id=tenant_id, answer_type=AnswerType.FACT, locale=locale
        )
        # 年度/类型已独立与 intent 对齐后才绑定完整来源期别；不推断财政年度起止日。
        source = replace(
            source,
            required_dimensions={
                "company": evidence[0].company,
                "metric": metric,
                "scope": scope,
                "period": result.evidence[0].period,
            },
        )
        plan = DeterministicAnswerPlanner().plan(source)
        rendered = BoundedSynthesisWorkflow().run(source, plan).answer
        checked = RestrictedOutputVerifier().verify(source, plan, rendered)
        return ShadowOutcome(
            "PASS" if checked.passed else "REJECTED",
            "restricted_template_only",
            digest,
            tuple(item.value for item in checked.failures),
        )
    except Exception as exc:
        # 不输出财报正文、用户问题、异常消息或原始 Provider 内容。
        return ShadowOutcome("REJECTED", "adapter_error:" + type(exc).__name__, digest)
