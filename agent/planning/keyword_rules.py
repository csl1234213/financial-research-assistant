# ============================================================
# Keyword Rules — Task Classification Keywords
# ============================================================
# All keyword lists are centralized here so that:
# 1. TaskAnalyzer stays clean (no keyword clutter)
# 2. Adding a new keyword never touches Analyzer code
# 3. Keywords can be reviewed and tuned independently
# ============================================================

import re

from .entity_extractor import extract_companies
from .task_enums import TaskType

# =========================
# Keyword Lists
# =========================

OCR_KEYWORDS = [
    "ocr",
    "scan",
    "扫描",
    "识别",
]

IMAGE_ANALYSIS_KEYWORDS = [
    "image",
    "photo",
    "picture",
    "chart",
    "图片",
    "截图",
    "图表",
]

COMPARISON_KEYWORDS = [
    "compare",
    "comparison",
    "vs",
    "versus",
    "比较",
    "对比",
]

DOCUMENT_QA_KEYWORDS = [
    "10-k",
    "10-q",
    "annual report",
    "annual reports",
    "financial report",
    "financial statement",
    "financial performance",
    "财务表现",
    "filing",
    "财报",
    "年报",
    "季报",
    "财务报告",
    "risk factor",
    "risk factors",
    "risk",
    "revenue",
    "profit",
    "margin",
    "ebitda",
    "balance sheet",
    "income statement",
    "cash flow",
    "cap",
    "market cap",
    "dividend",
    "earnings",
    "eps",
    "p/e",
    "pe ratio",
    "增长率",
    "营收",
    "收入",
    "主营业务收入",
    "直销",
    "批发代理",
    "国内",
    "国外",
    "地区",
    "渠道",
    "审计",
    "审计意见",
    "会计师事务所",
    "财务报表",
    "利润",
    "净利润",
    "毛利率",
    "净利率",
    "现金流",
    "股息",
    "市盈率",
    "市净率",
]

RESEARCH_KEYWORDS = [
    "research",
    "analyze",
    "analysis",
    "研究",
    "深入",
    "分析",
    "deep dive",
    "deep research",
    "investigate",
    "调查",
    "调研",
    "评估",
    "assessment",
    "展望",
    "outlook",
    "forecast",
    "预测",
    "trend",
    "趋势",
    "strategy",
    "战略",
    "market",
    "industry",
    "行业",
    "sector",
]

# =========================
# Priority-ordered lookup
# =========================
# Higher priority rules are checked first to avoid
# misclassification (e.g. "analyze this image" → RESEARCH
# would be wrong; it should be IMAGE_ANALYSIS).

_PRIORITY_ORDER = [
    (TaskType.OCR, OCR_KEYWORDS),
    (TaskType.IMAGE_ANALYSIS, IMAGE_ANALYSIS_KEYWORDS),
    (TaskType.COMPARISON, COMPARISON_KEYWORDS),
    (TaskType.DOCUMENT_QA, DOCUMENT_QA_KEYWORDS),
    (TaskType.RESEARCH, RESEARCH_KEYWORDS),
]

_CONCEPT_PREFIX = re.compile(
    r"^(?:please\s+)?(?:(?:what (?:is|are)\b)|what does\b.*\bmean\b|explain\b|define\b|describe the difference\b)"
    r"|^(?:请)?(?:什么是|什么叫|解释|说明|简单解释|用简单|简单说)"
)
_SOURCE_REFERENCE = re.compile(
    r"\b(?:reports?|filings?|documents?|uploaded|10-[kq])\b|财报|财务报告|年报|季报|上传|文档"
)
_PERIOD_REFERENCE = re.compile(
    r"\bq[1-4]\b|\b(?:fy|fiscal)\s*\d{2,4}\b|\b(?:first|second|third|fourth)\s+quarter\b"
    r"|第[一二三四1-4]季度|季度|年度"
)
_BUSINESS_PERFORMANCE = re.compile(
    r"\b(?:business|performance|growth|drivers?|segments?|financially|datacentre|datacenter)\b"
    r"|data[ -]cent(?:er|re)|业务|表现|业绩|增长|动力|驱动|发展|收入|营收|直销|批发代理"
    r"|国内|国外|地区|渠道|审计|会计师事务所|审计意见|财务报表"
)


def is_company_performance_question(question_lower: str) -> bool:
    return bool(_BUSINESS_PERFORMANCE.search(question_lower))


def classify_by_keyword(question_lower: str) -> tuple[TaskType, str | None]:
    # A definition is not document QA merely because it mentions a financial
    # metric. Explicit companies or source references still require evidence.
    if (
        _CONCEPT_PREFIX.search(question_lower.strip())
        and not extract_companies(question_lower)
        and not _SOURCE_REFERENCE.search(question_lower)
        and not _PERIOD_REFERENCE.search(question_lower)
    ):
        return TaskType.CHAT, "general concept"
    for task_type, keywords in _PRIORITY_ORDER:
        for kw in keywords:
            if kw in question_lower:
                return task_type, kw
    return TaskType.CHAT, None
