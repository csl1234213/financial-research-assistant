"""Provider-free query scope classification for answer budgeting."""

from __future__ import annotations

import re
from enum import StrEnum

from agent.planning.entity_extractor import extract_companies
from retrieval.periods import extract_periods


class QueryScope(StrEnum):
    FACT = "FACT"
    SUMMARY = "SUMMARY"
    COMPARE = "COMPARE"
    ANALYSIS = "ANALYSIS"
    RISK = "RISK"
    GENERAL_CONCEPT = "GENERAL_CONCEPT"


_PRIOR_USER_CONTEXT_MARKER = "\nrelevant prior user request for reference resolution:"


def current_turn_query(question: str) -> str:
    """Return the latest user turn, excluding resolver-only history context."""

    value = str(question or "")
    marker_index = value.casefold().find(_PRIOR_USER_CONTEXT_MARKER)
    if marker_index >= 0:
        value = value[:marker_index]
    return value.strip()


_BUSINESS_DEVELOPMENT_REQUEST = re.compile(
    r"\b(?:major\s+)?business\s+(?:developments?|updates?|initiatives?)\b|"
    r"\b(?:major\s+)?developments?\b|"
    r"主要业务(?:发展|进展|动态)|重大业务(?:发展|进展|动态)|业务(?:发展|进展|动态)情况",
    re.IGNORECASE,
)
_FINANCIAL_SUMMARY_OR_METRIC = re.compile(
    r"\bfinancial\s+(?:performance|results?|condition|position)\b|"
    r"\bperform(?:ed|ance)?\s+financially\b|\bfinancially\b|"
    r"\b(?:revenue|revenues|sales|income|earnings|profit|margin|eps|cash\s+flow)\b|"
    r"财务(?:表现|业绩|状况|情况)|经营(?:表现|业绩|状况)|"
    r"营收|收入|净利润|毛利|利润率|每股收益|现金流",
    re.IGNORECASE,
)
_METRIC_PERFORMANCE_REQUEST = re.compile(
    r"\b(?:revenue|revenues|sales|income|earnings|profit|margin|eps|cash\s+flow)\s+performance\b|"
    r"\bperformance\s+of\s+(?:revenue|sales|income|earnings|profit|margins?)\b|"
    r"(?:营收|收入|销售额|净利润|现金流).{0,4}(?:表现|业绩|情况|趋势)|"
    r"(?:表现|业绩|情况|趋势).{0,4}(?:营收|收入|销售额|净利润|现金流)",
    re.IGNORECASE,
)
_COMPARATIVE_RANKING_REQUEST = re.compile(
    r"\b(?:which|who)\b.{0,100}\b(?:strongest|weakest|highest|lowest|fastest|slowest|best|worst)\b|"
    r"哪(?:一个|一家|家|个).{0,40}(?:最强|最弱|最高|最低|最快|最慢|最好|最差|最大|最小|最显著)|"
    r"(?:谁|哪家).{0,40}(?:增长|表现|势头|动力).{0,20}最(?:强|快|好|高|显著)",
    re.IGNORECASE,
)
_CONTEXTUAL_MARGIN_REQUEST = re.compile(
    r"\b(?:it|they|that|those)\b.{0,45}\b(?:gross|operating|profit)?\s*margins?\b|"
    r"\b(?:gross|operating|profit)?\s*margins?\b.{0,45}\b(?:it|they|that|those)\b|"
    r"(?:它|其|这些|那些).{0,20}(?:毛利率|利润率|营业利润率|经营利润率)|"
    r"(?:毛利率|利润率|营业利润率|经营利润率).{0,20}(?:它|其|这些|那些)",
    re.IGNORECASE,
)


def is_nonfinancial_business_development_summary(question: str) -> bool:
    """Detect narrative business-update summaries, not financial summaries."""

    query = current_turn_query(question)
    return bool(
        _BUSINESS_DEVELOPMENT_REQUEST.search(query)
        and not _FINANCIAL_SUMMARY_OR_METRIC.search(query)
    )


# These requested statistics are not part of the structured filing fact
# ledger. Keep them distinct from adjacent facts (e.g. hires vs. headcount,
# market share vs. vehicle deliveries) and ensure they are still routed as
# evidence-seeking questions rather than definitions.
_SPECIFIC_FINANCIAL_FACT = (
    "price target", "target price", "expected stock price", "stock price forecast",
    "stock price prediction", "future stock price", "stock price", "share price",
    "market share", "gross hires", "hires", "employees hired",
    "股价目标", "目标股价", "目标价", "预期股价", "股价预测", "预测股价", "未来股价",
    "股价", "股票价格", "市场份额", "市场占有率", "招聘人数", "招聘总人数", "新招聘",
)


def classify_query_scope(question: str) -> QueryScope:
    """Classify requested answer breadth without an LLM or network call."""

    query = current_turn_query(question).casefold()
    # The runtime may append a prior user turn so company/period references can
    # be resolved. That context must not override the intent of the latest
    # turn (e.g. an analysis follow-up after a comparison).
    if any(token in query for token in ("compare", "comparison", " versus ", " vs ", "比较", "对比")) or (
        _COMPARATIVE_RANKING_REQUEST.search(query)
        and len(extract_companies(query)) >= 2
    ):
        return QueryScope.COMPARE
    if any(token in query for token in (
        "risk", "risks", "challenge", "constraints", "constraint", "风险", "挑战", "约束", "限制",
    )):
        return QueryScope.RISK
    explicit_summary_request = any(token in query for token in (
        "summarize", "summary", "overview", "financial results", "总结", "概述",
    ))
    if explicit_summary_request:
        return QueryScope.SUMMARY
    if any(token in query for token in (
        "analyze", "analysis", "research", "trend", "what drove",
        "business driver", "business drivers", "growth driver",
        "growth drivers", "reason for growth", "why did", "caused", "driver of",
        "attributable to", "reason for decline", "reason for decrease", "what caused",
        "drivers of growth", "main drivers of", "key drivers of", "primary drivers of",
        "分析", "研究", "趋势", "驱动因素", "增长动力", "为什么增长", "增长原因", "原因是什么",
        "归因", "下降原因", "减少原因", "下滑原因", "变化原因",
    )):
        return QueryScope.ANALYSIS
    has_financial_term = any(token in query for token in (
        "revenue", "revenues", "sales", "net income", "profit", "margin",
        "eps", "cash flow", "营收", "收入", "净利润", "毛利率", "利润率", "现金流",
    ))
    has_margin_term = any(token in query for token in (
        "margin", "margins", "毛利率", "利润率", "营业利润率", "经营利润率",
    ))
    # Short follow-ups such as “What about its margins?” often omit company and
    # period locally; the runtime resolves those from conversation context.
    # Keep the latest-turn scope metric-focused instead of broadening it merely
    # because the Chinese phrasing includes “performance”.
    if has_margin_term and _CONTEXTUAL_MARGIN_REQUEST.search(query):
        return QueryScope.FACT
    has_scoped_subject = bool(extract_companies(query) or extract_periods(query))
    # A specific metric keeps its fact scope even when the question uses a
    # broad predicate such as "how did revenue perform?". Explicit summary
    # commands still take precedence; vague company-level performance remains
    # a summary request.
    if (
        has_financial_term
        and has_scoped_subject
        and not _METRIC_PERFORMANCE_REQUEST.search(query)
    ):
        return QueryScope.FACT
    if any(token in query for token in (
        "summarize", "summary", "overview", "performance", "perform financially",
        "financial results", "financially", "how did", "what happened to", "how is", "how are",
        "总结", "概述", "财务表现", "业务表现",
        "经营表现", "表现如何", "表现", "怎么样", "怎样", "咋样", "业绩",
    )):
        return QueryScope.SUMMARY
    if any(token in query for token in _SPECIFIC_FINANCIAL_FACT):
        return QueryScope.FACT
    # "What is gross margin?" and "What is an iPhone?" are definitions,
    # while "What is Apple's gross margin?" / "... in Q2?" requests evidence.
    # Do not let the generic interrogative prefix hide a company- or
    # period-scoped financial fact request.
    if has_financial_term and (extract_companies(query) or extract_periods(query)):
        return QueryScope.FACT
    if any(token in query for token in (
        "what is", "what are", "explain", "define", "什么是", "什么叫", "解释", "说明",
    )):
        return QueryScope.GENERAL_CONCEPT
    return QueryScope.FACT
