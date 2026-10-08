"""Provider-free required-fact planning and generation coverage checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from agent.planning.entity_extractor import extract_companies
from agent.reasoning_models import Evidence
from core.fact_ledger import (
    FactLedger,
    FinancialFact,
    canonical_company,
    canonical_metric_id,
    metric_aliases,
    periods_equivalent,
)
from core.financial_grounding import (
    NormalizedNumber,
    canonical_metrics,
    derived_growth,
    extract_normalized_numbers,
    numbers_equivalent,
)
from core.growth_driver_evidence import is_growth_narrative_question
from core.query_scope import (
    QueryScope,
    classify_query_scope,
    current_turn_query,
    is_nonfinancial_business_development_summary,
)
from retrieval.periods import extract_annual_periods, extract_periods


@dataclass(frozen=True)
class RequiredFactSpec:
    company: str | None
    metric_id: str
    period: str | None
    reason: str
    accounting_basis: str | None = None
    growth_basis: str | None = None
    dimension: str | None = None
    category: str | None = None

    @property
    def key(self) -> str:
        parts = (canonical_company(self.company or ""), self.metric_id, self.period or "")
        if self.accounting_basis:
            parts = (*parts, self.accounting_basis)
        if self.growth_basis:
            parts = (*parts, f"growth_{self.growth_basis}")
        if self.dimension:
            parts = (*parts, f"dimension_{self.dimension}")
        if self.category:
            parts = (*parts, f"category_{self.category.casefold()}")
        return "|".join(parts)


@dataclass(frozen=True)
class RequiredFactStatus:
    spec: RequiredFactSpec
    available: tuple[FinancialFact, ...]
    answer_present: bool = False


@dataclass(frozen=True)
class RequiredFactPlan:
    scope: str
    required: tuple[RequiredFactSpec, ...]

    def statuses(self, ledger: FactLedger, answer: str = "") -> tuple[RequiredFactStatus, ...]:
        return tuple(
            RequiredFactStatus(
                spec=spec,
                available=_facts_for_spec(spec, ledger),
                answer_present=answer_contains_fact(answer, spec, ledger),
            )
            for spec in self.required
        )

    def prompt_context(self, ledger: FactLedger) -> str:
        lines = ["REQUIRED FACT PLAN"]
        for status in self.statuses(ledger):
            state = "AVAILABLE" if status.available else "MISSING"
            lines.append(
                f"- company={status.spec.company or 'unspecified'}; metric_id={status.spec.metric_id}; "
                f"period={status.spec.period or 'unspecified'}; "
                f"accounting_basis={status.spec.accounting_basis or 'unspecified'}; "
                f"growth_basis={status.spec.growth_basis or 'unspecified'}; "
                f"dimension={status.spec.dimension or 'unspecified'}; "
                f"category={status.spec.category or 'unspecified'}; "
                f"status={state}; reason={status.spec.reason}"
            )
        return "\n".join(lines)

    def as_dict(self, ledger: FactLedger, answer: str = "") -> dict[str, object]:
        statuses = self.statuses(ledger, answer)
        return {
            "scope": self.scope,
            "required": [
                {
                    "company": status.spec.company,
                    "metric_id": status.spec.metric_id,
                    "period": status.spec.period,
                    "accounting_basis": status.spec.accounting_basis,
                    "growth_basis": status.spec.growth_basis,
                    "dimension": status.spec.dimension,
                    "category": status.spec.category,
                    "reason": status.spec.reason,
                    "available": bool(status.available),
                    "fact_ids": [fact.fact_id for fact in status.available],
                    "answer_present": status.answer_present,
                }
                for status in statuses
            ],
        }


def _period(question: str) -> str | None:
    periods = extract_periods(question)
    if periods:
        return periods[0]
    annual_periods = extract_annual_periods(question)
    if annual_periods:
        return annual_periods[0]
    # Chinese users commonly write ``2025年净利润`` rather than ``2025年度``.
    # Interpret that year as annual only when no quarter label was found above.
    annual_year = re.search(r"(?<!\d)(20\d{2})\s*年", question)
    return f"FY{annual_year.group(1)}" if annual_year else None


def _explicit_annual_comparison_periods(question: str) -> tuple[str, ...]:
    """Extract years named in an explicit annual comparison, in query order.

    Bare years are intentionally not promoted to periods generally. Require
    comparison language and no quarter labels so historical years in prose or
    quarterly questions cannot silently expand a fact plan.
    """

    if extract_periods(question) or not re.search(
        r"相比|比较|對比|对比|同比|較|较|compare|compared|versus|\bvs\.?\b|"
        r"year[- ]over[- ]year|\byoy\b|增长|增長|下降|减少|增加|变化|change|growth",
        question,
        re.IGNORECASE,
    ):
        return ()
    years = tuple(dict.fromkeys(re.findall(r"(?<!\d)(20\d{2})(?!\d)", question)))
    return tuple(f"FY{year}" for year in years) if len(years) >= 2 else ()


def _fact_accounting_basis(fact: FinancialFact) -> str | None:
    text = str(fact.evidence_text or "")
    # FactLedger prefixes each value with its explicit basis when a sentence
    # reports paired GAAP/non-GAAP margins. Prefer that scoped label over the
    # other basis mentioned later in the source sentence.
    scoped_basis = re.match(
        r"\s*(?P<basis>non[-\s\u2010-\u2014]?gaap|gaap)\b",
        text,
        re.IGNORECASE,
    )
    if scoped_basis:
        return "non_gaap" if scoped_basis.group("basis").casefold() != "gaap" else "gaap"
    if re.search(r"\bnon[-\s\u2010-\u2014]?gaap\b", text, re.IGNORECASE):
        return "non_gaap"
    if re.search(r"\bgaap\b", text, re.IGNORECASE):
        return "gaap"
    return None


def _facts_for_spec(spec: RequiredFactSpec, ledger: FactLedger) -> tuple[FinancialFact, ...]:
    # 计划中的维度/类别是证据口径的一部分，不能只按指标和数值匹配。
    facts = ledger.lookup(
        company=spec.company,
        metric_id=spec.metric_id,
        period=spec.period,
        growth_basis=spec.growth_basis,
        dimension=spec.dimension,
        category=spec.category,
    )
    if spec.dimension is None and spec.category is None:
        # 未指定产品、地区或渠道的公司级问题，不能由分组行满足。
        # P1.5 标准报表事实把 scope/statement 放在同名字段中；合并报表
        # 并非产品或地区分组，必须保留为公司级候选。
        facts = tuple(
            fact for fact in facts
            if (not fact.dimension and not fact.category)
            or (fact.source_kind == "FINANCIAL_STATEMENT" and fact.scope == "CONSOLIDATED")
        )
    if not spec.accounting_basis:
        return facts
    return tuple(fact for fact in facts if _fact_accounting_basis(fact) == spec.accounting_basis)


def _explicit_dimension_categories(
    question: str,
    ledger: FactLedger,
    companies: list[str],
    period: str | None,
) -> tuple[str, tuple[str, ...]] | None:
    """Find a table dimension whose named categories are explicitly requested.

    Category expansion is evidence-led: a dimension/category must exist in the
    retrieved fact ledger and its category label must be named in the question.
    This avoids borrowing product rows for a regional/channel question.
    """
    normalized_question = re.sub(r"\s+", "", question).casefold()
    facts_by_dimension: dict[str, list[FinancialFact]] = {}
    for fact in ledger.facts:
        if (
            fact.dimension
            and fact.category
            and (not companies or fact.company in companies)
            and (period is None or periods_equivalent(fact.fact_period, period))
        ):
            facts_by_dimension.setdefault(fact.dimension, []).append(fact)
    requested: list[tuple[str, tuple[str, ...]]] = []
    for dimension, facts in facts_by_dimension.items():
        categories = tuple(dict.fromkeys(
            fact.category
            for fact in facts
            if fact.category
            and re.sub(r"\s+", "", fact.category).casefold() in normalized_question
        ))
        if len(categories) >= 2 and re.search(r"分别|各自|各类|各.*(?:收入|营收|毛利率)", question):
            requested.append((dimension, categories))
    # Only expand when the question identifies exactly one dimension. If its
    # labels collide across tables, fail closed instead of mixing row groups.
    return requested[0] if len(requested) == 1 else None


def _category_is_named(text: str, category: str | None) -> bool:
    """要求回答片段明确写出类别，避免无标签数字被误认成该类别事实。"""
    if not category:
        return True
    def normalize(value: str) -> str:
        return re.sub(r"[\s，。；：:、（）()\[\]]+", "", value.casefold())

    return normalize(category) in normalize(str(text or ""))


def _margin_specs_for_available_bases(
    company: str | None,
    metric_id: str,
    period: str | None,
    reason: str,
    ledger: FactLedger,
) -> list[RequiredFactSpec]:
    """Split basis-sensitive metrics when source evidence labels both bases.

    Filings commonly report GAAP and non-GAAP EPS together with margins. A
    single unqualified ``eps`` requirement would select one value and silently
    omit the other from a broad financial summary, even though both values are
    present and independently citable.
    """
    facts = ledger.lookup(company=company, metric_id=metric_id, period=period)
    bases = {_fact_accounting_basis(fact) for fact in facts}
    if metric_id in {"gross_margin", "operating_margin", "eps"} and bases >= {"gaap", "non_gaap"}:
        return [
            RequiredFactSpec(company, metric_id, period, reason, basis)
            for basis in ("gaap", "non_gaap")
        ]
    return [RequiredFactSpec(company, metric_id, period, reason)]


def _growth_specs_for_metrics(
    specs: Iterable[RequiredFactSpec], ledger: FactLedger, *, allow_derived: bool = True
) -> list[RequiredFactSpec]:
    """Require reported rates and optionally derive comparison rates.

    Reported rates are safe to include in a summary when the filing labels
    them for the requested period.  Derived rates are more invasive: they
    should only be planned when the user explicitly asks for a comparison, so
    a broad summary cannot acquire extra refusal lines for metrics the user
    never requested.
    """

    growth_specs: list[RequiredFactSpec] = []
    for spec in specs:
        for basis in ("yoy", "qoq"):
            if ledger.lookup(
                company=spec.company,
                metric_id=spec.metric_id,
                period=spec.period,
                growth_basis=basis,
                dimension=spec.dimension,
                category=spec.category,
            ):
                growth_specs.append(
                    RequiredFactSpec(
                        spec.company,
                        spec.metric_id,
                        spec.period,
                        f"explicitly reported {basis.upper()} change for a planned financial metric",
                        growth_basis=basis,
                        dimension=spec.dimension,
                        category=spec.category,
                    )
                )
                continue
            if not allow_derived or basis != "yoy" or not spec.period:
                continue
            prior_period = _prior_comparable_period(spec.period)
            if prior_period is None:
                continue
            current = ledger.lookup(
                company=spec.company, metric_id=spec.metric_id, period=spec.period,
                dimension=spec.dimension, category=spec.category,
            )
            prior = ledger.lookup(
                company=spec.company, metric_id=spec.metric_id, period=prior_period,
                dimension=spec.dimension, category=spec.category,
            )
            if current and prior:
                growth_specs.append(
                    RequiredFactSpec(
                        spec.company,
                        spec.metric_id,
                        spec.period,
                        "deterministically derivable YOY change from matching-period operands",
                        growth_basis="yoy",
                        dimension=spec.dimension,
                        category=spec.category,
                    )
                )
    return growth_specs


def _prior_comparable_period(period: str | None) -> str | None:
    """Return the same quarter or annual period in the prior year."""

    if not period:
        return None
    annual = re.fullmatch(r"FY(?P<year>20\d{2})", str(period).strip(), re.IGNORECASE)
    if annual:
        return f"FY{int(annual.group('year')) - 1}"
    match = re.fullmatch(
        r"Q(?P<quarter>[1-4])_(?P<fiscal>FY)?(?P<year>20\d{2})",
        str(period).strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    fiscal = "FY" if match.group("fiscal") else ""
    return f"Q{match.group('quarter')}_{fiscal}{int(match.group('year')) - 1}"


def _company_reporting_period(
    ledger: FactLedger,
    company: str,
    metric_id: str | None,
) -> str | None:
    """Choose the filing's reporting period for an unqualified comparison.

    Comparative tables often contain several historical quarters (and may
    even contain rows without a period).  When the question names companies
    but no explicit quarter, the document reporting period is the safest
    authoritative anchor: Tesla's Q2 2025 filing therefore maps to Q2_2025,
    while NVIDIA's Q1 FY2027 filing maps to Q1_FY2027.  A row period is only a
    fallback when no filing-level period is available.
    """

    facts = ledger.lookup(company=company, metric_id=metric_id)

    def usable_period(value: str | None) -> bool:
        normalized = str(value or "").strip().casefold().replace("-", "_")
        return normalized not in {
            "",
            "unknown",
            "undated",
            "none",
            "null",
            "n_a",
            "na",
            "not_available",
        }

    # Tenant uploads created by older ingestion versions may carry the
    # literal ``Unknown`` marker.  It is missing metadata, not an
    # authoritative filing period, and must not outvote a public filing's
    # real reporting period in mixed-scope retrieval.
    reporting = [
        fact.document_reporting_period
        for fact in facts
        if usable_period(fact.document_reporting_period)
    ]
    if reporting:
        # Preserve deterministic order while preferring the period repeated
        # by the greatest number of evidence rows.
        counts = {period: reporting.count(period) for period in dict.fromkeys(reporting)}
        report_period = max(counts, key=lambda period: (counts[period], period))
        if any(periods_equivalent(fact.fact_period, report_period) for fact in facts):
            return report_period
        # Filing-level quarter metadata is not row-level truth. When the
        # requested metric appears only in an annual comparison table, prefer
        # the matching fiscal year rather than relabeling it as Q4 actuals.
        report_year = re.search(r"20\d{2}", report_period)
        annual_period = f"FY{report_year.group(0)}" if report_year else None
        if annual_period and any(
            periods_equivalent(fact.fact_period, annual_period) for fact in facts
        ):
            return annual_period
        fact_periods = [fact.fact_period for fact in facts if usable_period(fact.fact_period)]
        if fact_periods:
            period_counts = {period: fact_periods.count(period) for period in dict.fromkeys(fact_periods)}
            return max(period_counts, key=lambda period: (period_counts[period], period))
        return report_period
    row_periods = [fact.fact_period for fact in facts if usable_period(fact.fact_period)]
    return row_periods[0] if row_periods else None


def _document_identity_period(
    ledger: FactLedger,
    company: str,
    metric_id: str | None,
) -> str | None:
    """Return a validated period encoded by a stable ingestion document id.

    A document id is not a filename and is not accepted as period evidence by
    itself.  It can only act as an anchor for an *unqualified comparison* when
    the same id's extracted facts also contain that period in their printed
    row/column evidence.  This handles canonical source identities such as
    ``tesla_q2_2025`` whose filing-level metadata may describe the later
    Q4/FY2025 update while the benchmark intentionally compares its Q2 column.
    Unknown or UUID-like ids contribute no candidate.
    """

    facts = ledger.lookup(company=company, metric_id=metric_id)
    by_document: dict[str, list[FinancialFact]] = {}
    for fact in facts:
        document_id = str(fact.document_id or "").strip()
        if document_id:
            by_document.setdefault(document_id, []).append(fact)

    candidates: list[str] = []
    for document_id, document_facts in by_document.items():
        normalized_id = re.sub(r"[_-]+", " ", document_id)
        for candidate in extract_periods(normalized_id):
            # The id is only a hint.  Require an independently extracted fact
            # with the same period from the document's printed evidence.
            if any(
                periods_equivalent(fact.fact_period, candidate)
                for fact in document_facts
            ):
                candidates.append(candidate)

    if not candidates:
        return None
    counts = {period: candidates.count(period) for period in dict.fromkeys(candidates)}
    return max(counts, key=lambda period: (counts[period], period))


def _quarter_label(period: str | None) -> str | None:
    match = re.match(r"^Q([1-4])(?:_|$)", str(period or "").strip().upper())
    return match.group(1) if match else None


def _comparison_periods_by_company(
    ledger: FactLedger, companies: list[str]
) -> dict[str, str | None]:
    """Select comparable quarter columns for an unqualified comparison.

    A filing-level period is authoritative for narrative facts, but a PDF can
    be a Q4 update whose financial table also contains Q1--Q3 historical
    columns.  For a broad multi-company comparison, silently pairing Apple's
    Q2 with Tesla's Q4 creates a false period comparison even though Tesla's
    Q2 column is present.  Align only on an explicitly labelled quarter that
    exists for every named company; if no common quarter exists, retain each
    company's reporting period and let the answer label the mismatch.
    """

    if len(companies) < 2:
        return {}

    periods_by_company: dict[str, list[str]] = {}
    for company in companies:
        facts = ledger.lookup(company=company, metric_id="revenue")
        if not facts:
            facts = [fact for fact in ledger.facts if canonical_company(fact.company) == company]
        periods = list(dict.fromkeys(
            str(fact.fact_period)
            for fact in facts
            if fact.fact_period and _quarter_label(fact.fact_period)
        ))
        periods_by_company[company] = periods
    if any(not periods for periods in periods_by_company.values()):
        return {}

    quarter_sets = [
        {label for period in periods for label in [_quarter_label(period)] if label}
        for periods in periods_by_company.values()
    ]
    common_quarters = set.intersection(*quarter_sets)
    if not common_quarters:
        # When issuers publish on different fiscal quarters, preserve the
        # canonical period represented by each source identity if it can be
        # proven by that source's printed facts.  Otherwise return an empty
        # mapping and fall back to the content-derived filing period.
        identity_periods = {
            company: _document_identity_period(ledger, company, "revenue")
            for company in companies
        }
        if all(identity_periods.values()):
            return identity_periods
        return {}

    # Align a shared quarter only when every issuer's own reporting period has
    # that same quarter label.  Looking only at the intersection is unsafe:
    # Tesla's historical Q4 column and NVIDIA's Q4 comparison column would
    # otherwise be mistaken for a same-period pair even though their years
    # differ substantially.
    reporting_periods = {
        company: _company_reporting_period(ledger, company, "revenue")
        for company in companies
    }
    preferred_labels = {
        label
        for label in (_quarter_label(period) for period in reporting_periods.values())
        if label
    }
    first_label = _quarter_label(reporting_periods.get(companies[0]))
    # A single shared quarter can safely align an anchor filing with a
    # historical column (for example Apple Q2 versus a Tesla Q4 update whose
    # only shared quarter is Q2).  If several historical quarter labels are
    # shared, the overlap is ambiguous and must not select an arbitrary one.
    if (
        len(preferred_labels) != 1
        and len(common_quarters) == 1
        and first_label in common_quarters
    ):
        chosen_quarter = next(iter(common_quarters))
        def shared_period(company: str) -> str | None:
            reporting_period = reporting_periods[company]
            if _quarter_label(reporting_period) == chosen_quarter:
                return reporting_period
            return next(
                (
                    period
                    for period in periods_by_company[company]
                    if _quarter_label(period) == chosen_quarter
                ),
                None,
            )

        return {company: shared_period(company) for company in companies}
    if len(preferred_labels) != 1 or not preferred_labels.issubset(common_quarters):
        identity_periods = {
            company: _document_identity_period(ledger, company, "revenue")
            for company in companies
        }
        if all(identity_periods.values()):
            return identity_periods
        return {}

    chosen_quarter = next(iter(preferred_labels))
    result: dict[str, str | None] = {}
    for company in companies:
        candidates = periods_by_company[company]
        reporting_period = reporting_periods[company]
        result[company] = (
            reporting_period
            if _quarter_label(reporting_period) == chosen_quarter
            else next(
                (period for period in candidates if _quarter_label(period) == chosen_quarter),
                None,
            )
        )
    return result


def infer_required_fact_plan(
    question: str, evidence: Iterable[Evidence], ledger: FactLedger | None = None
) -> RequiredFactPlan:
    items = list(evidence)
    ledger = ledger or FactLedger.from_evidence(items)
    intent_question = current_turn_query(question)
    scope = classify_query_scope(question)
    explicit_companies = [canonical_company(company) for company in extract_companies(question)]
    evidence_companies = list(ledger.companies())
    if explicit_companies:
        companies = explicit_companies
    elif scope == QueryScope.COMPARE:
        # A companyless comparison may refer to the set of available filings;
        # preserve each issuer partition rather than picking one at random.
        companies = evidence_companies[:3]
    elif len(evidence_companies) == 1:
        # A sole issuer in the conversation can safely resolve an elliptical
        # follow-up. Mixed-company context is ambiguous and must not silently
        # bind a generic fact question to whichever issuer sorts first.
        companies = evidence_companies
    else:
        companies = []
    if (
        not explicit_companies
        and scope in {QueryScope.FACT, QueryScope.SUMMARY}
        and len(evidence_companies) > 1
    ):
        return RequiredFactPlan(scope.value, ())
    period = _period(question)
    annual_comparison_periods = _explicit_annual_comparison_periods(intent_question)
    if period is None and annual_comparison_periods:
        period = annual_comparison_periods[0]
    metric = canonical_metric_id(intent_question)

    def available_generic_margin_metrics() -> list[str]:
        return [
            metric_id
            for metric_id in ("gross_margin", "operating_margin")
            if any(
                ledger.lookup(company=company, metric_id=metric_id, period=period)
                for company in (companies or [None])
            )
        ]

    def margin_expanded_specs(
        company: str | None, metric_id: str, metric_period: str | None, reason: str
    ) -> list[RequiredFactSpec]:
        if metric_id in {"gross_margin", "operating_margin", "eps"}:
            return _margin_specs_for_available_bases(
                company, metric_id, metric_period, reason, ledger
            )
        return [RequiredFactSpec(company, metric_id, metric_period, reason)]

    asks_cash_flow = bool(re.search(r"\bcash\s+flows?\b|现金流", intent_question, re.I))
    if (metric == "cash_flow" or (metric is None and asks_cash_flow)) and ledger.lookup(
        metric_id="operating_cash_flow"
    ):
        metric = "operating_cash_flow"
    if scope == QueryScope.GENERAL_CONCEPT:
        return RequiredFactPlan(scope.value, ())
    if scope == QueryScope.ANALYSIS:
        # For causal/business-driver questions, complete only an explicitly
        # named segment's headline metric. This preserves a supported core
        # fact (e.g. Data Center revenue) without turning a driver question
        # into a whole-company financial summary.
        segment_metrics = {
            "automotive_revenue",
            "services_revenue",
            "iphone_revenue",
            "products_revenue",
            "mac_revenue",
            "ipad_revenue",
            "wearables_revenue",
            "products_gross_margin",
            "services_gross_margin",
            "data_center_revenue",
            "edge_computing_revenue",
        }
        requested_metrics = [
            metric_id
            for metric_id in canonical_metrics(intent_question)
            if metric_id in segment_metrics
        ]
        if not requested_metrics:
            return RequiredFactPlan(scope.value, ())
        return RequiredFactPlan(
            scope.value,
            tuple(
                RequiredFactSpec(
                    company,
                    metric_id,
                    period
                    or _company_reporting_period(ledger, company, metric_id)
                    or _company_reporting_period(ledger, company, None),
                    "explicit segment/business metric in an analytical query",
                )
                for company in (companies[:1] or [None])
                for metric_id in requested_metrics
            ),
        )
    if scope == QueryScope.FACT:
        requested_metrics = list(dict.fromkeys(canonical_metrics(intent_question)))
        if "cash_flow" in requested_metrics and ledger.lookup(metric_id="operating_cash_flow"):
            requested_metrics = [
                "operating_cash_flow" if item == "cash_flow" else item
                for item in requested_metrics
            ]
            requested_metrics = list(dict.fromkeys(requested_metrics))
        if metric is not None and metric not in requested_metrics:
            requested_metrics.insert(0, metric)
        generic_margin_request = bool(
            re.search(r"\bmargins?\b|利润率", intent_question, re.IGNORECASE)
            and not re.search(
                r"\bgross\s+(?:profit\s+)?margins?\b|\boperating\s+(?:profit\s+)?margins?\b|毛利率|营业利润率",
                intent_question,
                re.IGNORECASE,
            )
        )
        if generic_margin_request:
            # An unqualified "margins" request does not assert that both
            # gross and operating margin are reported for this company/period.
            # Require the margin types actually present in evidence; explicitly
            # named metrics still remain required even when evidence is missing.
            requested_metrics = available_generic_margin_metrics() + [
                item for item in requested_metrics if item not in {"gross_margin", "operating_margin"}
            ]
        if not requested_metrics:
            # Do not silently answer an underspecified/general question with
            # whichever metric happened to be present in retrieved evidence.
            # The model may still answer from its grounded context, but the
            # fact ledger must not invent a revenue (or cash-flow) request.
            return RequiredFactPlan(scope.value, ())
        growth_requested = bool(
            re.search(
                r"\b(?:y\s*/\s*y|yoy|year[- ]over[- ]year|q\s*/\s*q|qoq|"
                r"quarter[- ]over[- ]quarter|growth|change|increased?|decreased?|"
                r"declined?|fell|rose|up|down|happened)\b|同比|环比|增长|变化|上升|下降|减少|增加",
                intent_question,
                re.IGNORECASE,
            )
        )
        requested_dimension = _explicit_dimension_categories(
            intent_question, ledger, companies, period
        )
        if requested_dimension:
            dimension, categories = requested_dimension
            # Regional rows in the Moutai filing are reported as revenue, even
            # though the prose calls the consolidated line 主营业务收入. Bind
            # the request to the explicitly named table dimension, not the
            # similarly worded whole-company metric.
            dimension_metrics = [
                "revenue" if dimension == "region" and item == "main_business_revenue" else item
                for item in requested_metrics
            ]
            dimension_metrics = list(dict.fromkeys(dimension_metrics))
            dimension_facts = [
                fact for fact in ledger.facts
                if fact.dimension == dimension
                and fact.category in categories
                and (not companies or fact.company in companies)
                and (period is None or periods_equivalent(fact.fact_period, period))
            ]
            category_specs: list[RequiredFactSpec] = []
            for category in categories:
                for requested_metric in dimension_metrics:
                    matching = next((
                        fact for fact in dimension_facts
                        if fact.category == category and fact.metric_id == requested_metric
                    ), None)
                    # Keep a missing requested row in the plan if this metric
                    # is represented for another requested category; it must
                    # not silently disappear from an EACH/RESPECTIVELY query.
                    if matching is None and not any(
                        fact.metric_id == requested_metric for fact in dimension_facts
                    ):
                        continue
                    category_specs.append(RequiredFactSpec(
                        companies[0] if companies else (matching.company if matching else None),
                        requested_metric,
                        period or (matching.fact_period if matching else None),
                        f"explicitly requested {dimension} category and financial metric",
                        dimension=dimension,
                        category=category,
                    ))
            if category_specs:
                if growth_requested:
                    for spec in tuple(category_specs):
                        prior_period = _prior_comparable_period(spec.period)
                        if prior_period:
                            prior = RequiredFactSpec(
                                spec.company, spec.metric_id, prior_period,
                                "available prior-year operand for an explicitly requested category YoY comparison",
                                dimension=spec.dimension, category=spec.category,
                            )
                            if _facts_for_spec(prior, ledger) and prior not in category_specs:
                                category_specs.append(prior)
                    category_specs.extend(_growth_specs_for_metrics(
                        [spec for spec in category_specs if spec.reason.startswith("explicitly requested")],
                        ledger,
                    ))
                return RequiredFactPlan(scope.value, tuple(category_specs))
        required_specs: list[RequiredFactSpec] = []
        for company in (companies[:1] or [None]):
            for requested_metric in requested_metrics:
                metric_period = period or (
                    _company_reporting_period(ledger, company, requested_metric)
                    or _company_reporting_period(ledger, company, None)
                )
                required_specs.extend(
                    margin_expanded_specs(
                        company, requested_metric, metric_period, "explicit fact request"
                    )
                )
                if annual_comparison_periods:
                    current_period = metric_period or annual_comparison_periods[0]
                    for comparison_period in annual_comparison_periods:
                        if comparison_period == current_period:
                            continue
                        comparison_spec = RequiredFactSpec(
                            company,
                            requested_metric,
                            comparison_period,
                            "explicit annual comparison operand named by the user",
                        )
                        if comparison_spec not in required_specs:
                            required_specs.append(comparison_spec)
        # A narrow FACT question must not grow into an unsolicited YoY/QoQ
        # claim merely because matching operands happen to be present in the
        # same filing.  Besides over-answering, that can create a derived
        # percentage which has no direct citation in the source and trigger a
        # refusal beside an otherwise supported answer.  Growth remains part
        # of the plan when the user explicitly asks for a comparison/change.
        if growth_requested:
            current_period_specs = [
                spec for spec in required_specs if spec.reason == "explicit fact request"
            ]
            # A YOY answer is easier to audit when the cited prior-year
            # operand is also available in the final response. Require that
            # operand only when the filing actually contains the comparable
            # period; do not turn missing history into a hard failure.
            for spec in current_period_specs:
                prior_period = _prior_comparable_period(spec.period)
                if prior_period is None:
                    continue
                prior_spec = RequiredFactSpec(
                    spec.company,
                    spec.metric_id,
                    prior_period,
                    "available prior-year operand for an explicitly requested YOY comparison",
                    accounting_basis=spec.accounting_basis,
                )
                if _facts_for_spec(prior_spec, ledger) and prior_spec not in required_specs:
                    required_specs.append(prior_spec)
            required_specs.extend(_growth_specs_for_metrics(current_period_specs, ledger))
        return RequiredFactPlan(scope.value, tuple(required_specs))
    if scope == QueryScope.COMPARE:
        comparison_metrics = list(dict.fromkeys(canonical_metrics(intent_question)))
        if "cash_flow" in comparison_metrics and ledger.lookup(metric_id="operating_cash_flow"):
            comparison_metrics = [
                "operating_cash_flow" if value == "cash_flow" else value
                for value in comparison_metrics
            ]
            comparison_metrics = list(dict.fromkeys(comparison_metrics))
        segment_overview_request = bool(
            re.search(
                r"\b(?:business\s+)?segments?\b|\bbusiness\s+lines\b|"
                r"业务分部|业务板块|各业务|分部情况",
                intent_question,
                re.IGNORECASE,
            )
        )
        if segment_overview_request and not comparison_metrics:
            # A cross-company segment comparison is still a request for the
            # available segment-level metrics, not merely a list of labels.
            # Requiring the ledger facts here lets the production completion
            # path add exact, period-labelled revenue cells (with citations)
            # when a model omits them, while leaving consolidated revenue and
            # net income outside the answer scope.
            segment_metrics = (
                "automotive_revenue",
                "services_revenue",
                "iphone_revenue",
                "products_revenue",
                "mac_revenue",
                "ipad_revenue",
                "wearables_revenue",
                "products_gross_margin",
                "services_gross_margin",
                "data_center_revenue",
                "edge_computing_revenue",
            )
            required_segments = [
                RequiredFactSpec(
                    company,
                    metric_id,
                    period
                    or (
                        _company_reporting_period(ledger, company, metric_id)
                        or _company_reporting_period(ledger, company, None)
                    ),
                    "available segment-level metric for a cross-company segment comparison",
                )
                for company in (companies or [None])
                for metric_id in segment_metrics
                if ledger.lookup(company=company, metric_id=metric_id, period=period)
            ]
            # A broad, cross-company segment comparison needs enough
            # consolidated context to interpret the segment figures.  Keep
            # this opt-in to overview/major-segment wording; a narrow
            # "Data Center revenue" question must not inherit every headline
            # metric from the filing.
            overview_with_headlines = bool(
                re.search(
                    r"\b(?:compare|comparison|summari[sz]e|overview|major|main|key)\b|"
                    r"比较|总结|概览|主要|关键",
                    intent_question,
                    re.IGNORECASE,
                )
            )
            if overview_with_headlines:
                headline_metrics = ["revenue", "net_income", "gross_margin", "eps"]
                if len(companies) > 1:
                    # Apple reports the six-month cash-flow total in this
                    # comparison; include it only when the ledger has such a
                    # period so a company without that disclosure is not
                    # assigned an invented quarterly value.
                    headline_metrics.append("operating_cash_flow")
                for company in companies:
                    for metric_id in headline_metrics:
                        metric_period = period or (
                            _company_reporting_period(ledger, company, metric_id)
                            or _company_reporting_period(ledger, company, None)
                        )
                        available = ledger.lookup(
                            company=company,
                            metric_id=metric_id,
                            period=metric_period,
                        )
                        if metric_id == "operating_cash_flow":
                            available = tuple(
                                fact for fact in available if fact.period_type == "six_months"
                            )
                        if not available:
                            continue
                        required_segments.extend(
                            margin_expanded_specs(
                                company,
                                metric_id,
                                metric_period,
                                "consolidated context for a broad segment comparison",
                            )
                        )
                growth_sources = [
                    spec for spec in required_segments
                    if spec.metric_id == "revenue"
                    or spec.metric_id.endswith("_revenue")
                ]
                required_segments.extend(
                    _growth_specs_for_metrics(growth_sources, ledger, allow_derived=True)
                )
            return RequiredFactPlan(scope.value, tuple(required_segments))
        general_financial_comparison = bool(
            re.search(
                r"\bfinancial\s+(?:performance|results?)\b|\bperform(?:ed|ance)\s+financially\b|"
                r"财务表现|财务业绩|财务状况|经营表现|经营业绩",
                intent_question,
                re.IGNORECASE,
            )
            or re.search(
                r"\b(?:analy[sz]e|review|summari[sz]e)\b.{0,100}\b(?:report|filing|financial)\b"
                r"|分析.{0,24}(?:财报|报告)|报告分析",
                str(question or ""),
                re.IGNORECASE,
            )
        )
        if not comparison_metrics and general_financial_comparison:
            comparison_metrics = [
                "revenue",
                "net_income",
                "gross_margin",
                "operating_margin",
                "operating_cash_flow",
                "eps",
            ]
        if not comparison_metrics:
            # Comparison intent alone does not imply a revenue comparison.
            # Risk, growth-driver, methodology, and business-factor questions
            # are prose comparisons; letting a default revenue requirement
            # leak into them created unrelated fact appends and inconsistent
            # EN/ZH coverage grades.
            if is_growth_narrative_question(intent_question) and len(companies) >= 2:
                # A ranking question still has one common quantitative anchor:
                # each issuer's reported (or deterministically derivable)
                # consolidated revenue growth.  Keep the periods issuer-local
                # and expose them in the answer; never silently align unlike
                # filings or borrow a segment rate for total revenue.
                growth_base: list[RequiredFactSpec] = []
                for company in companies:
                    metric_period = (
                        _company_reporting_period(ledger, company, "revenue")
                        or _company_reporting_period(ledger, company, None)
                    )
                    if metric_period and ledger.lookup(
                        company=company,
                        metric_id="revenue",
                        period=metric_period,
                    ):
                        growth_base.append(
                            RequiredFactSpec(
                                company,
                                "revenue",
                                metric_period,
                                "common quantitative anchor for a cross-company growth ranking",
                            )
                        )
                if len(growth_base) == len(companies):
                    return RequiredFactPlan(
                        scope.value,
                        tuple(growth_base)
                        + tuple(_growth_specs_for_metrics(
                            growth_base,
                            ledger,
                            allow_derived=True,
                        )),
                    )
            return RequiredFactPlan(scope.value, ())
        required_specs: list[RequiredFactSpec] = []
        aligned_periods = (
            _comparison_periods_by_company(ledger, companies)
            if not period
            else {}
        )
        for company in companies:
            for requested_metric in comparison_metrics:
                metric_period = (
                    period
                    or aligned_periods.get(company)
                    or _company_reporting_period(ledger, company, requested_metric)
                    or _company_reporting_period(ledger, company, None)
                )
                required_specs.extend(
                    margin_expanded_specs(
                        company,
                        requested_metric,
                        metric_period,
                        "one partition per named company, metric, and filing period",
                    )
                )
        return RequiredFactPlan(scope.value, tuple(required_specs))
    if scope == QueryScope.SUMMARY:
        headline_candidates = (
            "revenue",
            "automotive_revenue",
            "services_revenue",
            "iphone_revenue",
            "products_revenue",
            "mac_revenue",
            "ipad_revenue",
            "wearables_revenue",
            "energy_revenue",
            "net_income",
            "gross_profit",
            "eps",
            "operating_cash_flow",
            "free_cash_flow",
            "gross_margin",
            "operating_margin",
            "products_gross_margin",
            "services_gross_margin",
            "data_center_revenue",
            "edge_computing_revenue",
        )
        # A summary-shaped sentence can still request one specific metric or
        # segment (e.g. "What does NVIDIA report about Data Center performance?").
        # Do not expand that narrow question into a whole-company financial
        # summary; the broader plan caused extra facts to be appended and made
        # otherwise-correct answers look incomplete. When the query names
        # financial metrics, keep the plan to those named metrics. A true
        # overall-performance question has no metric aliases and retains the
        # headline set below.
        requested_metrics = list(dict.fromkeys(canonical_metrics(intent_question)))
        segment_overview_request = bool(
            re.search(
                r"\b(?:business\s+)?segments?\b|\bbusiness\s+lines\b|"
                r"业务分部|业务板块|各业务|分部情况",
                intent_question,
                re.IGNORECASE,
            )
        )
        if (
            is_nonfinancial_business_development_summary(intent_question)
            and not requested_metrics
        ):
            # Narrative development questions must not inherit every headline
            # metric from the same filing. That caused automatic numeric
            # additions unrelated to the requested business developments.
            return RequiredFactPlan(scope.value, ())
        if segment_overview_request and not requested_metrics:
            # A request to summarize segment disclosures is not a request for
            # the issuer's consolidated headline metrics. Require only the
            # segment-level revenue facts that are actually present in the
            # evidence ledger; this also lets a supported segment fact replace
            # a model's stale "no segment data" refusal without appending
            # unrelated company-wide revenue/net-income figures.
            segment_metrics = (
                "automotive_revenue",
                "services_revenue",
                "iphone_revenue",
                "products_revenue",
                "mac_revenue",
                "ipad_revenue",
                "wearables_revenue",
                "products_gross_margin",
                "services_gross_margin",
                "data_center_revenue",
                "edge_computing_revenue",
            )
            required_segments = [
                RequiredFactSpec(
                    company,
                    metric_id,
                    period or (
                        _company_reporting_period(ledger, company, metric_id)
                        or _company_reporting_period(ledger, company, None)
                    ),
                    "available segment-level metric for a segment overview",
                )
                for company in (companies or [None])
                for metric_id in segment_metrics
                if ledger.lookup(company=company, metric_id=metric_id, period=period)
            ]
            overview_with_headlines = bool(
                re.search(
                    r"\b(?:summari[sz]e|overview|major|main|key)\b|"
                    r"总结|概览|主要|关键",
                    intent_question,
                    re.IGNORECASE,
                )
            )
            if overview_with_headlines:
                headline_metrics = ["revenue", "net_income", "gross_margin", "eps"]
                company = companies[0] if companies else None
                for metric_id in headline_metrics:
                    metric_period = period or (
                        _company_reporting_period(ledger, company, metric_id)
                        or _company_reporting_period(ledger, company, None)
                    )
                    if not ledger.lookup(
                        company=company,
                        metric_id=metric_id,
                        period=metric_period,
                    ):
                        continue
                    required_segments.extend(
                        margin_expanded_specs(
                            company,
                            metric_id,
                            metric_period,
                            "consolidated context for a broad segment overview",
                        )
                    )
                growth_sources = [
                    spec for spec in required_segments
                    if spec.metric_id == "revenue"
                    or spec.metric_id.endswith("_revenue")
                ]
                required_segments.extend(
                    _growth_specs_for_metrics(growth_sources, ledger, allow_derived=True)
                )
            return RequiredFactPlan(scope.value, tuple(required_segments))
        generic_margin_request = bool(
            re.search(r"\bmargins?\b|利润率", intent_question, re.I)
            and not re.search(r"gross|operating|毛利|营业利润", intent_question, re.I)
        )
        if generic_margin_request:
            # A generic follow-up such as "what about margins?" asks about
            # margin disclosures present in the filing, not every headline
            # metric and not margin types the filing does not report.
            requested_metrics = available_generic_margin_metrics() + [
                metric
                for metric in requested_metrics
                if metric not in {"gross_margin", "operating_margin"}
            ]
            if not requested_metrics:
                return RequiredFactPlan(scope.value, ())
        if "cash_flow" in requested_metrics and ledger.lookup(
            metric_id="operating_cash_flow"
        ):
            requested_metrics = [
                "operating_cash_flow" if metric == "cash_flow" else metric
                for metric in requested_metrics
            ]
        candidates = tuple(
            metric for metric in headline_candidates
            if not requested_metrics or metric in requested_metrics
        )
        company = companies[0] if companies else None
        required_items: list[RequiredFactSpec] = []
        for candidate in (requested_metrics or candidates):
            candidate_period = period or (
                (
                    _company_reporting_period(ledger, company, candidate)
                    or _company_reporting_period(ledger, company, None)
                )
                if company
                else None
            )
            # Preserve explicitly requested metrics even when current context
            # lacks them. The prompt must distinguish "not retrieved" from
            # "not requested"; completion still only uses available facts.
            if requested_metrics or ledger.lookup(company=company, metric_id=candidate, period=candidate_period):
                required_items.extend(
                    margin_expanded_specs(
                        company, candidate, candidate_period, "headline summary metric"
                    )
                )
        explicit_growth_requested = bool(
            re.search(
                r"\b(?:y\s*/\s*y|yoy|year[- ]over[- ]year|q\s*/\s*q|qoq|"
                r"quarter[- ]over[- ]quarter|growth|change|increased?|decreased?|"
                r"declined?|fell|rose|up|down|happened)\b|同比|环比|增长|变化|上升|下降|减少|增加",
                intent_question,
                re.IGNORECASE,
            )
        )
        # ``performance`` / ``表现`` is a bilingual summary cue. It should
        # admit filing-reported headline growth, but it is not permission to
        # derive or append every available segment rate.
        summary_growth_requested = explicit_growth_requested or bool(
            re.search(
                r"\bperformance\b|表现|怎么样|做得如何|表现如何",
                intent_question,
                re.IGNORECASE,
            )
        )
        broad_financial_summary = bool(
            not requested_metrics
            and not segment_overview_request
            and not is_nonfinancial_business_development_summary(intent_question)
        )
        if broad_financial_summary or summary_growth_requested:
            # A broad financial-performance summary should include growth
            # rates that the filing explicitly reports, even when the user did
            # not spell out "YoY". Derived rates remain opt-in so a summary
            # never invents extra calculations.
            growth_sources = required_items
            if not explicit_growth_requested and not requested_metrics:
                # Keep a broad summary useful without turning every segment
                # and margin row into a second answer. These are the headline
                # growth measures commonly reported alongside performance;
                # explicitly requested metrics (including a named business
                # such as automotive) retain their filing-reported growth so
                # bilingual "what happened" / "表现如何" queries plan the
                # same evidence without deriving extra rates.
                growth_metrics = {
                    "revenue",
                    "net_income",
                    "eps",
                    "services_revenue",
                    "iphone_revenue",
                    "data_center_revenue",
                    "edge_computing_revenue",
                }
                growth_sources = [
                    spec for spec in required_items if spec.metric_id in growth_metrics
                ]
            required_items.extend(
                _growth_specs_for_metrics(
                    growth_sources,
                    ledger,
                    # A named metric plus a performance-shaped question may
                    # safely derive its YoY rate from matching-period
                    # operands (for example Services Q2 FY2026 vs Q2 FY2025).
                    # Keep broad whole-company summaries conservative: they
                    # admit only filing-reported rates unless growth was
                    # explicitly requested.
                    allow_derived=(
                        explicit_growth_requested
                        or (summary_growth_requested and bool(requested_metrics))
                    ),
                )
            )
        required = tuple(required_items)
        return RequiredFactPlan(
            scope.value,
            required
            or (RequiredFactSpec(companies[0] if companies else None, "revenue", period, "headline summary metric"),),
        )
    return RequiredFactPlan(scope.value, ())


def _fact_alias_present(line: str, metric_id: str) -> bool:
    lowered = line.casefold()
    aliases = metric_aliases(metric_id) or (metric_id,)
    if metric_id == "revenue":
        # A segment's revenue is not evidence for consolidated revenue, even
        # when the same numeric value happens to appear elsewhere in context.
        explicit_total = bool(
            re.search(
                r"\btotal\s+(?:net\s+)?revenues?\b|"
                r"总(?:收入|营收)|营业总收入|合并(?:收入|营收)",
                lowered,
            )
        )
        if explicit_total:
            return True
        segment_markers = (
            "automotive", "services", "service revenue", "data center", "datacenter",
            "data centre", "datacentre", "edge computing", "edge revenue", "segment",
            "product revenue", "iphone", "ipad", "mac revenue", "汽车业务", "服务收入",
            "服务业务", "数据中心", "边缘计算", "分部收入",
        )
        if any(marker in lowered for marker in segment_markers):
            return False
    return any(alias.casefold() in lowered for alias in aliases)


def _number_matches_fact(claim: NormalizedNumber, fact: FinancialFact) -> bool:
    """Compare a claim with a ledger fact without erasing its financial unit."""
    if fact.unit == "percent":
        if claim.kind == "percent":
            return claim.value == fact.normalized_value
        if claim.kind == "basis_points":
            return claim.value / Decimal("100") == fact.normalized_value
        return False
    return numbers_equivalent(
        claim,
        NormalizedNumber(fact.normalized_value, "amount", fact.currency),
    )


_ACCOUNTING_BASIS_MARKER = re.compile(
    r"(?P<non_gaap>non[-\s\u2010-\u2014]?gaap|非\s*gaap|非通用会计准则)"
    r"|(?P<gaap>gaap|通用会计准则)",
    re.IGNORECASE,
)


def _accounting_basis_number_groups(
    line: str,
) -> tuple[tuple[str, tuple[NormalizedNumber, ...]], ...]:
    """Bind EPS numbers to the nearest explicit GAAP basis label.

    A line-level check is unsafe when a sentence contains both labels: a
    reversed ``GAAP 1.87; non-GAAP 2.39`` line contains both correct values,
    but assigns each value to the wrong accounting basis. Split values at the
    labels. For the filing's conventional ``GAAP and non-GAAP ... were X and
    Y, respectively`` wording, distribute the ordered values across the
    ordered labels.
    """

    markers = list(_ACCOUNTING_BASIS_MARKER.finditer(str(line or "")))
    if not markers:
        return ()
    groups: list[tuple[str, tuple[NormalizedNumber, ...]]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(line)
        basis = "non_gaap" if marker.group("non_gaap") else "gaap"
        values = tuple(extract_normalized_numbers(line[marker.end() : end]))
        groups.append((basis, values))
    if (
        len(markers) >= 2
        and all(not values for _, values in groups)
        and re.search(r"\brespectively\b|分别", line, re.IGNORECASE)
    ):
        trailing = tuple(extract_normalized_numbers(line[markers[-1].end() :]))
        if len(trailing) >= len(markers):
            return tuple(
                (
                    "non_gaap" if marker.group("non_gaap") else "gaap",
                    (trailing[index],),
                )
                for index, marker in enumerate(markers)
            )
    return tuple(groups)


def answer_contains_fact(answer: str, spec: RequiredFactSpec, ledger: FactLedger) -> bool:
    """只有指标数值及其公司、期间、类别标签与计划一致，才视为已回答。"""
    facts = _facts_for_spec(spec, ledger)
    if not facts:
        return False
    for line in str(answer or "").splitlines():
        if spec.metric_id == "eps" and spec.accounting_basis:
            named = {canonical_company(company) for company in extract_companies(line)}
            if named and canonical_company(spec.company or "") not in named:
                continue
            named_periods = extract_periods(line)
            if spec.period and named_periods and not any(
                periods_equivalent(period, spec.period) for period in named_periods
            ):
                continue
            if not _fact_alias_present(line, spec.metric_id):
                continue
            for basis, claims in _accounting_basis_number_groups(line):
                if basis != spec.accounting_basis:
                    continue
                if any(
                    _number_matches_fact(claim, fact)
                    for claim in claims
                    for fact in facts
                ):
                    return True
            continue
        if (
            spec.metric_id in {"gross_margin", "operating_margin"}
            and spec.accounting_basis
        ):
            named = {canonical_company(company) for company in extract_companies(line)}
            if named and canonical_company(spec.company or "") not in named:
                continue
            named_periods = extract_periods(line)
            if spec.period and named_periods and not any(
                periods_equivalent(period, spec.period) for period in named_periods
            ):
                continue
            if not _fact_alias_present(line, spec.metric_id):
                continue
            groups = _accounting_basis_number_groups(line)
            if groups:
                claims = tuple(
                    claim
                    for basis, values in groups
                    if basis == spec.accounting_basis
                    for claim in values
                )
                if claims and all(
                    any(_number_matches_fact(claim, fact) for fact in facts)
                    for claim in claims
                ):
                    return True
                continue
            # An unqualified margin defaults to GAAP, but every percentage on
            # that metric line must agree with the GAAP fact. A range that
            # combines GAAP and non-GAAP values is not a valid GAAP answer.
            if spec.accounting_basis != "gaap":
                continue
            claims = tuple(extract_normalized_numbers(line))
            if claims and all(
                claim.kind in {"percent", "basis_points"}
                and any(_number_matches_fact(claim, fact) for fact in facts)
                for claim in claims
            ):
                return True
            continue
        if spec.accounting_basis:
            if spec.accounting_basis == "non_gaap" and not re.search(
                r"\bnon[-\s\u2010-\u2014]?gaap\b|非\s*gaap|非通用会计准则",
                line,
                re.IGNORECASE,
            ):
                continue
            # Unqualified reported margin values use the GAAP basis by
            # default. Never let a line explicitly marked non-GAAP satisfy it.
            if spec.accounting_basis == "gaap" and re.search(
                r"\bnon[-\s\u2010-\u2014]?gaap\b|非\s*gaap|非通用会计准则",
                line,
                re.IGNORECASE,
            ):
                continue
        named = {canonical_company(company) for company in extract_companies(line)}
        if named and canonical_company(spec.company or "") not in named:
            continue
        named_periods = extract_periods(line)
        if spec.period and named_periods and not any(
            periods_equivalent(period, spec.period) for period in named_periods
        ):
            continue
        if not _fact_alias_present(line, spec.metric_id):
            continue
        if not _category_is_named(line, spec.category):
            continue
        if spec.growth_basis and not _growth_basis_present(line, spec.growth_basis):
            continue
        claims = extract_normalized_numbers(line)
        if any(
            _number_matches_fact(claim, fact)
            for claim in claims
            for fact in facts
        ):
            return True
    return False


def remove_mislabeled_eps_claims(
    answer: str,
    plan: RequiredFactPlan,
    ledger: FactLedger,
) -> tuple[str, tuple[str, ...]]:
    """Remove accounting-basis lines that attach values to the wrong basis.

    Numeric grounding alone cannot distinguish a GAAP value from a non-GAAP
    value when both occur in the same filing. For EPS and margin claims, only
    apply this repair when the plan and ledger contain both explicitly labelled
    bases for the same issuer and period. An unqualified margin defaults to
    GAAP, and every percentage in its claim must match that basis; mixed ranges
    are removed rather than relabelled.
    """

    paired_specs: dict[tuple[str | None, str | None], dict[str, tuple[FinancialFact, ...]]] = {}
    for spec in plan.required:
        if (
            spec.metric_id not in {"eps", "gross_margin", "operating_margin"}
            or spec.accounting_basis not in {"gaap", "non_gaap"}
        ):
            continue
        facts = _facts_for_spec(spec, ledger)
        if facts:
            paired_specs.setdefault((spec.company, spec.period), {})[
                spec.accounting_basis
            ] = facts
    paired_specs = {
        key: bases
        for key, bases in paired_specs.items()
        if set(bases) == {"gaap", "non_gaap"}
    }
    if not paired_specs:
        return str(answer or ""), ()

    kept: list[str] = []
    removed: list[str] = []
    for line in str(answer or "").splitlines():
        groups = _accounting_basis_number_groups(line)
        metric_id = next(
            (
                metric
                for metric in ("eps", "gross_margin", "operating_margin")
                if _fact_alias_present(line, metric)
            ),
            None,
        )
        if metric_id is None:
            kept.append(line)
            continue
        is_margin = metric_id in {"gross_margin", "operating_margin"}
        line_numbers = tuple(extract_normalized_numbers(line))
        if is_margin and (
            not line_numbers
            or any(value.kind not in {"percent", "basis_points"} for value in line_numbers)
        ):
            kept.append(line)
            continue
        line_companies = {canonical_company(item) for item in extract_companies(line)}
        line_periods = extract_periods(line)
        candidates = [
            bases
            for (company, period), bases in paired_specs.items()
            if (not line_companies or canonical_company(company or "") in line_companies)
            and (not period or not line_periods or any(
                periods_equivalent(value, period) for value in line_periods
            ))
        ]
        if not candidates:
            kept.append(line)
            continue

        mismatched = False
        if groups:
            for basis, claims in groups:
                if not claims:
                    continue
                matching_facts = tuple(
                    fact
                    for candidate in candidates
                    for fact in candidate.get(basis, ())
                )
                if not matching_facts or any(
                    not any(_number_matches_fact(claim, fact) for fact in matching_facts)
                    for claim in claims
                ):
                    mismatched = True
                    break
        elif is_margin:
            # A margin without a basis label is GAAP by default. Validate the
            # whole metric claim, not just one matching value in a range.
            gaap_facts = tuple(
                fact for candidate in candidates for fact in candidate.get("gaap", ())
            )
            mismatched = not gaap_facts or any(
                not any(_number_matches_fact(claim, fact) for fact in gaap_facts)
                for claim in line_numbers
            )
        if mismatched:
            removed.append(line)
        else:
            kept.append(line)
    return "\n".join(kept).strip(), tuple(removed)


def _growth_basis_present(line: str, basis: str) -> bool:
    if basis == "yoy":
        pattern = (
            r"\b(?:y\s*/\s*y|yoy|year[- ]over[- ]year|from\s+(?:a|the same period a)\s+year\s+ago)\b|"
            r"同比|较上年同期"
        )
    elif basis == "qoq":
        pattern = (
            r"\b(?:q\s*/\s*q|qoq|quarter[- ]over[- ]quarter|"
            r"from\s+(?:the\s+)?previous\s+quarter|sequential(?:ly)?)\b|环比|较上季度"
        )
    else:
        return False
    return bool(re.search(pattern, line, re.IGNORECASE))


def _render_fact(fact: FinancialFact, *, chinese: bool = False) -> str:
    amount = fact.normalized_value
    if chinese and fact.currency and fact.currency.upper() in {"CNY", "RMB"}:
        absolute = abs(amount)
        if absolute >= Decimal("100000000"):
            return f"{_plain_decimal((amount / Decimal('100000000')).quantize(Decimal('0.01')))}亿元人民币"
        if absolute >= Decimal("10000"):
            return f"{_plain_decimal((amount / Decimal('10000')).quantize(Decimal('0.01')))}万元人民币"
        return f"{_plain_decimal(amount.quantize(Decimal('0.01')))}元人民币"
    if fact.display_unit == "million":
        # Explicit period-labelled table cells retain the source statement's
        # readable scale; narrative and legacy flattened rows use the
        # magnitude-based rendering below.
        displayed = amount / Decimal("1000000") if amount >= Decimal("1000000") else amount
        rendered = f"{int(displayed):,}" if displayed == displayed.to_integral_value() else _plain_decimal(displayed)
        return f"{rendered} million"
    if fact.unit == "billion":
        return f"{_plain_decimal(amount / Decimal('1000000000'))} billion"
    if fact.unit == "million":
        return f"{_plain_decimal(amount / Decimal('1000000'))} million"
    if fact.unit == "percent":
        return f"{_plain_decimal(amount)}%"
    return _plain_decimal(amount)


def _plain_decimal(value: Decimal) -> str:
    """Render normalized decimals without exponent notation for user-facing text."""
    return format(value.normalize(), "f")


def _label_unqualified_gaap_margin(
    answer: str, spec: RequiredFactSpec, facts: tuple[FinancialFact, ...]
) -> str:
    """Make the default GAAP basis explicit without duplicating a supported value."""
    output: list[str] = []
    chinese = any("\u3400" <= char <= "\u9fff" for char in answer)
    for line in str(answer or "").splitlines():
        if (
            _fact_alias_present(line, spec.metric_id)
            and not re.search(
                r"\b(?:non[-\s\u2010-\u2014]?gaap|gaap)\b|非\s*gaap|非通用会计准则",
                line,
                re.IGNORECASE,
            )
            and (claims := tuple(extract_normalized_numbers(line)))
            and all(
                claim.kind in {"percent", "basis_points"}
                and any(_number_matches_fact(claim, fact) for fact in facts)
                for claim in claims
            )
        ):
            alias = next(
                (value for value in metric_aliases(spec.metric_id) if value.casefold() in line.casefold()),
                None,
            )
            if alias:
                replacement = f"GAAP{alias}" if chinese else f"GAAP {alias}"
                line = re.sub(re.escape(alias), replacement, line, count=1, flags=re.IGNORECASE)
        output.append(line)
    return "\n".join(output)


def _preferred_fact(
    facts: tuple[FinancialFact, ...],
    metric_id: str,
    *,
    question: str = "",
    requested_period: str | None = None,
) -> FinancialFact:
    """Choose the most authoritative value when one row yields several facts.

    Financial statement chunks commonly contain both a metric's component rows
    (for example depreciation) and its total row.  The ledger keeps both for
    auditability; answer completion must prefer the explicit total/value row
    instead of whichever parser match happened to appear first.
    """

    prefer_non_gaap = bool(
        re.search(r"\bnon[-\s]?gaap\b|非\s*gaap|非通用会计准则", question, re.IGNORECASE)
    )
    prefer_basic_eps = metric_id == "eps" and bool(
        re.search(r"\bbasic\s+(?:earnings\s+per\s+share|eps)\b|基本每股收益", question, re.IGNORECASE)
    )
    prefer_cumulative = bool(
        re.search(
            r"\b(?:six[- ]months?|year[- ]to[- ]date|ytd|first half)\b|"
            r"(?:前六个月|前6个月|上半年|累计)",
            question,
            re.IGNORECASE,
        )
    )
    period_requests_quarter = bool(
        requested_period
        and re.search(r"(?:^|[^A-Z0-9])Q[1-4](?:$|[^A-Z0-9])", requested_period, re.IGNORECASE)
    )
    prefer_quarter = not prefer_cumulative and (period_requests_quarter or bool(
        re.search(
            r"\bq[1-4](?:\s*(?:fy\s*)?20\d{2})?\b|\bquarter(?:ly)?\b|"
            r"[一二三四1-4]\s*季度|季度",
            question,
            re.IGNORECASE,
        )
    ))

    def score(fact: FinancialFact) -> tuple[int, int, float, str]:
        text = fact.evidence_text.casefold()
        section = (fact.section or "").casefold()
        value_row = 0
        if metric_id == "revenue" and len(facts) >= 2:
            # A PDF table row can be emitted more than once by the parser:
            # quarter and YTD columns may share the same normalized period
            # until table-column metadata is resolved.  Prefer the central
            # value cluster for a quarter request; this prevents a cumulative
            # YTD value (for example 254,940) from being used as the prior
            # quarter operand in a derived YoY calculation.
            ordered = sorted(float(item.normalized_value) for item in facts)
            low, high = ordered[0], ordered[-1]
            if high >= low * 1.5 and low > 0:
                # When only one quarter and one YTD duplicate survive
                # retrieval, the quarter operand is the smaller amount and
                # the cumulative operand is the larger amount.
                target = high if prefer_cumulative else low
                value_row += 12 if abs(float(fact.normalized_value) - target) < 1e-6 else -12
            else:
                median = ordered[len(ordered) // 2]
                distance = abs(float(fact.normalized_value) - median)
                spread = max(ordered[-1] - ordered[0], 1.0)
                value_row += 10 if distance <= spread * 0.05 else -10
            # A flattened PDF table can assign the filing-level quarter to
            # an annual-history row as well as the actual quarterly row.  The
            # correctly scoped value is usually repeated across the native
            # table and structured-row chunks, while the annual contamination
            # appears once.  Prefer the repeated cluster without relying on
            # a filename or a question-specific period exception.
            frequency = sum(
                item.normalized_value == fact.normalized_value for item in facts
            )
            value_row += min(frequency * 4, 20)
        if prefer_cumulative:
            value_row += 24 if fact.period_type in {"six_months", "nine_months"} else 0
            value_row -= 24 if fact.period_type == "fiscal_quarter" else 0
        elif prefer_quarter:
            value_row += 24 if fact.period_type == "fiscal_quarter" else 0
            value_row -= 24 if fact.period_type in {"six_months", "nine_months"} else 0
        if metric_id == "operating_cash_flow":
            if re.search(
                r"cash\s+generated\s+by\s+operating\s+activities\s+(?:\$\s*)?[\d,(.-]+",
                text,
            ) or "经营活动现金流" in text:
                value_row += 20
            if any(
                marker in text
                for marker in ("depreciation and amortization", "share-based compensation")
            ):
                value_row -= 10
        elif metric_id == "net_income":
            # The cash-flow reconciliation repeats net income as a six-month
            # subtotal.  Prefer the statement-of-operations row for an
            # unqualified summary instead of that repeated subtotal.
            if (
                "net income attributable to common stockholders" in text
                or re.search(r"\b(?:non[-\s]?gaap|gaap)\b", text)
            ):
                value_row += _accounting_basis_score(text, prefer_non_gaap)
            if text.lstrip().startswith("net income"):
                value_row += 12
            if "operating activities" in section:
                value_row -= 15
            if any(marker in section for marker in ("instruments", "securities")):
                value_row -= 8
        elif metric_id == "eps":
            if "earnings per share" in section or text.lstrip().startswith("earnings per share"):
                value_row += 12
            if section.startswith("numerator"):
                value_row -= 5
            if re.search(r"\bdiluted\b", text):
                value_row += 14 if not prefer_basic_eps else -14
            elif re.search(r"\bbasic\b", text):
                value_row += 14 if prefer_basic_eps else -14
            value_row += _accounting_basis_score(text, prefer_non_gaap)
        elif metric_id in {
            "gross_profit",
            "gross_margin",
            "automotive_gross_margin",
            "operating_income",
            "operating_margin",
        }:
            value_row += _accounting_basis_score(text, prefer_non_gaap)
        elif metric_id == "revenue":
            # Geographic/segment tables often expose a bare ``Net sales``
            # row whose value is a regional subtotal.  Prefer an explicitly
            # labelled consolidated row whenever one is present; otherwise a
            # duplicate table value can become the YoY operand simply because
            # it happens to sort earlier in the ledger.
            if re.search(r"\b(?:total\s+(?:net\s+)?sales|total\s+revenues?)\b", text):
                value_row += 48
            if text.lstrip().startswith(("net sales", "total revenue", "total revenues")):
                value_row += 20
            # Segment/geography tables repeat net sales but are not the
            # consolidated headline revenue requested by a summary question.
            if any(marker in section for marker in ("china", "japan", "asia", "segment")):
                value_row -= 12
            # Risk disclosures can contain the word ``revenue`` and a small
            # duration/threshold amount (for example ``up to 12 months``).
            # Those values are not consolidated revenue and must never win the
            # headline fact merely because they are the smallest duplicate.
            if any(
                marker in section or marker in text
                for marker in (
                    "foreign exchange",
                    "market risk",
                    "risk management",
                    "inventory purchases",
                    "up to 12 m",
                )
            ):
                value_row -= 40
        if fact.table_row_period or fact.table_column_period:
            value_row += 2
        if fact.fact_period:
            value_row += 1
        return (value_row, int(fact.confidence * 1000), float(fact.normalized_value), fact.fact_id)

    return max(facts, key=score)


def _accounting_basis_score(text: str, prefer_non_gaap: bool) -> int:
    scoped = re.match(r"\s*(?P<basis>non[-\s]?gaap|gaap)\b", text, re.IGNORECASE)
    if scoped:
        non_gaap = scoped.group("basis").casefold() != "gaap"
        return 24 if non_gaap == prefer_non_gaap else -12
    non_gaap = bool(re.search(r"\bnon[-\s]?gaap\b", text))
    gaap = bool(re.search(r"\bgaap\b", text)) and not non_gaap
    if non_gaap:
        return 24 if prefer_non_gaap else -12
    if gaap:
        return -12 if prefer_non_gaap else 24
    return 0


def complete_from_fact_ledger(
    answer: str, plan: RequiredFactPlan, ledger: FactLedger,
    *, question: str | None = None, evidence: Iterable[Evidence] | None = None,
    response_language: str | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Complete omitted available facts without another provider call."""

    additions: list[str] = []
    fact_ids: list[str] = []
    labels = {
        "operating_cash_flow": "operating cash flow",
        "cash_paid_for_taxes": "cash paid for income taxes",
        "automotive_revenue": "Automotive revenue",
        "services_revenue": "Services revenue",
        "iphone_revenue": "iPhone revenue",
        "products_revenue": "Products net sales",
        "mac_revenue": "Mac revenue",
        "ipad_revenue": "iPad revenue",
        "wearables_revenue": "Wearables, Home and Accessories revenue",
        "products_gross_margin": "Products gross margin",
        "services_gross_margin": "Services gross margin",
        "energy_revenue": "Energy generation and storage revenue",
        "data_center_revenue": "Data Center revenue",
        "edge_computing_revenue": "Edge Computing revenue",
        "free_cash_flow": "free cash flow",
        "net_income": "net income",
        "gross_profit": "gross profit",
        "revenue": "revenue",
        "eps": "EPS",
        "gross_margin": "gross margin",
        "automotive_gross_margin": "automotive gross margin",
        "operating_margin": "operating margin",
    }
    source_text = str(question if question is not None else answer)
    chinese = (
        response_language == "zh-CN"
        if response_language in {"en", "zh-CN"}
        else any("\u3400" <= char <= "\u9fff" for char in source_text)
    )
    citation_ranks = {str(item.metadata.get("chunk_id", "")): index
                      for index, item in enumerate(evidence or (), 1)}
    zh_labels = {
        "operating_cash_flow": "经营活动现金流",
        "automotive_revenue": "汽车业务收入",
        "services_revenue": "服务业务收入",
        "iphone_revenue": "iPhone收入",
        "products_revenue": "产品净销售额",
        "mac_revenue": "Mac收入",
        "ipad_revenue": "iPad收入",
        "wearables_revenue": "可穿戴设备、家居和配件收入",
        "products_gross_margin": "产品毛利率",
        "services_gross_margin": "服务毛利率",
        "energy_revenue": "能源发电与储能收入",
        "data_center_revenue": "数据中心收入",
        "edge_computing_revenue": "边缘计算收入",
        "free_cash_flow": "自由现金流",
        "net_income": "净利润",
        "gross_profit": "毛利额",
        "revenue": "营收",
        "eps": "每股收益",
        "gross_margin": "毛利率",
        "automotive_gross_margin": "汽车业务毛利率",
        "operating_margin": "营业利润率",
    }
    company_labels = {
        "apple": "Apple",
        "tesla": "Tesla",
        "nvidia": "NVIDIA",
        "microsoft": "Microsoft",
        "moutai": "Kweichow Moutai",
    }
    zh_company_labels = {
        "apple": "苹果",
        "tesla": "特斯拉",
        "nvidia": "英伟达",
        "microsoft": "微软",
        "moutai": "贵州茅台",
    }
    for status in plan.statuses(ledger, answer):
        answer_present = status.answer_present
        derived_value: NormalizedNumber | None = None
        derived_operands: tuple[FinancialFact, FinancialFact] | None = None
        if status.spec.growth_basis == "yoy" and not status.available:
            prior_period = _prior_comparable_period(status.spec.period)
            if prior_period:
                current_facts = ledger.lookup(
                    company=status.spec.company,
                    metric_id=status.spec.metric_id,
                    period=status.spec.period,
                    dimension=status.spec.dimension,
                    category=status.spec.category,
                )
                prior_facts = ledger.lookup(
                    company=status.spec.company,
                    metric_id=status.spec.metric_id,
                    period=prior_period,
                    dimension=status.spec.dimension,
                    category=status.spec.category,
                )
                if current_facts and prior_facts:
                    current_fact = _preferred_fact(
                        current_facts,
                        status.spec.metric_id,
                        question=str(question or ""),
                        requested_period=status.spec.period,
                    )
                    prior_fact = _preferred_fact(
                        prior_facts,
                        status.spec.metric_id,
                        question=str(question or ""),
                        requested_period=prior_period,
                    )
                    derived_value = derived_growth(
                        NormalizedNumber(
                            current_fact.normalized_value,
                            "amount",
                            current_fact.currency,
                        ),
                        NormalizedNumber(
                            prior_fact.normalized_value,
                            "amount",
                            prior_fact.currency,
                        ),
                    )
                    if derived_value is not None:
                        derived_operands = (current_fact, prior_fact)
                        answer_present = False
                        if _growth_basis_present(
                            str(answer or ""), status.spec.growth_basis
                        ):
                            negative_trend = bool(
                                re.search(
                                    r"\b(?:down|decreased|declined|fell|lower)\b|下降|减少|下滑",
                                    str(answer or ""),
                                    re.IGNORECASE,
                                )
                            )
                            for line in str(answer or "").splitlines():
                                for value in extract_normalized_numbers(line):
                                    if value.kind != "percent":
                                        continue
                                    if numbers_equivalent(value, derived_value) or (
                                        negative_trend
                                        and abs(value.value - abs(derived_value.value)) <= Decimal("0.2")
                                    ):
                                        answer_present = True
                                        break
                                if answer_present:
                                    break
        if (
            status.spec.accounting_basis == "gaap"
            and answer_present
            and status.spec.metric_id in {"gross_margin", "operating_margin"}
        ):
            answer = _label_unqualified_gaap_margin(
                answer, status.spec, status.available
            )
        if answer_present and status.spec.metric_id == "net_income":
            # An explicitly labelled non-GAAP value must not satisfy an
            # unqualified net-income requirement (whose default basis is
            # GAAP), and vice versa. Otherwise a model can provide only the
            # adjusted figure and suppress completion of the reported GAAP
            # fact even when the filing contains both.
            prefer_non_gaap = bool(
                re.search(
                    r"\bnon[-\s]?gaap\b|非\s*gaap|非通用会计准则",
                    str(question or ""),
                    re.IGNORECASE,
                )
            )
            basis_facts = tuple(
                fact for fact in status.available
                if _accounting_basis_score(fact.evidence_text.casefold(), prefer_non_gaap) > 0
            )
            if basis_facts:
                answer_present = answer_contains_fact(
                    answer, status.spec, FactLedger(basis_facts)
                )
        if answer_present or (not status.available and derived_value is None):
            continue
        fact = (
            derived_operands[0]
            if derived_operands is not None
            else _preferred_fact(
                status.available,
                status.spec.metric_id,
                question=str(question or ""),
                requested_period=status.spec.period,
            )
        )
        label = (
            zh_labels.get(fact.metric_id, labels.get(fact.metric_id, fact.metric_id))
            if chinese
            else labels.get(fact.metric_id, fact.metric_id)
        )
        if status.spec.category:
            label = f"{status.spec.category}{label}"
        if status.spec.growth_basis:
            growth_value = (
                derived_value.value
                if derived_value is not None
                else fact.normalized_value
            )
            declining = growth_value < 0
            if chinese:
                direction = "变化" if declining else "增长"
                label += f"同比{direction}" if status.spec.growth_basis == "yoy" else f"环比{direction}"
            else:
                direction = "change" if declining else "growth"
                label += f" YoY {direction}" if status.spec.growth_basis == "yoy" else f" QoQ {direction}"
        if status.spec.accounting_basis:
            if chinese:
                label = (
                    f"非GAAP{label}"
                    if status.spec.accounting_basis == "non_gaap"
                    else f"GAAP{label}"
                )
            else:
                label = (
                    f"non-GAAP {label}"
                    if status.spec.accounting_basis == "non_gaap"
                    else f"GAAP {label}"
                )
        if (plan.scope == QueryScope.COMPARE.value or evidence is not None) and fact.fact_period:
            company_label = (
                zh_company_labels.get(fact.company, fact.company)
                if chinese
                else company_labels.get(fact.company, fact.company)
            )
            rendered_period = fact.fact_period.replace("_", " ") if evidence is not None else fact.fact_period
            label = f"{company_label} {rendered_period} {label}"
        if evidence is not None and fact.period_type == "six_months":
            label += "（六个月累计）" if chinese else " (six months cumulative)"
        if derived_value is not None:
            rendered_growth = derived_value.value
            rendered = (
                f"{label}: "
                f"{_plain_decimal(rendered_growth.quantize(Decimal('0.01')))}%"
            )
        elif fact.growth_basis:
            rendered = (
                f"{label}: "
                f"{_plain_decimal(fact.normalized_value.quantize(Decimal('0.01')))}%"
            )
        else:
            localize_currency = response_language == "zh-CN"
            rendered = f"{label}: {_render_fact(fact, chinese=localize_currency)}"
        if evidence is not None:
            if fact.currency and derived_value is None and not (
                response_language == "zh-CN"
                and fact.currency.upper() in {"CNY", "RMB"}
            ):
                rendered += f" {fact.currency.upper()}"
            citation_facts = derived_operands or (fact,)
            ranks = list(dict.fromkeys(
                citation_ranks.get(item.chunk_id)
                for item in citation_facts
                if citation_ranks.get(item.chunk_id) is not None
            ))
            if not ranks:
                continue
            rendered += " " + " ".join(f"[Evidence {rank}]" for rank in ranks)
        additions.append(rendered)
        fact_ids.extend(item.fact_id for item in (derived_operands or (fact,)))
    if not additions:
        return answer, (), ()
    prefix = "补充的已验证事实：" if chinese else "Verified facts: "
    if evidence is not None:
        completed = f"{str(answer).rstrip()}\n\n" + "\n".join(f"- {item}." for item in additions)
    else:
        completed = f"{str(answer).rstrip()}\n\n{prefix}{'; '.join(additions)}."
    return completed, tuple(fact_ids), tuple(additions)


@dataclass(frozen=True)
class GenerationCheck:
    disposition: str
    supported_fact_ids: tuple[str, ...]
    rejected_lines: tuple[str, ...]
    missing_fact_ids: tuple[str, ...]
    completed_answer: str


def check_generation(answer: str, plan: RequiredFactPlan, ledger: FactLedger) -> GenerationCheck:
    """Validate a draft and deterministically complete omitted available facts."""

    rejected: list[str] = []
    supported: list[str] = []
    for line in str(answer or "").splitlines():
        values = extract_normalized_numbers(line)
        if not values:
            continue
        metric = canonical_metric_id(line)
        if metric == "cash_paid_for_taxes" and any(spec.metric_id == "operating_cash_flow" for spec in plan.required):
            rejected.append(line)
            continue
        matched = False
        for spec in plan.required:
            if metric and metric != spec.metric_id:
                continue
            if not _category_is_named(line, spec.category):
                continue
            for fact in ledger.lookup(
                company=spec.company,
                metric_id=spec.metric_id,
                period=spec.period,
                growth_basis=spec.growth_basis,
                dimension=spec.dimension,
                category=spec.category,
            ):
                if any(_number_matches_fact(value, fact) for value in values):
                    supported.append(fact.fact_id)
                    matched = True
        if not matched and metric:
            rejected.append(line)
    completed, added_ids, _ = complete_from_fact_ledger(answer, plan, ledger)
    supported.extend(added_ids)
    missing = tuple(
        fact.fact_id
        for status in plan.statuses(ledger, completed)
        if status.available and not status.answer_present
        for fact in status.available[:1]
    )
    disposition = "REJECT" if rejected else ("COMPLETE" if added_ids else "KEEP")
    return GenerationCheck(disposition, tuple(dict.fromkeys(supported)), tuple(rejected), missing, completed)


def safe_answer_from_fact_ledger(
    answer: str, plan: RequiredFactPlan, ledger: FactLedger
) -> tuple[str, tuple[str, ...]]:
    """Remove numeric lines that cannot be proven by a planned ledger fact."""

    # 先按完整必答规格验证每个数字片段；类别比较时，缺少类别标签也不能作为安全答案保留。

    removed: list[str] = []
    output: list[str] = []

    def fragment_is_supported(fragment: str) -> bool:
        values = extract_normalized_numbers(fragment)
        if not values:
            return True
        metric = canonical_metric_id(fragment)
        candidates = [
            fact
            for spec in plan.required
            if (not metric or metric == spec.metric_id)
            and _category_is_named(fragment, spec.category)
            for fact in _facts_for_spec(spec, ledger)
        ]
        if any(spec.category for spec in plan.required) and not any(
            spec.category and _category_is_named(fragment, spec.category)
            for spec in plan.required
        ):
            return False
        if any(value.kind == "percent" for value in values):
            for spec in plan.required:
                if spec.growth_basis != "yoy" or not spec.period:
                    continue
                prior_period = _prior_comparable_period(spec.period)
                if prior_period is None:
                    continue
                current = ledger.lookup(
                    company=spec.company,
                    metric_id=spec.metric_id,
                    period=spec.period,
                    dimension=spec.dimension,
                    category=spec.category,
                )
                prior = ledger.lookup(
                    company=spec.company,
                    metric_id=spec.metric_id,
                    period=prior_period,
                    dimension=spec.dimension,
                    category=spec.category,
                )
                for current_fact in current:
                    for prior_fact in prior:
                        derived = derived_growth(
                            NormalizedNumber(current_fact.normalized_value, "amount", current_fact.currency),
                            NormalizedNumber(prior_fact.normalized_value, "amount", prior_fact.currency),
                        )
                        if derived and any(numbers_equivalent(value, derived) for value in values):
                            return True
        return all(
            any(_number_matches_fact(value, fact) for fact in candidates)
            for value in values
        )

    for line in str(answer or "").splitlines():
        values = extract_normalized_numbers(line)
        if not values:
            output.append(line)
            continue
        fragments = [
            part
            for part in re.split(r"(?<=[。；！!？?])\s*|(?<!\d)\.(?=\s|$)", line)
            if part
        ]
        if len(fragments) == 1 and ";" in line:
            fragments = [part for part in line.split(";") if part]
        supported_fragments = [fragment for fragment in fragments if fragment_is_supported(fragment)]
        if len(supported_fragments) == len(fragments):
            output.append(line)
        else:
            removed.append(line)
            if supported_fragments:
                output.append(" ".join(supported_fragments))
            else:
                output.append(
                    "证据不足，无法可靠支持该数字结论。"
                    if any("\u3400" <= char <= "\u9fff" for char in line)
                    else "Insufficient evidence to support this numeric claim."
                )
    return "\n".join(output).strip(), tuple(removed)
