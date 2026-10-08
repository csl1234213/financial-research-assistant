"""Bind existing precise query semantics to admitted real financial artifacts."""

import re
from datetime import date

from core.answer_synthesis_contracts import AnswerType, SynthesisInput
from core.fact_ledger import canonical_company
from core.financial_metric_registry import FINANCIAL_METRIC_REGISTRY
from core.intent_analyzer import IntentAnalyzer
from core.structured_financial_query import _query_scope
from retrieval.ingestion_fact_evidence import ReadyFinancialFactEvidence
from services.ready_narrative_synthesis_source import narrative_answer_type


class ReadyFactSynthesisSource:
    """Precise FACT branch; other answer types may use an explicit server fallback.

    No unknown query is silently forced into a financial fact or sent to an LLM.
    The default scope policy is the same disclosed consolidated policy as P1.7.
    """
    def __init__(self, ledger, *, fallback_resolver=None):
        self.facts = ReadyFinancialFactEvidence(ledger)
        self.fallback = fallback_resolver

    def __call__(self, *, question, locale, tenant_id, user_id, ingestion_job_id, manifest):
        # Answer shape is resolved before precise-metric routing. Never catch
        # a fact read/authorization failure and replace it with narrative prose.
        if self.fallback is not None and narrative_answer_type(question) is not None:
            return self.fallback(question=question, locale=locale, tenant_id=tenant_id,
                user_id=user_id, ingestion_job_id=ingestion_job_id, manifest=manifest)
        intent = IntentAnalyzer().analyze(question)
        companies = intent.get("companies") or []
        years = tuple(dict.fromkeys(re.findall(r"(?<!\d)(20\d{2})(?!\d)", question)))
        comparison = bool(re.search(r"比较|对比|compare|comparison", question, re.I))
        trend = bool(re.search(r"趋势|trend", question, re.I))
        multi_year = len(years) == 2 and (comparison or trend)
        if multi_year and abs(int(years[0]) - int(years[1])) != 1:
            raise ValueError("NON_ADJACENT_ANNUAL_TREND_NOT_SUPPORTED")
        if multi_year and re.search(r"季度|半年|上半年|下半年|Q[1-4]|quarter|half.year|月", question, re.I):
            raise ValueError("NON_ANNUAL_COMPARISON_NOT_SUPPORTED")
        if (intent.get("intent") != "FINANCIAL_FACT_QUERY" and not multi_year) or len(companies) != 1:
            if self.fallback is not None:
                return self.fallback(question=question, locale=locale, tenant_id=tenant_id,
                    user_id=user_id, ingestion_job_id=ingestion_job_id, manifest=manifest)
            raise ValueError("QUERY_STRATEGY_NOT_AVAILABLE")
        if intent.get("metric_resolution_status") == "AMBIGUOUS":
            return SynthesisInput(question, tenant_id, AnswerType.AMBIGUOUS, locale, (),
                                  "PARTIAL", "FACT", {})
        if multi_year:
            resolution = FINANCIAL_METRIC_REGISTRY.resolve_query_metric(question)
            if resolution.canonical_metric is None:
                raise ValueError("EXPLICIT_SINGLE_METRIC_REQUIRED")
            metric = resolution.canonical_metric
            definition = FINANCIAL_METRIC_REGISTRY.get(metric)
            period_semantics = definition.period_semantics
        else:
            metric, year = intent.get("canonical_metric"), intent.get("fiscal_year")
            years = (year,)
            period_semantics = intent.get("period_semantics")
        scope, _ = _query_scope(question)
        parent_requested = bool(re.search(r"母公司|单体报表|parent\s+company|standalone", question, re.I))
        consolidated_requested = bool(re.search(r"合并|consolidated", question, re.I))
        scopes = ("CONSOLIDATED", "PARENT_COMPANY") if parent_requested and consolidated_requested else (scope,)
        if multi_year and len(scopes) != 1:
            raise ValueError("MULTI_PERIOD_MULTI_SCOPE_NOT_COMPARABLE")
        evidence = tuple(item for requested_year in years for requested_scope in scopes for item in self.facts.retrieve(
            ingestion_job_id, tenant_id=tenant_id, user_id=user_id,
            metric=metric, scope=requested_scope, fiscal_year=requested_year))
        expected_kind = {"point_in_time": "INSTANT", "duration": "DURATION"}.get(period_semantics)
        eligible = []
        for item in evidence:
            data = item.payload
            if (canonical_company(data["company"]) != canonical_company(companies[0])
                    or data["period"]["period_type"] != expected_kind):
                continue
            if expected_kind == "DURATION":
                period = data["period"]
                if not period["period_start"] or not 300 <= (
                    date.fromisoformat(period["period_end"]) - date.fromisoformat(period["period_start"])
                ).days <= 400:
                    continue
            eligible.append(item)
        expected_keys = {(year, selected_scope) for year in years for selected_scope in scopes}
        actual_keys = {(item.payload["period"]["fiscal_year"], item.payload["scope"]) for item in eligible}
        if len(eligible) != len(expected_keys) or actual_keys != expected_keys:
            raise ValueError("UNIQUE_ELIGIBLE_FINANCIAL_OBSERVATION_REQUIRED")
        if any(item.document_id != str(manifest["document_id"])
               or item.payload["provenance"]["content_sha256"] != manifest["source_sha256"] for item in eligible):
            raise ValueError("READY_FACT_SOURCE_CHANGED")
        data = eligible[0].payload
        required = {"company": data["company"], "metric": metric,
                    "period": data["period"], "statement": data["statement"],
                    "currency": data["provenance"]["currency"], "unit": data["provenance"]["unit"]}
        if len(scopes) == 1:
            required["scope"] = scope
        if multi_year:
            required.pop("period")
        # Multiple explicitly requested scopes remain separate observations.
        # This enumerates factual amounts; it performs no cross-scope arithmetic.
        # Same-company cross-period comparison is a temporal trend. COMPARISON
        # is reserved by the audited arithmetic layer for aligned-period companies.
        answer_type = AnswerType.TREND if multi_year else AnswerType.FACT
        return SynthesisInput(question, tenant_id, answer_type, locale, tuple(eligible), "FOUND", "FACT", {},
                              required_dimensions=required)
