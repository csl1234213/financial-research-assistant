"""Deterministic financial grounding primitives.

The helpers in this module are deliberately provider-free.  They are shared by
offline evaluation and the runtime citation guard so a value is compared by
its economic meaning (unit/scale/currency), not by its display spelling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True)
class NormalizedNumber:
    """A numeric claim normalized to a base amount or percentage."""

    value: Decimal
    kind: str = "amount"  # amount, percent, basis_points, count
    currency: str | None = None
    quantum: Decimal | None = None  # display resolution after unit scaling


_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<open>\()?\s*(?P<sign>-)?\s*(?P<currency>\$|USD|US\$|EUR|CNY|RMB)?\s*"
    # PDF text extraction can insert a space after the decimal point
    # (``$75. 2 billion``).  Accept that presentation while normalizing it to
    # the same numeric value as ``$75.2 billion``.
    r"(?P<number>\d[\d,]*(?:\.\s*\d+)?)\s*(?P<close_number>\))?\s*"
    r"(?P<scale>thousand|million|billion|trillion|十亿美元|亿|万|[KMBTkmbt])?(?![A-Za-z])\s*"
    r"(?P<currency_after>USD|US\$|EUR|CNY|RMB|美元|人民币|元|dollars?)?\s*"
    r"(?P<percent>%|percent)?\s*(?P<bps>bps|basis points)?\s*(?P<close>\))?"
)
_MONTH_BEFORE_DATE_DAY = re.compile(
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\.?\s*$",
    re.IGNORECASE,
)
_DATE_DAY_SUFFIX = re.compile(
    r"\s*,?\s*(?:(?:19|20)\d{2}\b|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b)",
    re.IGNORECASE,
)

_SCALE = {
    "k": Decimal("1000"),
    "thousand": Decimal("1000"),
    "m": Decimal("1000000"),
    "million": Decimal("1000000"),
    "b": Decimal("1000000000"),
    "billion": Decimal("1000000000"),
    "t": Decimal("1000000000000"),
    "trillion": Decimal("1000000000000"),
    "十亿美元": Decimal("1000000000"),
    # Chinese financial answers commonly express USD billions as ``75.2
    # 亿美元``.  Normalise the unit instead of treating 75.2 as a raw USD
    # amount; this keeps Chinese and English answers comparable.
    "亿": Decimal("100000000"),
    "万": Decimal("10000"),
}


def _parse_match(match: re.Match[str]) -> NormalizedNumber | None:
    try:
        value = Decimal(match.group("number").replace(",", "").replace(" ", ""))
    except (InvalidOperation, AttributeError):
        return None
    # A trailing ``)`` can belong to explanatory prose such as
    # ``($22.496 billion)`` where the opening parenthesis is outside the
    # numeric token (``(i.e., $22.496 billion)``).  Treating a lone closing
    # parenthesis as a negative sign caused equivalent amounts to compare as
    # +22.496B vs -22.496B and incorrectly rejected otherwise supported
    # claims.  Parenthetical negatives have the opening/immediate closing
    # marker captured by ``open``/``close_number``.
    if match.group("open") or match.group("close_number") or match.group("sign"):
        value = -value
    scale = match.group("scale")
    raw_number = match.group("number").replace(",", "").replace(" ", "")
    decimal_places = len(raw_number.partition(".")[2]) if "." in raw_number else 0
    quantum = Decimal(1).scaleb(-decimal_places)
    if scale:
        scale_factor = _SCALE[scale.casefold()]
        value *= scale_factor
        quantum *= scale_factor
    percent = match.group("percent")
    basis_points = match.group("bps")
    currency = match.group("currency") or match.group("currency_after")
    if currency:
        currency = currency.casefold().replace("us$", "usd")
        currency = {
            "$": "usd",
            "dollars": "usd",
            "美元": "usd",
            "rmb": "cny",
            "人民币": "cny",
            "元": "cny",
        }.get(currency, currency)
    if percent:
        return NormalizedNumber(value=value, kind="percent", currency=None, quantum=quantum)
    if basis_points:
        return NormalizedNumber(value=value, kind="basis_points", currency=None, quantum=quantum)
    return NormalizedNumber(value=value, kind="amount", currency=currency, quantum=quantum)


def extract_normalized_numbers(
    text: str,
    *,
    allow_year_like_amount: bool = False,
) -> list[NormalizedNumber]:
    """Extract financial numbers while preserving scale and sign.

    Comparative financial table rows can legitimately contain a comma-grouped
    amount such as ``2,034``. The default year guard is still correct for
    prose, but callers that have already isolated a verified table row may
    explicitly allow that amount-shaped value instead of treating it as the
    year 2034.
    """

    values: list[NormalizedNumber] = []
    for match in _NUMBER_RE.finditer(text or ""):
        before = (text or "")[max(0, match.start() - 12) : match.start()].casefold()
        after = (text or "")[match.end() : match.end() + 8].casefold()
        # Citation labels and calendar date components are structural text,
        # not financial claims (``[Evidence 15]``, ``2026 年 4 月 26 日``).
        if re.search(r"evidence\s*$", before, re.IGNORECASE):
            continue
        if re.search(r"(?:page|p\.)\s*$", before, re.IGNORECASE):
            continue
        if re.match(r"\s*(?:年|月|日|号)", after):
            continue
        # English filing headers commonly spell dates as ``April 26, 2026``
        # or list comparative dates as ``April 26, April 27, 2026``. The day
        # component is a calendar label, not a financial amount. Without this
        # guard the answer sanitizer can replace a fully source-supported
        # reporting-period sentence with an insufficiency placeholder.
        if (
            parsed_number := re.fullmatch(r"\d{1,2}", match.group("number").replace(",", ""))
        ) and not any(match.group(name) for name in ("currency", "scale", "percent", "bps", "currency_after")):
            day = int(parsed_number.group(0))
            if (
                1 <= day <= 31
                and _MONTH_BEFORE_DATE_DAY.search(before)
                and _DATE_DAY_SUFFIX.match(after)
            ):
                continue
        if re.search(
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
            r"dec(?:ember)?)\s*$",
            before,
            re.IGNORECASE,
        ) and not match.group("currency") and not match.group("scale") and not match.group("percent"):
            continue
        # PDF page footers such as ``Form 10-Q | 16`` are navigation
        # metadata, not financial facts.
        if (
            (re.search(r"form\s*$", before) and re.match(r"\s*-\s*q", after))
            or re.search(r"\|\s*$", before)
        ):
            continue
        parsed = _parse_match(match)
        if parsed is None:
            continue
        # Years and bare single digits are usually labels, not claims.
        if parsed.kind == "amount" and parsed.value == parsed.value.to_integral_value():
            integer = int(parsed.value)
            if (
                1900 <= abs(integer) <= 2100
                and not match.group("scale")
                and not allow_year_like_amount
            ):
                continue
            if abs(integer) < 10 and not match.group("currency") and not match.group("scale"):
                continue
        values.append(parsed)
    return values


def numbers_equivalent(left: NormalizedNumber, right: NormalizedNumber) -> bool:
    """Compare claims without allowing amount/percent or scale confusion."""

    if left.kind != right.kind:
        return False
    if left.currency and right.currency and left.currency.casefold() != right.currency.casefold():
        return False
    if left.value == right.value:
        return True
    resolutions = [value for value in (left.quantum, right.quantum) if value is not None]
    if not resolutions:
        return False
    # A displayed value is rounded to its last shown digit. Permit only the
    # half-unit rounding interval at the coarser precision; this equates 81.6B
    # with 81,615M without ever confusing 81.6M and 81.6B.
    return abs(left.value - right.value) <= max(resolutions) / Decimal("2")


_METRIC_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "automotive_revenue",
        (
            "automotive revenue",
            "automotive business",
            "automotive segment",
            "汽车业务",
            "汽车业务分部",
        ),
    ),
    (
        "services_revenue",
        (
            "services revenue",
            "services net sales",
            "services and other",
            "services business",
            "service business",
            "services segment",
            "service segment",
            "service-related business",
            "service-related revenue",
            "服务业务",
            "服务相关业务",
            "服务类业务",
            "服务分部",
        ),
    ),
    (
        "energy_revenue",
        (
            "energy generation and storage revenue",
            "energy generation and storage",
            "energy revenue",
            "能源发电与储能收入",
            "能源发电和储能收入",
            "能源收入",
        ),
    ),
    ("edge_computing_revenue", (
        "edge computing revenue", "edge revenue", "边缘计算收入", "边缘计算营收", "边缘计算业务",
    )),
    (
        "iphone_revenue",
        (
            "iphone®", "iphone net sales", "iphone revenue",
            "iphone 销售额", "iphone收入", "iphone 收入", "iphone销售额",
        ),
    ),
    ("products_revenue", ("products net sales", "products revenue", "产品净销售额", "产品收入")),
    ("mac_revenue", ("mac®", "mac net sales", "mac revenue", "mac销售额", "mac收入")),
    ("ipad_revenue", ("ipad®", "ipad net sales", "ipad revenue", "ipad销售额", "ipad收入")),
    (
        "wearables_revenue",
        (
            "wearables, home and accessories",
            "wearables net sales",
            "wearables revenue",
            "可穿戴设备、家居和配件",
        ),
    ),
    (
        "products_gross_margin",
        ("products gross margin", "metric: products", "产品毛利率"),
    ),
    (
        "services_gross_margin",
        ("services gross margin", "metric: services", "服务毛利率"),
    ),
    ("data_center_revenue", (
        "data center revenue", "data-center revenue", "datacenter revenue",
        "data center business", "data-center business", "datacenter business",
        "data centre revenue", "data-centre revenue", "data centre business",
        "data-centre business", "data center performance", "data centre performance",
        "data center growth", "data centre growth",
        "data-centre performance", "data-centre growth",
        "数据中心收入", "数据中心业务", "数据中心表现", "数据中心业绩", "数据中心增长",
    )),
    ("operating_margin", ("operating margin", "operating profit margin", "营业利润率")),
    ("automotive_gross_margin", ("automotive gross margin", "汽车业务毛利率")),
    ("gross_margin", ("gross margin", "毛利率", "毛利")),
    ("gross_profit", ("gross profit", "毛利额", "毛利润")),
    ("net_income", ("net income", "net profit", "net earnings", "净利润")),
    ("operating_income", ("operating income", "income from operations", "营业利润")),
    ("free_cash_flow", ("free cash flow", "fcf", "自由现金流")),
    (
        "operating_cash_flow",
        (
            "net cash provided by operating activities",
            "cash generated by operating activities",
            "operating cash flow",
            "经营活动现金流",
            "经营活动产生的现金流",
        ),
    ),
    ("cash_paid_for_taxes", ("cash paid for income taxes", "cash paid for taxes", "所得税支付现金", "支付的所得税")),
    ("cash_flow", ("cash flow", "operating cash", "现金流")),
    ("main_business_revenue", ("main business revenue", "core business revenue", "主营业务收入")),
    ("revenue", ("total revenue", "total revenues", "net sales", "revenue", "revenues", "营收", "收入")),
)


def canonical_metrics(text: str) -> tuple[str, ...]:
    """Return all explicit financial metrics, preferring specific aliases.

    This matters for both metric breakdowns and multi-metric questions: total
    revenue is not Data Center revenue, while a request for revenue by segment
    may legitimately contain several specific revenue metrics.
    """
    lowered = (text or "").casefold()
    matched = [
        canonical
        for canonical, aliases in _METRIC_ALIASES
        if any(alias in lowered for alias in aliases)
    ]
    coordinated_margins = re.search(
        r"\bgross\s+and\s+operating\s+margins?\b|毛利(?:率)?\s*(?:和|及|与)\s*营业利润率",
        lowered,
    )
    if coordinated_margins:
        matched.extend(metric for metric in ("operating_margin", "gross_margin") if metric not in matched)
    elif re.search(r"\bmargins?\b|利润率", lowered) and not re.search(
        r"\bgross\s+(?:profit\s+)?margins?\b|\boperating\s+(?:profit\s+)?margins?\b|毛利率|营业利润率",
        lowered,
    ):
        # A generic margin question asks for both common margin measures; it
        # is not safe to silently interpret it as gross margin alone.
        matched.extend(metric for metric in ("operating_margin", "gross_margin") if metric not in matched)
    coordinated_margins = re.search(
        r"\bgross\s+and\s+operating\s+margins?\b|毛利(?:率)?\s*(?:和|及|与)\s*营业利润率",
        lowered,
    )
    if coordinated_margins:
        matched.extend(metric for metric in ("operating_margin", "gross_margin") if metric not in matched)
    elif re.search(r"\bmargins?\b|利润率", lowered) and not re.search(
        r"\bgross\s+(?:profit\s+)?margins?\b|\boperating\s+(?:profit\s+)?margins?\b|毛利率|营业利润率",
        lowered,
    ):
        # A generic margin question asks for both common margin measures; it
        # is not safe to silently interpret it as gross margin alone.
        matched.extend(metric for metric in ("operating_margin", "gross_margin") if metric not in matched)
    specific_revenue = {
        "automotive_revenue", "services_revenue", "energy_revenue",
        "data_center_revenue", "edge_computing_revenue", "iphone_revenue",
        "products_revenue", "mac_revenue", "ipad_revenue", "wearables_revenue",
        "main_business_revenue",
    }
    if specific_revenue.intersection(matched):
        matched = [metric for metric in matched if metric != "revenue"]
    if "automotive_gross_margin" in matched:
        matched = [metric for metric in matched if metric != "gross_margin"]
    if "revenue" in matched and any(
        term in lowered
        for term in ("breakdown", "by segment", "segments", "components", "composition", "分项", "构成", "拆分", "分部")
    ):
        for metric in (
            "automotive_revenue", "services_revenue", "energy_revenue",
            "data_center_revenue", "edge_computing_revenue",
        ):
            if metric not in matched:
                matched.append(metric)
    return tuple(matched)


def canonical_metric(text: str) -> str | None:
    """Return one strict metric key; specific metrics win over broad aliases."""

    metrics = canonical_metrics(text)
    return metrics[0] if metrics else None


def metric_matches(question: str, evidence: str) -> bool:
    """Match metrics conservatively, never folding automotive revenue into total revenue."""

    expected = canonical_metric(question)
    if expected is None:
        return True
    actual = canonical_metric(evidence)
    if actual == expected:
        return True
    # A broad revenue question can accept a total-revenue statement only.
    if expected == "revenue":
        return actual == "revenue"
    return False


def derived_growth(left: NormalizedNumber, right: NormalizedNumber) -> NormalizedNumber | None:
    """Calculate a deterministic percentage change from two amount operands."""

    if left.kind != "amount" or right.kind != "amount" or right.value == 0:
        return None
    return NormalizedNumber(
        value=(left.value - right.value) / right.value * Decimal("100"),
        kind="percent",
    )


def any_equivalent(claims: Iterable[NormalizedNumber], evidence: Iterable[NormalizedNumber]) -> bool:
    return any(numbers_equivalent(claim, item) for claim in claims for item in evidence)
