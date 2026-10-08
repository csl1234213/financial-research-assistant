# ============================================================
# Entity Extractor — Company & Year Extraction
# ============================================================
# Simple rule-based entity extraction for the first version.
# Later versions can add NER (spaCy / LLM) without changing
# the extractor interface.
# ============================================================

import re

_COMPANY_MAP = {
    "apple": "Apple",
    "iphone maker": "Apple",
    "苹果": "Apple",
    "tesla": "Tesla",
    "ev maker": "Tesla",
    "electric vehicle maker": "Tesla",
    "特斯拉": "Tesla",
    "电动车公司": "Tesla",
    "电动汽车公司": "Tesla",
    "nvidia": "NVIDIA",
    "chip company": "NVIDIA",
    "gpu company": "NVIDIA",
    "gpu maker": "NVIDIA",
    "gpu 的公司": "NVIDIA",
    "gpu的公司": "NVIDIA",
    "gpu 厂商": "NVIDIA",
    "gpu厂商": "NVIDIA",
    "英伟达": "NVIDIA",
    "amd": "AMD",
    "超威": "AMD",
    "microsoft": "Microsoft",
    "微软": "Microsoft",
    "贵州茅台酒股份有限公司": "贵州茅台",
    "贵州茅台": "贵州茅台",
    "kweichow moutai": "贵州茅台",
    "moutai": "贵州茅台",
    "茅台": "贵州茅台",
    "google": "Google",
    "alphabet": "Alphabet",
    "谷歌": "Google",
    "amazon": "Amazon",
    "亚马逊": "Amazon",
    "meta": "Meta",
    "facebook": "Meta",
    "netflix": "Netflix",
    "奈飞": "Netflix",
    "intel": "Intel",
    "英特尔": "Intel",
    "tsmc": "TSMC",
    "台积电": "TSMC",
    "samsung": "Samsung",
    "三星": "Samsung",
    "qualcomm": "Qualcomm",
    "高通": "Qualcomm",
    "broadcom": "Broadcom",
    "博通": "Broadcom",
    "jpmorgan": "JPMorgan",
    "摩根大通": "JPMorgan",
    "berkshire": "Berkshire Hathaway",
    "伯克希尔": "Berkshire Hathaway",
    "visa": "Visa",
    "mastercard": "Mastercard",
    "万事达": "Mastercard",
    "walmart": "Walmart",
    "沃尔玛": "Walmart",
    "cocacola": "Coca-Cola",
    "coca-cola": "Coca-Cola",
    "可口可乐": "Coca-Cola",
    "pepsi": "Pepsi",
    "百事": "Pepsi",
    "disney": "Disney",
    "迪士尼": "Disney",
    "toyota": "Toyota",
    "丰田": "Toyota",
    "alibaba": "Alibaba",
    "阿里巴巴": "Alibaba",
    "tencent": "Tencent",
    "腾讯": "Tencent",
    "byd": "BYD",
    "比亚迪": "BYD",
    "huawei": "Huawei",
    "华为": "Huawei",
    "xiaomi": "Xiaomi",
    "小米": "Xiaomi",
    "baidu": "Baidu",
    "百度": "Baidu",
    "jd": "JD.com",
    "京东": "JD.com",
    "pdd": "Pinduoduo",
    "拼多多": "Pinduoduo",
    "meituan": "Meituan",
    "美团": "Meituan",
    "netease": "NetEase",
    "网易": "NetEase",
}

_YEAR_PATTERN = re.compile(r"\b(20[012]\d)\b")
_APPLE_PRODUCT_COMPANY_HINT = re.compile(
    r"\biphone\b.{0,15}\b(?:maker|manufacturer|company)\b|"
    r"(?:做|生产|制造)?\s*i\s*phone.{0,12}(?:的)?\s*(?:公司|厂商|企业)",
    re.IGNORECASE,
)
_FOLLOWUP_REFERENCE_PATTERN = re.compile(
    r"^\s*(?:what|which)\s+(?:was|is|were|are)\s+the\s+"
    r"(?:main|primary|key)\s+(?:growth\s+)?drivers?\s*[?.!]*$|"
    r"\b(?:it|its|they|their|them|this|that|those|same|there|now)\b|"
    r"^\s*(?:(?:what|how)\s+about|and|also)\b|\bcompare\s+it\b|"
    r"^\s*(?:focus(?:\s+only)?(?:\s+on)?|concentrate\s+on|elaborate\s+on|"
    r"expand\s+on|tell\s+me\s+more\s+about)\b|"
    r"^\s*(?:只(?:重点)?(?:分析|讨论|关注|聚焦|看|比较)|重点(?:分析|讨论|关注|聚焦))|"
    r"它(?:的)?|那份|这份|同一(?:家公司|份)|现在(?:再)?|那么|继续",
    re.IGNORECASE,
)
_FINANCIAL_CONTEXT_FOLLOWUP_PATTERN = re.compile(
    r"(?:收入|营收|营业额|净利润|利润|毛利率|经营现金流|经营利润|资产|负债|"
    r"每股收益|营收|revenue|net income|gross margin|operating income|eps)"
    r".*(?:20\d{2}|Q[1-4]|FY\d{4}|年度|季度|同比|环比|增长|变化|分别|各自|"
    r"分地区|分产品|销售模式|直销|批发代理|国内|国外)|"
    r"(?:20\d{2}|Q[1-4]|FY\d{4}|年度|季度|同比|环比|增长|变化|分别|各自|"
    r"分地区|分产品|销售模式|直销|批发代理|国内|国外).*"
    r"(?:收入|营收|营业额|净利润|利润|毛利率|经营现金流|经营利润|资产|负债|"
    r"每股收益|revenue|net income|gross margin|operating income|eps)",
    re.IGNORECASE,
)
_SOURCE_CONSTRAINT_PATTERN = re.compile(
    r"(?:\bonly\s+(?:use|using|from)\b|\buse\s+only\b|"
    r"\bbased\s+only\s+on\b|\busing\s+only\b|"
    r"(?:仅|只)(?:使用|根据)|只能使用|仅限于)"
    r".{0,140}?(?:financial\s+reports?|filings?|reports?|财报|报告|资料|文档)",
    re.IGNORECASE,
)


def extract_companies(question: str) -> list[str]:
    lower = question.lower()
    seen: set[str] = set()
    result: list[str] = []

    for key, name in _COMPANY_MAP.items():
        if key in lower and name not in seen:
            seen.add(name)
            result.append(name)

    # A product mention alone (for example, “What is an iPhone?”) is not a
    # company scope. Resolve Apple only when the wording identifies the maker.
    if "Apple" not in seen and _APPLE_PRODUCT_COMPANY_HINT.search(question):
        seen.add("Apple")
        result.append("Apple")

    for ticker, name in {"aapl": "Apple", "tsla": "Tesla", "nvda": "NVIDIA"}.items():
        if re.search(rf"\b{ticker}\b", lower) and name not in seen:
            seen.add(name)
            result.append(name)

    return result


def extract_allowed_source_companies(question: str) -> list[str]:
    """Extract issuers explicitly allowed by a source-only constraint.

    This is deliberately opt-in and narrow. Ordinary company mentions remain
    query targets; only wording such as ``use only Apple's financial reports``
    creates an evidence-source allow-list.
    """

    seen: set[str] = set()
    result: list[str] = []
    for match in _SOURCE_CONSTRAINT_PATTERN.finditer(question or ""):
        for company in extract_companies(match.group(0)):
            if company not in seen:
                seen.add(company)
                result.append(company)
    return result


def prior_user_context_for_followup(
    question: str,
    history: list[dict] | None,
) -> tuple[str, list[str]] | None:
    """Return the latest entity-bearing user request for a referential follow-up.

    Assistant messages are deliberately ignored: their text may mention other
    companies or periods than the user asked about, and must not silently
    change the retrieval scope of a later pronoun such as “it” / “它”. A prior
    standalone user question without an entity is a topic boundary; do not scan
    past it and resurrect an older company. Entityless referential turns may be
    followed backward until the nearest topic boundary or entity-bearing turn.
    """

    question_is_referential = bool(
        _FOLLOWUP_REFERENCE_PATTERN.search(question or "")
    )
    question_is_financial_scope_followup = bool(
        _FINANCIAL_CONTEXT_FOLLOWUP_PATTERN.search(question or "")
    )
    if not question_is_referential and not question_is_financial_scope_followup:
        return None
    for message in reversed(history or []):
        if not isinstance(message, dict) or str(message.get("role", "")).casefold() != "user":
            continue
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        companies = extract_companies(content)
        if companies:
            return content, companies
        if not _FOLLOWUP_REFERENCE_PATTERN.search(content):
            return None
    return None


def extract_years(question: str) -> list[str]:
    matches = _YEAR_PATTERN.findall(question)
    seen: set[str] = set()
    result: list[str] = []

    for year in matches:
        if year not in seen:
            seen.add(year)
            result.append(year)

    return result
