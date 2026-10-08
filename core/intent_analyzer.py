import re

from agent.planning.entity_extractor import extract_companies as _extract_company_entities
from core.financial_metric_registry import (
    FINANCIAL_METRIC_REGISTRY,
    MetricMappingStatus,
    extract_explicit_fiscal_year,
)

# Financial/research keywords that indicate a query is research-oriented
# rather than a simple chat. Without these, the query is DIRECT_CHAT.
_RESEARCH_SIGNALS = [
    "revenue",
    "profit",
    "margin",
    "ebitda",
    "earnings",
    "eps",
    "balance sheet",
    "income statement",
    "cash flow",
    "market cap",
    "dividend",
    "risk",
    "growth",
    "trend",
    "forecast",
    "outlook",
    "strategy",
    "analysis",
    "analyze",
    "research",
    "financial",
    "investment",
    "sector",
    "industry",
    "market",
    "stock",
    "price",
    "economy",
    "economic",
    "interest rate",
    "inflation",
    "gdp",
    "营收",
    "利润",
    "净利润",
    "收入",
    "营收",
    "直销",
    "批发代理",
    "国内",
    "国外",
    "渠道",
    "同比",
    "环比",
    "审计",
    "会计师事务所",
    "审计意见",
    "财务报表",
    "毛利率",
    "现金流",
    "股息",
    "市盈率",
    "分析",
    "研究",
    "风险",
    "增长",
    "趋势",
    "投资",
    "市场",
    "行业",
    "财务",
    "经济",
]

_GENERAL_CONCEPT_PREFIX = re.compile(
    r"^(?:please\s+)?(?:(?:what is\b)|what does\b.*\bmean\b|explain\b|define\b|"
    r"describe the difference\b)"
    r"|^(?:请)?(?:什么是|什么叫|解释|说明|简单解释|用简单|简单说)"
)
_SOURCE_REFERENCE = re.compile(
    r"\b(?:reports?|filings?|documents?|uploaded|10-[kq])\b|财报|财务报告|年报|季报|上传|文档"
)


class IntentAnalyzer:
    def analyze(self, query: str, company_context: str | None = None):
        query_lower = query.lower()

        # -------------------------
        # 1. Compare Intent
        # -------------------------
        compare_keywords = ["vs", "compare", "对比", "比较", "versus", "和.*哪个", "与.*哪个"]
        is_compare = any(kw in query_lower if ".*" not in kw else re.search(kw, query_lower) for kw in compare_keywords)

        if is_compare:
            companies = self._extract_companies(query)
            return {"intent": "COMPARE_COMPANIES", "companies": companies, "document_ids": None}

        # -------------------------
        # 2. Single Company Intent
        # -------------------------
        companies = self._extract_companies(query)

        if len(companies) == 1:
            structured = self._structured_fact_intent(query)
            if structured is not None:
                return {
                    "intent": "FINANCIAL_FACT_QUERY",
                    "companies": companies,
                    "document_ids": None,
                    **structured,
                }
            unsupported_metric = self._unsupported_metric_intent(query)
            if unsupported_metric is not None:
                return {
                    "intent": "FINANCIAL_FACT_QUERY",
                    "companies": companies,
                    "document_ids": None,
                    **unsupported_metric,
                }
            return {"intent": "SINGLE_COMPANY", "companies": companies, "document_ids": None}

        # -------------------------
        # 3. Multiple companies without compare keyword
        # -------------------------
        if len(companies) > 1:
            return {"intent": "UNKNOWN", "companies": companies, "document_ids": None}

        # A provider/API-supplied issuer is part of the user query contract.
        # It should route a financial question to that issuer's evidence, but
        # must not turn a genuine definition into RAG (e.g. “什么叫毛利率”).
        if company_context:
            structured = self._structured_fact_intent(query)
            if structured is not None:
                return {
                    "intent": "FINANCIAL_FACT_QUERY",
                    "companies": [company_context],
                    "document_ids": None,
                    **structured,
                }
            unsupported_metric = self._unsupported_metric_intent(query)
            if unsupported_metric is not None:
                return {
                    "intent": "FINANCIAL_FACT_QUERY",
                    "companies": [company_context],
                    "document_ids": None,
                    **unsupported_metric,
                }
            if not self._is_direct_chat(query_lower):
                return {
                    "intent": "SINGLE_COMPANY",
                    "companies": [company_context],
                    "document_ids": None,
                }

        # -------------------------
        # 4. No companies — direct chat vs research
        # -------------------------
        if self._is_direct_chat(query_lower):
            return {"intent": "DIRECT_CHAT", "companies": None, "document_ids": None}

        return {"intent": "GLOBAL_RESEARCH", "companies": None, "document_ids": None}

    def _is_direct_chat(self, query_lower: str) -> bool:
        # A definition/explanation without a named company or source should
        # be answered conversationally, even when it contains a financial
        # term such as "gross margin"/"毛利率".
        if (
            _GENERAL_CONCEPT_PREFIX.search(query_lower.strip())
            and not self._extract_companies(query_lower)
            and not _SOURCE_REFERENCE.search(query_lower)
        ):
            return True
        for signal in _RESEARCH_SIGNALS:
            if signal in query_lower:
                return False
        return True

    @staticmethod
    def _structured_fact_intent(query: str) -> dict[str, str] | None:
        """Recognize only one declared metric plus one explicit fiscal year."""

        normalized = query.casefold().strip()
        if _GENERAL_CONCEPT_PREFIX.search(normalized) and not _SOURCE_REFERENCE.search(normalized):
            return None
        year = extract_explicit_fiscal_year(query)
        if year is None:
            return None
        metric = FINANCIAL_METRIC_REGISTRY.resolve_query_metric(query)
        if metric.status == MetricMappingStatus.AMBIGUOUS:
            # 多指标不能静默选一个，也不能进入未经授权的模型回退。
            return {
                "canonical_metric": "",
                "fiscal_year": year,
                "period_semantics": "",
                "matched_metric_alias": "",
                "metric_resolution_status": "AMBIGUOUS",
            }
        if metric.status not in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}:
            return None
        if metric.canonical_metric is None or metric.period_semantics not in {"point_in_time", "duration"}:
            return None
        return {
            "canonical_metric": metric.canonical_metric,
            "fiscal_year": year,
            "period_semantics": metric.period_semantics,
            "matched_metric_alias": metric.matched_alias or "",
        }

    @staticmethod
    def _unsupported_metric_intent(query: str) -> dict[str, str] | None:
        """Block known ambiguous debt terms from being recast as liabilities."""

        if not re.search(r"(?:总债务|债务|有息负债|total\s+debt|\bdebt\b|\bborrowings\b)", query, re.I):
            return None
        metric = FINANCIAL_METRIC_REGISTRY.resolve_query_metric(query)
        if metric.status in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}:
            return None
        return {
            "canonical_metric": "",
            "fiscal_year": extract_explicit_fiscal_year(query) or "",
            "period_semantics": "",
            "matched_metric_alias": "",
            "query_metric_status": "UNSUPPORTED_METRIC",
        }

    def _extract_companies(self, query: str):
        # Keep the runtime intent router aligned with the planner's canonical
        # aliases; separate maps caused implicit bilingual issuer descriptions
        # (for example, "iPhone maker") to fall through to direct chat.
        return _extract_company_entities(query)
