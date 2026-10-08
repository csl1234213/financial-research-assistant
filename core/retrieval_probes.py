"""Deterministic bounded retrieval probes shared by runtime and offline audits."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from agent.planning.entity_extractor import extract_companies
from agent.reasoning_models import Evidence
from core.fact_ledger import FactLedger, canonical_company, canonical_metric_id, metric_aliases
from core.financial_grounding import canonical_metrics
from core.growth_driver_evidence import (
    is_explicit_growth_driver_question,
    is_growth_narrative_question,
)
from core.query_scope import QueryScope, is_nonfinancial_business_development_summary
from retrieval.periods import extract_periods

_BROAD_FINANCIAL_SUMMARY = re.compile(
    r"\bfinancial\s+(?:performance|results?|condition|position|summary|overview)\b|"
    r"\b(?:revenue|revenues|sales)\s+performance\b|"
    r"\bperform(?:ed|ance)?\s+financially\b|\bfinancially\b|"
    r"(?:营收|收入|销售额).{0,4}(?:表现|业绩|情况|趋势)|"
    r"财务(?:表现|业绩|状况|情况|摘要|概况)|"
    r"经营(?:表现|业绩|状况|情况)|经营.{0,4}(?:怎么样|如何|怎样)|业绩",
    re.IGNORECASE,
)
_HEADLINE_SUMMARY_METRICS = (
    "revenue",
    "automotive_revenue",
    "services_revenue",
    "energy_revenue",
    "iphone_revenue",
    "products_revenue",
    "mac_revenue",
    "ipad_revenue",
    "wearables_revenue",
    "products_gross_margin",
    "services_gross_margin",
    "net_income",
    "gross_profit",
    "gross_margin",
    "operating_margin",
    "operating_cash_flow",
    "free_cash_flow",
    "eps",
)
_SEGMENT_OVERVIEW_METRICS = (
    "automotive_revenue",
    "products_revenue",
    "iphone_revenue",
    "mac_revenue",
    "ipad_revenue",
    "wearables_revenue",
    "products_gross_margin",
    "services_gross_margin",
    "services_revenue",
    "data_center_revenue",
    "edge_computing_revenue",
)
_CAUSAL_CHANGE_QUESTION = re.compile(
    r"\b(?:why|cause|causes|reason|reasons|attributable|explain|explains)\b|"
    r"归因|原因|因为什么|为何|为什么|导致",
    re.IGNORECASE,
)


def _company_document_period(
    evidence: Sequence[Evidence], company: str
) -> str | None:
    """Use an observed filing period; never infer one from a filename."""

    periods: list[str] = []
    seen: set[tuple[str, str]] = set()
    wanted_company = canonical_company(company)
    for item in evidence:
        metadata = dict(item.metadata or {})
        item_company = canonical_company(str(item.company or metadata.get("company", "")))
        if item_company != wanted_company:
            continue
        period = str(
            metadata.get("document_reporting_period") or metadata.get("quarter") or ""
        ).strip()
        chunk_id = str(metadata.get("chunk_id") or "")
        if period and (chunk_id, period) not in seen:
            periods.append(period)
            seen.add((chunk_id, period))
    if not periods:
        return None
    counts = Counter(periods)
    return max(counts, key=lambda period: (counts[period], period))


def retrieval_probe_queries(
    query: str,
    scope: QueryScope,
    existing_evidence: Sequence[Evidence] = (),
) -> tuple[str, ...]:
    """Return the production's bounded follow-up queries in stable order."""

    text = str(query or "")
    lowered = text.casefold()
    probes: list[str] = []
    companies = extract_companies(text)
    existing_ledger = FactLedger.from_evidence(existing_evidence)
    metric = canonical_metric_id(text)
    if metric and not (scope == QueryScope.COMPARE and len(companies) > 1):
        probes.extend(f"{text} {term}" for term in _metric_probe_terms(metric))
    if scope in {QueryScope.SUMMARY, QueryScope.ANALYSIS, QueryScope.FACT, QueryScope.COMPARE}:
        if any(token in lowered for token in ("performance", "perform financially", "表现", "业绩")):
            probes.append(f"{text} financial summary")
        if (
            not is_nonfinancial_business_development_summary(text)
            and any(token in lowered for token in (
                "segment", "business driver", "business factor", "growth driver",
                "growth factor", "reported performance", "业务", "增长动力",
                "驱动因素"
            ))
        ):
            probes.append(f"{text} segment revenue growth drivers")
    if scope == QueryScope.ANALYSIS and _CAUSAL_CHANGE_QUESTION.search(text):
        # Causal questions about a reported financial change need narrative
        # disclosure as well as the numeric statement row. Reuse observed
        # issuer/period metadata from the first retrieval when the issuer or
        # period was supplied through request context rather than typed in
        # the question; never infer either from a filename.
        probe_companies = list(companies)
        if not probe_companies:
            for item in existing_evidence:
                candidate = str(
                    item.company or (item.metadata or {}).get("company") or ""
                ).strip()
                if candidate and all(
                    canonical_company(candidate) != canonical_company(known)
                    for known in probe_companies
                ):
                    probe_companies.append(candidate)
        year_match = re.search(r"(?<!\d)(20\d{2})(?:\s*年)?", text)
        periods = extract_periods(text)
        period_suffix = (
            f" {periods[0]}" if periods
            else f" {year_match.group(1)}" if year_match
            else ""
        )
        metric_ids = list(dict.fromkeys(canonical_metrics(text)))
        if "cash_flow" in metric_ids and existing_ledger.lookup(
            metric_id="operating_cash_flow"
        ):
            metric_ids = [
                "operating_cash_flow" if metric_id == "cash_flow" else metric_id
                for metric_id in metric_ids
            ]
        for company in probe_companies:
            for metric_id in metric_ids:
                for term in _metric_probe_terms(metric_id)[:2]:
                    probes.append(
                        f"{company} {term} change reason annual report{period_suffix}"
                    )
                if metric_id == "operating_cash_flow":
                    probes.append(
                        f"{company} 经营活动产生的现金流量净额 变化原因 年报{period_suffix}"
                    )
    # Explicit causal questions need issuer-scoped probes.  A whole-query
    # embedding can rank one company's commentary above the other issuers,
    # which makes the final answer look grounded while silently omitting a
    # named company.  Keep this fan-out bounded to the named companies and
    # only activate it for explicit driver/factor intent.
    if is_explicit_growth_driver_question(text) and companies:
        periods = extract_periods(text)
        for company in companies:
            company_period = (
                periods[0]
                if periods
                else _company_document_period(existing_evidence, company)
            )
            period_suffix = f" {company_period}" if company_period else ""
            probes.extend(
                (
                    f"{company} business growth drivers{period_suffix}",
                    f"{company} reported performance drivers{period_suffix}",
                    f"{company} segment revenue growth drivers{period_suffix}",
                )
            )
    if scope == QueryScope.RISK:
        probes.append(f"{text} forward-looking statements risk factors")
    if scope == QueryScope.COMPARE and len(companies) > 1:
        comparison_metrics = list(dict.fromkeys(canonical_metrics(text)))
        if is_growth_narrative_question(text):
            # A ranking question needs comparable issuer-local revenue facts,
            # not only narrative driver passages.  The broad embedding query
            # often returns NVIDIA/Apple commentary and drops the consolidated
            # revenue rows for another issuer.  Add bounded company/period
            # probes for both the headline amount and its reported growth; the
            # ledger and grounding gates still decide whether each fact is
            # authoritative.  Periods come from the observed filing metadata,
            # never from filenames or benchmark IDs.
            for company in companies:
                company_period = (
                    extract_periods(text)[0]
                    if extract_periods(text)
                    else _company_document_period(existing_evidence, company)
                )
                period_suffix = f" {company_period}" if company_period else ""
                probes.extend(
                    (
                        f"{company} total revenues{period_suffix}",
                        f"{company} total net sales{period_suffix}",
                        f"{company} revenue growth{period_suffix}",
                        f"{company} year over year revenue{period_suffix}",
                    )
                )
        segment_overview = bool(
            re.search(
                r"\b(?:business\s+)?segments?\b|\bbusiness\s+lines\b|"
                r"业务分部|业务板块|各业务|分部情况",
                text,
                re.IGNORECASE,
            )
        )
        if segment_overview and not comparison_metrics:
            # Segment-overview turns have no explicit metric token, so the
            # normal comparison probes would otherwise skip issuer-specific
            # rows. Probe each supported segment alias for every named company
            # and let the same coverage-aware selector enforce period/company
            # consistency afterward.
            for company in companies:
                company_period = (
                    extract_periods(text)[0]
                    if extract_periods(text)
                    else _company_document_period(existing_evidence, company)
                )
                period_suffix = f" {company_period}" if company_period else ""
                probes.append(f"{company} segment revenue{period_suffix}")
                for metric_id in _SEGMENT_OVERVIEW_METRICS:
                    probes.extend(
                        f"{company} {term}{period_suffix}"
                        for term in _metric_probe_terms(metric_id)
                    )
            # Broad major-segment comparisons also need consolidated context
            # (revenue, profitability and EPS) so the answer can explain the
            # segment mix without borrowing a number from another issuer.
            overview_with_headlines = bool(
                re.search(
                    r"\b(?:compare|comparison|summari[sz]e|overview|major|main|key)\b|"
                    r"比较|总结|概览|主要|关键",
                    text,
                    re.IGNORECASE,
                )
            )
            if overview_with_headlines:
                headline_metrics = ["revenue", "net_income", "gross_margin", "eps"]
                for company in companies:
                    company_period = (
                        extract_periods(text)[0]
                        if extract_periods(text)
                        else _company_document_period(existing_evidence, company)
                    )
                    period_suffix = f" {company_period}" if company_period else ""
                    for metric_id in headline_metrics:
                        probes.extend(
                            f"{company} {term}{period_suffix}"
                            for term in _metric_probe_terms(metric_id)
                        )
        followup_financial_compare = re.search(
            r"\b(?:analy[sz]e|review|summari[sz]e)\b.{0,100}\b(?:report|filing|financial)\b"
            r"|分析.{0,24}(?:财报|报告)|报告分析",
            text,
            re.IGNORECASE,
        )
        if not comparison_metrics and (
            re.search(
                r"\bfinancial\s+(?:performance|results?)\b|"
                r"\bperform(?:ed|ance)?\s+financially\b|财务(?:表现|业绩|状况)",
                text,
                re.IGNORECASE,
            )
            or followup_financial_compare
        ):
            # Normalize broad bilingual financial comparisons to the same
            # company-scoped probe terms instead of embedding the whole
            # differently worded sentence. Keep per-company metric probes as
            # well: a single broad summary query can retrieve headline revenue
            # while omitting profitability/period evidence for the other side.
            for company in companies:
                probes.append(f"{company} financial summary")
                periods = extract_periods(text)
                company_period = (
                    periods[0]
                    if periods
                    else _company_document_period(existing_evidence, company)
                )
                period_suffix = f" {company_period}" if company_period else ""
                for metric_id in _HEADLINE_SUMMARY_METRICS:
                    if (
                        company_period
                        and metric_id not in {"net_income", "eps"}
                        and existing_ledger.lookup(
                        company=company,
                        metric_id=metric_id,
                            period=company_period,
                        )
                    ):
                        continue
                    probes.extend(
                        f"{company} {term}{period_suffix}"
                        for term in _metric_probe_terms(metric_id)
                    )
        else:
            if re.search(r"\bmargins?\b|利润率", text, re.IGNORECASE) and not comparison_metrics:
                comparison_metrics = ["gross_margin", "operating_margin"]
            periods = extract_periods(text)
            for company in companies:
                company_period = (
                    periods[0]
                    if periods
                    else _company_document_period(existing_evidence, company)
                )
                period_suffix = f" {company_period}" if company_period else ""
                for metric_id in comparison_metrics:
                    probes.extend(
                        f"{company} {term}{period_suffix}"
                        for term in _metric_probe_terms(metric_id)
                    )
    summary_segment_overview = bool(
        scope == QueryScope.SUMMARY
        and re.search(
            r"\b(?:business\s+)?segments?\b|\bbusiness\s+lines\b|"
            r"业务分部|业务板块|各业务|分部情况",
            text,
            re.IGNORECASE,
        )
        and not canonical_metrics(text)
    )
    if summary_segment_overview and companies:
        # Chinese segment-overview prompts need issuer-scoped probes too;
        # whole-query embeddings can otherwise return segment rows while
        # dropping the consolidated net-income row for the same issuer.
        periods = extract_periods(text)
        for company in companies:
            company_period = (
                periods[0]
                if periods
                else _company_document_period(existing_evidence, company)
            )
            period_suffix = f" {company_period}" if company_period else ""
            for metric_id in (*_SEGMENT_OVERVIEW_METRICS, "revenue", "net_income", "gross_margin", "eps"):
                probes.extend(
                    f"{company} {term}{period_suffix}"
                    for term in _metric_probe_terms(metric_id)
                )

    broad_financial_summary = bool(
        scope == QueryScope.SUMMARY
        and _BROAD_FINANCIAL_SUMMARY.search(text)
    )
    if broad_financial_summary and len(companies) == 1:
        periods = extract_periods(text)
        company_period = (
            periods[0]
            if periods
            else _company_document_period(existing_evidence, companies[0])
        )
        period_suffix = f" {company_period}" if company_period else ""
        for metric_id in _HEADLINE_SUMMARY_METRICS:
            if (
                company_period
                and metric_id not in {"net_income", "eps"}
                and existing_ledger.lookup(
                company=companies[0],
                metric_id=metric_id,
                    period=company_period,
                )
            ):
                continue
            probes.extend(
                f"{companies[0]} {term}{period_suffix}"
                for term in _metric_probe_terms(metric_id)
            )
    elif (
        scope == QueryScope.SUMMARY
        and not is_nonfinancial_business_development_summary(text)
    ):
        probes.extend(
            f"{text} {metric_name}"
            for metric_name in (
                "revenue",
                "net income",
                "gross margin",
                "operating cash flow",
                "earnings per share",
            )
        )
    return tuple(dict.fromkeys(probes))


def retrieval_probe_top_k(question: str, probe_query: str) -> int:
    """Use a deeper bounded pool for normalized company-metric probes.

    Public-filings audits showed that exact period-mapped rows can fall just
    outside the five-result probe window even when the normalized company and
    metric query is correct. Keep broad prose probes shallow; only expand
    company-scoped fact probes where the additional candidates are useful for
    deterministic evidence coverage.
    """

    companies = extract_companies(question)
    if any(probe_query.casefold().startswith(f"{company.casefold()} ") for company in companies):
        return 8
    return 3


def _metric_probe_terms(metric_id: str) -> tuple[str, ...]:
    """Use filing-native cash-flow labels alongside normalized wording."""

    aliases = metric_aliases(metric_id)
    if not aliases:
        return ()
    if metric_id == "operating_cash_flow":
        return tuple(dict.fromkeys((aliases[0], "cash generated by operating activities")))
    if metric_id == "net_income":
        return tuple(dict.fromkeys((aliases[0], "net income attributable to common stockholders")))
    if metric_id == "eps":
        return tuple(dict.fromkeys((aliases[0], "earnings per share")))
    return (aliases[0],)
