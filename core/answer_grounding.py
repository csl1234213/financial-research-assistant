"""Production answer grounding and conservative response sanitization.

This module sits after provider generation and before report/API serialization.
It is deterministic and provider-free: a raw model answer can only retain a
numeric claim when the filtered evidence contains the same normalized value or
when a derived percentage is reproducibly calculated from evidence operands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from agent.planning.entity_extractor import extract_companies
from agent.reasoning_models import Evidence
from core.citation_gate import filter_evidence_for_query
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
    canonical_metric,
    canonical_metrics,
    derived_growth,
    extract_normalized_numbers,
    numbers_equivalent,
)
from core.growth_driver_evidence import (
    extract_growth_driver_passages,
    is_growth_narrative_question,
)
from core.required_fact_plan import (
    _company_reporting_period,
    _growth_basis_present,
    _preferred_fact,
    _prior_comparable_period,
)
from core.typesafe_citation import CitationAction, CitationJudgment, judge_citation
from retrieval.periods import extract_annual_periods, extract_periods, period_scoped_row_numbers

_GUIDANCE_CUE = re.compile(
    r"\b(?:guidance|outlook|forecast|project(?:ed|ion)?|expect(?:ed|s)?|"
    r"anticipat(?:ed|es|e))\b|预期|预计|指引|展望|预测",
    re.IGNORECASE,
)
_RISK_QUERY_CUE = re.compile(
    r"(?i)\b(?:risk|risks|challenge|challenges|threat|threats|constraint|constraints)\b|"
    r"风险|挑战|威胁|约束|限制"
)
_SAFE_GROUNDING_REFUSAL = re.compile(
    r"(?i)^(?:insufficient evidence(?: to support this (?:numeric )?claim)?\.?|"
    r"the cited filing evidence is insufficient to support this statement\.?|"
    r"the retrieved passages are insufficient to establish this information\.?|"
    r"the retrieved passages are insufficient to answer this question reliably\.?|"
    r"the cited filing excerpts do not establish a complete cross-company growth ranking\.?|"
    r"the cited filing excerpts provide related context but do not explicitly "
    r"attribute it to growth in the requested reporting period\.?|"
    r"the cited filing contains general risk disclosures but does not identify "
    r"risks specific to the requested reporting period\.?|"
    r"no relevant uploaded-filing evidence was retrieved.*|"
    r"the available filing evidence does not establish the requested metric: [\w -]+\.?|"
    r"[-*]?\s*[A-Za-z][\w .-]*\s*:?[ \t]*(?:not available in the cited filing)\.?|"
    r"upload the relevant company's filing for the requested period and try again\.?|"
    r"证据不足(?:，无法可靠支持该(?:数字)?结论)?。?|"
    r"所引财报证据不足以支持该表述。?|"
    r"当前检索到的证据不足以确认该信息。?|"
    r"当前检索到的证据不足以可靠回答该问题。?|"
    r"现有财报摘录不足以建立完整的跨公司增长排名。?|"
    r"现有财报摘录仅提供相关背景，未明确将其归因于所询报告期的增长。?|"
    r"现有财报摘录包含一般风险披露，但未明确对应所询报告期。?|"
    r"现有财报证据未能证明所询[^，。]*，无法可靠作答。?|"
    r"[-*]?\s*[^，。:：]+：现有财报摘录未提供。?|"
    r"请上传相关公司及报告期的财报后再试。?|"
    r"当前可检索的上传财报中没有找到足以支持该问题的证据.*)$"
)
_STANDARD_REFUSAL_PLACEHOLDERS = (
    re.compile(r"(?i)Insufficient evidence to support this numeric claim\.?"),
    re.compile(r"(?i)The cited filing evidence is insufficient to support this statement\.?"),
    re.compile(r"(?i)The retrieved passages are insufficient to establish this information\.?"),
    re.compile(r"(?i)The retrieved passages are insufficient to answer this question reliably\.?"),
    re.compile(r"证据不足，无法可靠支持该数字结论。?"),
    re.compile(r"所引财报证据不足以支持该表述。?"),
    re.compile(r"当前检索到的证据不足以确认该信息。?"),
    re.compile(r"当前检索到的证据不足以可靠回答该问题。?"),
)
_QUALITATIVE_STOP_WORDS = {
    "according", "and", "are", "as", "at", "by", "company", "did", "does", "during",
    "filing", "for", "from", "in", "include", "includes", "is", "it", "its", "of",
    "on", "or", "report", "reported", "reporting", "says", "showed", "shows", "states",
    "stated", "the", "their", "this", "those", "to", "was", "were", "which", "with",
    "disclosed", "discloses", "mentions", "mentioned", "indicates", "indicated",
}
_QUALITATIVE_CAUSAL_CUE = re.compile(
    r"(?i)\b(?:because|due\s+to|driven\s+by|result(?:ed|ing)?\s+from|caused\s+by|"
    r"led\s+to|attributable\s+to|reflect(?:s|ed|ing)?)\b|"
    r"因(?:为|由)|由于|导致|带动|推动|促使|归因于|反映"
)
_QUALITATIVE_POSITIVE_TREND = re.compile(
    r"(?i)\b(?:increas\w*|grew|growth|rose|rising|up|higher|improv\w*|strengthen\w*)\b|"
    r"增长|增加|上升|提高|改善|增强"
)
_QUALITATIVE_NEGATIVE_TREND = re.compile(
    r"(?i)\b(?:decreas\w*|declin\w*|fell|falling|down|lower|drop\w*|weak\w*|contract\w*)\b|"
    r"下降|减少|下跌|降低|疲软|收缩|減少|下滑"
)
_QUALITATIVE_INTENSITY = re.compile(
    r"(?i)\b(?:record(?:ed)?|strong(?:ly)?|significant(?:ly)?|substantial(?:ly)?|"
    r"sharp(?:ly)?|dramatic(?:ally)?|unprecedented|highest|lowest|robust|material(?:ly)?)\b|"
    r"创纪录|显著|大幅|急剧|强劲|最高|最低|空前|重大"
)


def _is_guidance(text: str) -> bool:
    return bool(_GUIDANCE_CUE.search(text or ""))


def _guidance_claim_allowed(question: str, line: str) -> bool:
    """Guidance values support claims only when both query and claim ask/state it."""
    return _is_guidance(question) and _is_guidance(line)


@dataclass(frozen=True)
class GroundingClaim:
    text: str
    disposition: str  # SUPPORTED, DERIVABLE, UNCERTAIN, UNSUPPORTED, NON_NUMERIC


@dataclass(frozen=True)
class GroundingResult:
    answer: str
    evidence: list[Evidence]
    claims: list[GroundingClaim]
    judgments: list[CitationJudgment] = field(default_factory=list)

    @property
    def unsupported_count(self) -> int:
        return sum(claim.disposition == "UNSUPPORTED" for claim in self.claims)

    @property
    def supported_count(self) -> int:
        return sum(claim.disposition == "SUPPORTED" for claim in self.claims)

    @property
    def derivable_count(self) -> int:
        return sum(claim.disposition == "DERIVABLE" for claim in self.claims)

    @property
    def uncertain_count(self) -> int:
        return sum(claim.disposition == "UNCERTAIN" for claim in self.claims)


def _close_percentage(left: NormalizedNumber, right: NormalizedNumber) -> bool:
    return abs(left.value - right.value) <= Decimal("0.2")


def _close_growth_claim(claim: NormalizedNumber, derived: NormalizedNumber, line: str) -> bool:
    """Match prose such as ``down 12.5%`` to a signed derived -12.5%."""
    if _close_percentage(claim, derived):
        return True
    negative = bool(_QUALITATIVE_NEGATIVE_TREND.search(line))
    return negative and _close_percentage(claim, NormalizedNumber(abs(derived.value), derived.kind, derived.currency))


def _ordered_growth_operands(
    claims: list[NormalizedNumber], line: str,
) -> tuple[NormalizedNumber, NormalizedNumber] | None:
    """Read an explicit ``from older to newer`` pair from a claim clause."""

    amounts = [item for item in claims if item.kind == "amount"]
    lowered = line.casefold()
    ordered_transition = (
        ("from" in lowered and " to " in lowered)
        or ("between" in lowered and " and " in lowered)
        or ("从" in line and any(token in line for token in ("到", "至")))
        or ("由" in line and any(token in line for token in ("增至", "升至", "变为")))
    )
    if len(amounts) != 2 or not ordered_transition:
        return None
    # Return (current, prior); the source amount order in an explicit
    # "from A to B" phrase is chronological, not retrieval-rank order.
    return amounts[1], amounts[0]


def _supports_derived(
    claims: list[NormalizedNumber], evidence: list[NormalizedNumber], line: str = "",
) -> bool:
    percent_claims = [claim for claim in claims if claim.kind == "percent"]
    amounts = [item for item in evidence if item.kind == "amount"]
    if not percent_claims or len(amounts) < 2:
        return False
    derived_values = []
    ordered_operands = _ordered_growth_operands(claims, line)
    if ordered_operands:
        derived = derived_growth(*ordered_operands)
        if derived is not None:
            derived_values.append(derived)
    for index, left in enumerate(amounts):
        for right in amounts[index + 1 :]:
            derived = derived_growth(left, right)
            if derived is None:
                continue
            derived_values.append(derived)
    return all(any(numbers_equivalent(claim, item) for item in evidence)
               or any(_close_growth_claim(claim, value, line) for value in derived_values)
               for claim in percent_claims)


def _line_disposition(
    line: str,
    evidence_numbers: list[NormalizedNumber],
) -> str:
    claims = extract_normalized_numbers(line)
    if not claims:
        return "NON_NUMERIC"
    if all(
        any(numbers_equivalent(claim, item) for item in evidence_numbers)
        for claim in claims
    ):
        return "SUPPORTED"
    # A derived percentage may coexist with directly stated operand amounts,
    # but every direct amount must still be present.  Do not let a valid
    # growth calculation rescue an unrelated/wrong-period amount on the same
    # line.
    direct_claims = [claim for claim in claims if claim.kind == "amount"]
    if direct_claims and not all(
        any(numbers_equivalent(claim, item) for item in evidence_numbers)
        for claim in direct_claims
    ):
        return "UNSUPPORTED"
    if _supports_derived(claims, evidence_numbers, line):
        return "DERIVABLE"
    return "UNSUPPORTED"


def _company_aliases(company: str) -> set[str]:
    aliases = {
        "nvidia": {"nvidia", "英伟达", "英伟达公司", "nvda"},
        "apple": {"apple", "苹果", "苹果公司"},
        "tesla": {"tesla", "特斯拉"},
        "microsoft": {"microsoft", "微软"},
        "moutai": {
            "moutai", "kweichow moutai", "贵州茅台", "贵州茅台酒股份有限公司", "茅台", "600519",
        },
    }
    lowered = (company or "").casefold()
    return aliases.get(lowered, {lowered} if lowered else set())


def _line_mentions_company(line: str, company: str | None) -> bool:
    aliases = _company_aliases(str(company or ""))
    line_lower = line.casefold()
    return bool(aliases and any(alias.casefold() in line_lower for alias in aliases))


def _qualitative_tokens(text: str) -> set[str]:
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", str(text or ""))
    }
    tokens.difference_update(_QUALITATIVE_STOP_WORDS)
    generic_cjk = {"公司", "财报", "報告", "报告", "季度", "期间", "方面", "表示", "提到"}
    for run in re.findall(r"[\u3400-\u9fff]{2,}", str(text or "")):
        tokens.update(
            run[index:index + 2]
            for index in range(len(run) - 1)
            if run[index:index + 2] not in generic_cjk
        )
    return tokens


def _qualitative_relation_compatible(claim: str, source: str) -> bool:
    """Do not ground direction, causality, or intensity absent from the source."""
    if _QUALITATIVE_CAUSAL_CUE.search(claim) and not _QUALITATIVE_CAUSAL_CUE.search(source):
        return False
    if _QUALITATIVE_POSITIVE_TREND.search(claim) and not _QUALITATIVE_POSITIVE_TREND.search(source):
        return False
    if _QUALITATIVE_NEGATIVE_TREND.search(claim) and not _QUALITATIVE_NEGATIVE_TREND.search(source):
        return False
    if _QUALITATIVE_INTENSITY.search(claim) and not _QUALITATIVE_INTENSITY.search(source):
        return False
    return True


def _qualitative_metrics_compatible(claim: str, source: str) -> bool:
    """Do not treat adjacent financial metrics as interchangeable prose."""
    claim_metrics = set(canonical_metrics(claim))
    source_metrics = set(canonical_metrics(source))
    # Narrative driver evidence can support a causal explanation without
    # naming a ledger metric. For multi-metric claims, evidence is assessed as
    # a set below: a revenue passage and a margin passage may jointly support
    # one sentence, while an operating-margin passage alone cannot support a
    # gross-margin claim.
    return not claim_metrics or not source_metrics or bool(claim_metrics & source_metrics)


def _qualitative_support_items(
    question: str,
    line: str,
    cited: list[Evidence],
) -> list[Evidence]:
    """Keep only cited chunks with a minimal lexical tie to a prose claim.

    Citation markers are often copied onto an entire paragraph by a provider.
    For non-numeric clauses there is no value-based check, so retaining every
    cited chunk falsely presents unrelated pages as support.  This deliberately
    conservative overlap check is only a citation-selection aid: it never
    invents support and leaves a clause uncited when no chunk is plausibly
    related.
    """

    words = _qualitative_tokens(line)
    if not words:
        return []
    claim_metrics = set(canonical_metrics(line))
    scored: list[tuple[int, int, Evidence, set[str]]] = []
    for index, item in enumerate(cited):
        requested_periods = extract_periods(question)
        if requested_periods and not (
            str(item.metadata.get("semantic_support", "")).casefold()
            == "related_context"
            and _RISK_QUERY_CUE.search(question or "")
        ):
            # A company/report match is not enough for a period-specific prose
            # claim: narrative elsewhere in a later filing must not be cited
            # as evidence about the requested quarter. Structured numeric
            # rows are validated separately against their exact column period.
            evidence_periods = set(extract_periods(item.content))
            for key in (
                "fact_period",
                "table_column_period",
                "evidence_row_period",
                "period",
                "periods",
                "quarter",
                "reporting_period",
                "document_reporting_period",
            ):
                evidence_periods.update(extract_periods(str(item.metadata.get(key, ""))))
            claim_periods = extract_periods(line)
            if claim_periods and not any(
                periods_equivalent(claim, requested)
                for claim in claim_periods
                for requested in requested_periods
            ):
                continue
            if not any(
                periods_equivalent(found, requested)
                for found in evidence_periods
                for requested in requested_periods
            ):
                continue
        if not _qualitative_relation_compatible(line, item.content):
            continue
        if not _qualitative_metrics_compatible(line, item.content):
            continue
        content_words = _qualitative_tokens(item.content)
        overlap = len(words & content_words)
        coverage = overlap / len(words) if words else 0
        source_metrics = set(canonical_metrics(item.content))
        minimum = 1 if len(words) == 1 else 2
        # A sentence that explicitly asserts several metrics can be supported
        # by several focused passages. Do not demand that every passage repeat
        # every metric, but require the selected evidence set to cover them all.
        metric_match = bool(claim_metrics & source_metrics)
        if overlap >= minimum and (
            coverage >= 0.45 or (len(claim_metrics) > 1 and metric_match)
        ):
            scored.append((overlap, -index, item, source_metrics))
    if not scored:
        return []
    # One shared token is too weak for generic prose (e.g. "report"); require
    # two matches unless the claim contains only one meaningful token.
    minimum = 1 if len(words) == 1 else 2
    if len(claim_metrics) > 1:
        metric_candidates = [
            candidate for candidate in scored if claim_metrics & candidate[3]
        ]
        covered_metrics = set().union(
            *(claim_metrics & candidate[3] for candidate in metric_candidates)
        ) if metric_candidates else set()
        if metric_candidates:
            if not claim_metrics.issubset(covered_metrics):
                return []
            selected: list[Evidence] = []
            remaining = set(claim_metrics)
            for _, _, item, source_metrics in sorted(
                metric_candidates, key=lambda candidate: (-candidate[0], -candidate[1])
            ):
                newly_covered = remaining & source_metrics
                if newly_covered:
                    selected.append(item)
                    remaining.difference_update(newly_covered)
                if not remaining:
                    break
            return selected

    best = max(score for score, _, _, _ in scored)
    # Do not attach a second citation merely because its overlap is almost as
    # high as the best one. Each citation must independently be the strongest
    # lexical match for this clause; numeric claims use the stricter exact-fact
    # selector below instead.
    return [item for score, _, item, _ in scored if score == best and score >= minimum]


def _is_verbatim_cited_excerpt(line: str, cited: list[Evidence]) -> bool:
    """Return whether a REVIEW line is an exact, explicitly quoted excerpt."""

    if not re.search(r"[\"“”‘’]", line):
        return False
    quote_parts = re.findall(r"[\"“‘](.+?)[\"”’]", line)
    if not quote_parts:
        return False
    def normalize(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()
    return any(
        normalize(quote) and normalize(quote) in normalize(item.content)
        for quote in quote_parts
        for item in cited
    )


def _numbers_for_line(
    line: str,
    item: Evidence,
    metric_override: str | None = None,
    allow_guidance: bool = False,
    requested_periods: Iterable[str] = (),
) -> list[NormalizedNumber]:
    """Return evidence numbers scoped to a claim period/table row when possible."""

    periods = list(extract_periods(line))
    if not periods:
        # Chinese annual questions commonly say ``2025年度`` rather than
        # ``FY2025``. Resolve that explicit claim period before falling back
        # to filing-date metadata such as ``2025-12-31``. The fact ledger
        # stores annual facts as ``FY2025``; the filing date is not a period key.
        periods = list(extract_annual_periods(line))
    inferred_from_metadata = False
    inferred_from_query = False
    requested_periods = tuple(requested_periods)
    if not periods and len(requested_periods) == 1:
        # A single explicit question period is the safe default for omitted
        # periods in answer bullets. This is especially important when a
        # filing contains a historical comparative table but its document
        # metadata names a later reporting quarter.
        periods = [requested_periods[0]]
        inferred_from_query = True
    if not periods:
        # When a filing's document period is explicit in metadata, use that
        # period as the default column for an unqualified claim.  This avoids
        # accepting a later comparative column (for example Q4) merely because
        # it happens to be in a Q2 filing chunk.
        metadata_period = str(item.metadata.get("quarter", ""))
        if metadata_period:
            periods = [metadata_period.replace("-", "_")]
            inferred_from_metadata = True
    metric = canonical_metric_id(line) or metric_override or canonical_metric(line)
    if metric == "cash_flow":
        metric = "operating_cash_flow"
    # The same parsed rows used to build context carry units and comparative
    # column periods. Raw text scanning loses both (22,496 in a millions table
    # must support $22.496B, but not the neighbouring Q4 column).
    full_ledger = FactLedger.from_evidence([item])
    guidance_facts = tuple(fact for fact in full_ledger.facts if _is_guidance(fact.evidence_text))
    ledger = FactLedger(
        fact for fact in full_ledger.facts
        if allow_guidance or not _is_guidance(fact.evidence_text)
    )
    # A single provider sentence can contain several explicitly named facts
    # (for example net income, depreciation and operating cash flow).  The
    # former implementation selected only the first metric alias and then
    # rejected the other, still-cited operands as unsupported.  Collect every
    # metric whose alias is actually present in the sentence so each operand
    # remains bounded by the same period/table evidence.
    line_lower = line.casefold()
    mentioned_metrics = {
        metric_id
        for metric_id in {fact.metric_id for fact in ledger.facts}
        if any(alias.casefold() in line_lower for alias in metric_aliases(metric_id))
    }
    if metric:
        mentioned_metrics.add(metric)
    metric_facts = tuple(
        fact for fact in ledger.facts if fact.metric_id in mentioned_metrics
    ) if mentioned_metrics else ()
    if metric_facts:
        cumulative_markers = re.compile(
            r"\b(?:six[- ]months?|nine[- ]months?|year[- ]to[- ]date|ytd|first half)\b|"
            r"前\s*六\s*个?月|上半年|累计",
            re.IGNORECASE,
        )
        line_is_cumulative = bool(cumulative_markers.search(line))
        # Comparative Apple filings expose both quarterly and YTD values in
        # the same metric row. A Q2 summary must not accept the YTD net income
        # merely because it shares the same fiscal-period label. Cash-flow
        # questions are the explicit exception: the source contract may call
        # for the six-month operating cash-flow total.
        def duration_compatible(fact: FinancialFact) -> bool:
            if fact.period_type in {"six_months", "nine_months", "fiscal_year"}:
                if line_is_cumulative:
                    return True
                return fact.metric_id in {
                    "operating_cash_flow",
                    "free_cash_flow",
                    "cash_paid_for_taxes",
                }
            if line_is_cumulative and fact.period_type == "fiscal_quarter":
                return False
            return True

        metric_facts = tuple(fact for fact in metric_facts if duration_compatible(fact))
        scoped_facts = tuple(
            fact for fact in metric_facts
            if not periods or any(
                fact in ledger.lookup(
                    metric_id=fact.metric_id,
                    period=period,
                    growth_basis=fact.growth_basis,
                )
                for period in periods
            )
        )
        if scoped_facts:
            numbers = [
                NormalizedNumber(fact.normalized_value,
                                 "percent" if fact.unit == "percent" else "amount", fact.currency)
                for fact in scoped_facts
            ]
            # Narrative growth percentages belong to the matching metric's
            # own clause; they cannot borrow values from another metric row.
            for fact in scoped_facts:
                numbers.extend(number for number in extract_normalized_numbers(fact.evidence_text)
                               if number.kind in {"percent", "basis_points"})
            # Structured rows intentionally keep only the requested metric.
            # A cited narrative/table clause can also include directly stated
            # adjustment operands (depreciation, SBC, comparative columns)
            # that are present in the same chunk but not emitted as separate
            # ledger facts.  Supplement only when every claim number is
            # literally present in that chunk; this cannot rescue a wrong
            # value or an unrelated citation.
            raw_numbers = extract_normalized_numbers(item.content)
            supported_fact_numbers = [
                NormalizedNumber(fact.normalized_value,
                                 "percent" if fact.unit == "percent" else "amount", fact.currency)
                for fact in scoped_facts
            ]
            guidance_numbers = [number for fact in guidance_facts
                                for number in extract_normalized_numbers(fact.evidence_text)]
            # Flattened filing tables often omit the ``$ in millions`` unit
            # from the extracted row text.  When the same chunk's structured
            # facts establish a million-scale table, add a scoped million
            # interpretation for unscaled raw amounts.  It is used only when
            # every claim number matches a value in this exact chunk.
            if (
                any(fact.unit == "billion" for fact in ledger.facts)
                or "million" in item.content.casefold()
                or "millions" in str(item.metadata.get("table_context", "")).casefold()
                or any(
                    marker in str(item.metadata.get("table_context", ""))
                    for marker in ("Three Months Ended", "Six Months Ended")
                )
            ):
                raw_numbers = raw_numbers + [
                    NormalizedNumber(
                        number.value * Decimal("1000000"),
                        number.kind,
                        "usd" if number.kind == "amount" and number.currency is None else number.currency,
                        number.quantum * Decimal("1000000")
                        if number.kind == "amount" and number.quantum is not None
                        else number.quantum,
                    )
                    for number in raw_numbers
                    if number.kind == "amount" and number.currency is None
                ]
            supplemental_raw_numbers = raw_numbers
            content_periods = extract_periods(item.content)
            if len(periods) == 1 and any(
                not periods_equivalent(content_period, periods[0])
                for content_period in content_periods
            ):
                # A comparative filing chunk may contain several values for
                # the same metric. The parsed fact ledger above is period
                # scoped, but supplementing it with every raw number from the
                # chunk would re-introduce neighboring-quarter values (for
                # example accepting Tesla Q4 revenue as if it were its Q2
                # result). Keep raw-text recovery bounded to the proven table
                # column; if the row/column cannot be mapped, do not use raw
                # numbers as a fallback.
                supplemental_raw_numbers = period_scoped_row_numbers(
                    item.content, periods[0], metric,
                )
                if supplemental_raw_numbers and (
                    any(fact.unit == "billion" for fact in ledger.facts)
                    or "million" in item.content.casefold()
                    or "millions" in str(item.metadata.get("table_context", "")).casefold()
                    or any(
                        marker in str(item.metadata.get("table_context", ""))
                        for marker in ("Three Months Ended", "Six Months Ended")
                    )
                ):
                    supplemental_raw_numbers = supplemental_raw_numbers + [
                        NormalizedNumber(
                            number.value * Decimal("1000000"),
                            number.kind,
                            "usd" if number.kind == "amount" and number.currency is None else number.currency,
                            number.quantum * Decimal("1000000")
                            if number.kind == "amount" and number.quantum is not None
                            else number.quantum,
                        )
                        for number in supplemental_raw_numbers
                        if number.kind == "amount" and number.currency is None
                    ]
            line_numbers = extract_normalized_numbers(line)
            if line_numbers and all(
                any(numbers_equivalent(claim, raw) for raw in raw_numbers)
                for claim in line_numbers
            ):
                numbers.extend(
                    raw for raw in supplemental_raw_numbers
                    if allow_guidance
                    or not any(numbers_equivalent(raw, guidance) for guidance in guidance_numbers)
                    or any(numbers_equivalent(raw, supported) for supported in supported_fact_numbers)
                )
            # A YoY claim is a deterministic relation between the requested
            # period and its matching prior-year operand.  The ordinary
            # period scope intentionally keeps neighbouring table columns
            # out; for an explicit growth clause, add only that one prior
            # period from the same parsed row so the validator can calculate
            # the percentage without admitting unrelated quarters/YTD cells.
            if _growth_basis_present(line, "yoy"):
                current_period = periods[0] if len(periods) == 1 else None
                if current_period:
                    prior_period = _prior_comparable_period(current_period)
                    if prior_period:
                        numbers.extend(
                            NormalizedNumber(
                                fact.normalized_value,
                                "percent" if fact.unit == "percent" else "amount",
                                fact.currency,
                            )
                            for fact in ledger.facts
                            if fact.metric_id in mentioned_metrics
                            and periods_equivalent(fact.fact_period, prior_period)
                            and fact.growth_basis is None
                        )
                    # A bare ``YoY`` column is not tied to every quarter in a
                    # comparative row.  Keep a reported rate only when the
                    # parser bound it to this exact claim period; otherwise
                    # the percentage must be proven from two operands below.
                    has_period_bound_rate = any(
                        fact.growth_basis
                        and periods_equivalent(fact.fact_period, current_period)
                        for fact in ledger.facts
                        if fact.metric_id in mentioned_metrics
                    )
                    if not has_period_bound_rate:
                        numbers = [
                            number for number in numbers
                            if number.kind not in {"percent", "basis_points"}
                        ]
            return numbers
        if not inferred_from_metadata and not inferred_from_query:
            # Structured rows can miss a period when a flattened table has
            # several adjacent columns.  Fail closed unless the explicitly
            # cited chunk itself contains every claimed operand; in that case
            # the raw table text is still a valid, bounded source.
            raw_numbers = extract_normalized_numbers(item.content)
            if any(
                marker in str(item.metadata.get("table_context", ""))
                for marker in ("Three Months Ended", "Six Months Ended")
            ):
                raw_numbers = raw_numbers + [
                    NormalizedNumber(
                        number.value * Decimal("1000000"), number.kind, "usd",
                        number.quantum * Decimal("1000000")
                        if number.quantum is not None else None,
                    )
                    for number in raw_numbers
                    if number.kind == "amount" and number.currency is None and abs(number.value) >= 1000
                ]
            line_numbers = extract_normalized_numbers(line)
            if line_numbers and all(
                any(numbers_equivalent(claim, raw) for raw in raw_numbers)
                for claim in line_numbers
            ):
                return raw_numbers
            return []
    elif metric and ledger.facts:
        # Narrative chunks may advertise a metric in retrieval metadata while
        # the table parser has no structured row for it (for example NVIDIA's
        # ``Data Center compute revenue`` paragraph).  If the chunk is already
        # semantically filtered to the requested filing period, retain only
        # the raw numbers from that chunk; do not fall back to unrelated
        # chunks or to a different reporting period.
        advertised = {
            token.strip().casefold()
            for token in str(item.metadata.get("metrics", "")).split("|")
            if token.strip()
        }
        if metric in advertised and (
            inferred_from_metadata
            or not periods
            or periods[0] in extract_periods(item.content)
        ):
            return extract_normalized_numbers(item.content)
        return []
    elif metric and not ledger.facts:
        if guidance_facts and not allow_guidance:
            return []
        # A narrative-only chunk can have no structured ledger rows at all.
        # Retrieval metadata still records the matched metric and filing
        # period; use that scoped paragraph rather than rejecting every
        # citation merely because a table row was not emitted.
        advertised = {
            token.strip().casefold()
            for token in str(item.metadata.get("metrics", "")).split("|")
            if token.strip()
        }
        if metric in advertised and (
            inferred_from_metadata
            or not periods
            or periods[0] in extract_periods(item.content)
        ):
            return extract_normalized_numbers(item.content)
    elif not metric and (inferred_from_metadata or inferred_from_query):
        # Some translated claims use a metric phrase that is not in the
        # bilingual alias table.  With an explicit citation and a retrieval
        # item already scoped to the filing quarter, validate against that
        # item's own numbers rather than silently discarding the claim.
        if inferred_from_query:
            content_periods = extract_periods(item.content)
            if periods[0] not in content_periods or any(
                not periods_equivalent(content_period, periods[0])
                for content_period in content_periods
            ):
                # Without a recognized metric row, a comparative table cannot
                # safely bind its raw numbers to the query's inherited period.
                return []
        raw_numbers = extract_normalized_numbers(item.content)
        if any(marker in str(item.metadata.get("table_context", ""))
               for marker in ("Three Months Ended", "Six Months Ended")):
            raw_numbers = raw_numbers + [
                NormalizedNumber(
                    number.value * Decimal("1000000"), number.kind, "usd",
                    number.quantum * Decimal("1000000")
                    if number.quantum is not None else None,
                )
                for number in raw_numbers
                if number.kind == "amount" and number.currency is None and abs(number.value) >= 1000
            ]
        return raw_numbers
    if len(periods) == 1:
        scoped = period_scoped_row_numbers(item.content, periods[0], metric)
        if scoped:
            return scoped
        if inferred_from_metadata and periods[0] not in extract_periods(item.content):
            # A document-level quarter without an in-content period label is
            # insufficient to support an unqualified numeric claim.  This is
            # the critical distinction between filing period and claim/row
            # period for comparative reports.
            return []
    return extract_normalized_numbers(item.content)


def _rewrite_chinese_billion_unit(
    line: str,
    evidence_numbers: list[NormalizedNumber],
) -> str:
    """Correct the common ``75.2 亿美元`` rendering of a $75.2B fact.

    Chinese financial prose expresses one billion USD as ten ``亿``.  Models
    occasionally copy the English numeral while adding the Chinese unit.  If
    the evidence proves the same billion-scale numeral, rewrite only that
    unit (for example ``75.2 亿美元`` -> ``752 亿美元``); otherwise leave the
    claim untouched and let the normal unsupported policy remove it.
    """

    import re

    pattern = re.compile(r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*亿\s*(?P<currency>美元|人民币|元)")

    def replace(match: re.Match[str]) -> str:
        raw = match.group("num").replace(",", "")
        try:
            value = Decimal(raw)
        except Exception:
            return match.group(0)
        for evidence in evidence_numbers:
            if evidence.kind != "amount":
                continue
            if evidence.value / Decimal("1000000000") == value:
                converted = evidence.value / Decimal("100000000")
                rendered = format(converted.normalize(), "f")
                if "." in rendered:
                    rendered = rendered.rstrip("0").rstrip(".")
                return f"{rendered} 亿{match.group('currency')}"
        return match.group(0)

    return pattern.sub(replace, line)


def _insufficient_evidence_line(line: str) -> str:
    if any("\u3400" <= char <= "\u9fff" for char in line):
        return "证据不足，无法可靠支持该数字结论。"
    return "Insufficient evidence to support this numeric claim."


def _is_financial_numeric_claim(line: str) -> bool:
    """Distinguish financial amounts from identifiers in cited prose.

    Financial filings routinely mention non-financial numerals such as the
    ``4680`` battery-cell format, product generations, page references, or
    model numbers.  Treating every bare numeral as a financial claim causes
    the sanitizer to insert a misleading numeric-refusal sentence into an
    otherwise supported qualitative answer.  Currency, scale, percentage,
    basis-point, or explicit financial-metric context remains high risk and
    continues through the strict numeric validator.
    """

    numbers = extract_normalized_numbers(line)
    if not numbers:
        return False
    if any(number.kind in {"percent", "basis_points"} for number in numbers):
        return True
    if re.search(
        r"(?:\$|\b(?:usd|us\$|eur|cny|rmb|dollars?|million|millions|"
        r"billion|billions|thousand|thousands|trillion|trillions|bps?|"
        r"basis\s+points)\b|亿|万|美元|人民币|元)",
        line,
        re.IGNORECASE,
    ):
        return True
    # A bare numeral next to an explicit financial metric is still a claim,
    # while a product/part identifier such as ``4680 cells`` is not.
    # ``canonical_metrics`` intentionally focuses on broad metric aliases;
    # compact identifiers such as EPS are resolved by the stricter singular
    # metric parser.  Include both so a supported EPS value remains a
    # financial claim while bare product identifiers still take the
    # qualitative path.
    return bool(canonical_metrics(line) or canonical_metric_id(line))


_GROWTH_RANKING_CUE = re.compile(
    r"(?i)\b(?:strongest|stronger|weakest|best|worst)\s+growth|"
    r"\b(?:growth\s+)?(?:ranking|ranked|momentum|narrative)\b|"
    r"最强(?:的)?增长|增长(?:势头|动能|叙事).{0,12}(?:最强|最弱|更强|最好|最差)"
)
_DETERMINISTIC_GROWTH_RANKING_CUE = re.compile(
    r"(?i)\b(?:reported|verifiable)\s+revenue\s+(?:yoy|year[- ]over[- ]year)\b|"
    r"按各公司财报可验证的营收同比增速"
)
_DETERMINISTIC_GROWTH_SCOPE_CAVEAT_CUE = re.compile(
    r"(?i)(?:报告期不同|方向性比较|不代表同一季度的严格排名|"
    r"reporting periods? differ|directional comparison|not a strict same[- ]quarter ranking)"
)


def _deterministic_growth_ranking_references(
    question: str,
    evidence: list[Evidence],
) -> list[Evidence]:
    """Return issuer-complete revenue-growth evidence for a safe ranking line."""

    requested = {
        canonical_company(company) for company in extract_companies(question)
    }
    if len(requested) < 2:
        return []
    ledger = FactLedger.from_evidence(evidence)
    references: list[Evidence] = []
    for company in requested:
        growth_facts = ledger.lookup(
            company=company,
            metric_id="revenue",
            growth_basis="yoy",
        )
        operands: tuple[FinancialFact, ...] = ()
        if growth_facts:
            operands = (growth_facts[0],)
        else:
            period = _company_reporting_period(ledger, company, "revenue")
            prior_period = _prior_comparable_period(period)
            if not period or not prior_period:
                return []
            current = ledger.lookup(company=company, metric_id="revenue", period=period)
            prior = ledger.lookup(company=company, metric_id="revenue", period=prior_period)
            if not current or not prior:
                return []
            operands = (
                _preferred_fact(current, "revenue", question=question, requested_period=period),
                _preferred_fact(prior, "revenue", question=question, requested_period=prior_period),
            )
        for fact in operands:
            for item in evidence:
                if (
                    fact.chunk_id
                    and str(item.metadata.get("chunk_id", "")) == str(fact.chunk_id)
                ) or (
                    fact.evidence_text
                    and fact.evidence_text.strip() in str(item.content or "")
                ):
                    if item not in references:
                        references.append(item)
                    break
    return references if len({canonical_company(item.company) for item in references}) >= len(requested) else []


def _supported_growth_inference_references(
    question: str,
    line: str,
    evidence: list[Evidence],
) -> list[Evidence]:
    """Return issuer-complete evidence for a bounded growth ranking claim.

    A ranking is an inference rather than a verbatim filing sentence.  It is
    only eligible for citation synthesis when the line names exactly one
    requested issuer as the ranked subject and the retrieved evidence has a
    recognized growth passage for every requested issuer.  This prevents a
    model's unsupported ranking from bypassing the qualitative citation gate,
    while avoiding over-sanitization of a comparison that is fully covered.
    """

    if not is_growth_narrative_question(question) or _is_financial_numeric_claim(line):
        return []
    deterministic_ranking = bool(_DETERMINISTIC_GROWTH_RANKING_CUE.search(line))
    deterministic_caveat = bool(_DETERMINISTIC_GROWTH_SCOPE_CAVEAT_CUE.search(line))
    if not (_GROWTH_RANKING_CUE.search(line) or deterministic_ranking or deterministic_caveat):
        return []
    # The inference rescue is only for a concise ranking sentence. A long
    # paragraph can contain a ranking phrase plus unrelated periods, figures,
    # or causal assertions that the issuer-complete evidence does not entail.
    # Let the normal claim-level gate remove those fragments instead of
    # treating the whole paragraph as a supported ranking.
    if (len(_qualitative_tokens(line)) > 24 or len(line) > 320) and not deterministic_caveat:
        return []
    if re.search(r"(?i)\b(?:19|20)\d{2}\b|\bQ[1-4](?:\s*FY)?\s*20\d{2}\b", line):
        return []
    requested = {
        canonical_company(company) for company in extract_companies(question)
    }
    if len(requested) < 2:
        return []
    if _DETERMINISTIC_GROWTH_SCOPE_CAVEAT_CUE.search(line):
        # The deterministic renderer emits a second, non-issuer sentence to
        # disclose that the source periods are not aligned.  It is a policy
        # caveat, not a new financial claim, so it may inherit the same
        # issuer-complete evidence as the ranking sentence.  Keep this cue
        # narrow: arbitrary prose must still name exactly one requested issuer.
        return _deterministic_growth_ranking_references(question, evidence)
    mentioned = {
        canonical_company(company)
        for company in extract_companies(line)
        if canonical_company(company) in requested
    }
    if len(mentioned) != 1:
        return []
    if deterministic_ranking:
        return _deterministic_growth_ranking_references(question, evidence)
    passages = extract_growth_driver_passages(question, evidence)
    covered = {
        canonical_company(passage.company)
        for passage in passages
        if passage.company
    }
    if covered != requested:
        return []
    references: list[Evidence] = []
    for passage in passages:
        index = passage.evidence_rank - 1
        if 0 <= index < len(evidence) and evidence[index] not in references:
            references.append(evidence[index])
    return references


def _unsupported_prose_line(line: str) -> str:
    if any("\u3400" <= char <= "\u9fff" for char in line):
        return "所引财报证据不足以支持该表述。"
    return "The cited filing evidence is insufficient to support this statement."


def _deduplicate_standard_refusal_placeholders(answer: str) -> str:
    """Keep one copy of each standard refusal while preserving claim audits.

    The sanitizer may replace several unsupported fragments with the same
    user-facing message. Repeating that message adds no information; the
    ``GroundingClaim`` list still retains one disposition per original claim.
    """

    value = str(answer or "")
    for pattern in _STANDARD_REFUSAL_PLACEHOLDERS:
        seen = False

        def keep_first(match: re.Match[str]) -> str:
            nonlocal seen
            if seen:
                return ""
            seen = True
            return match.group(0)

        value = pattern.sub(keep_first, value)

    normalized_lines: list[str] = []
    for line in value.splitlines():
        line = re.sub(r"[ \t]{2,}", " ", line)
        line = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", line)
        line = re.sub(r"(?:[.;。]\s*){2,}", ". ", line)
        if re.fullmatch(r"\s*(?:[-*•]|\d+[.)])\s*", line):
            continue
        normalized_lines.append(line)

    value = "\n".join(normalized_lines)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _is_navigation_reference(line: str) -> bool:
    value = line.strip().rstrip(".!?。！？").strip()
    return bool(
        re.fullmatch(r"(?i)(?:see|refer to|see also)\s+(?:page|p\.?)\s*\d+", value)
        or re.fullmatch(r"(?:参见|见)\s*(?:第\s*)?\d+\s*页", value)
    )


def _scope_violation(question: str, claim: str) -> str | None:
    """Reject an answer clause that explicitly changes the requested scope.

    This check is intentionally independent of citation markers. A citation
    may occur after a sentence abbreviation (``Apple Inc.`` or ``U.S.``), and
    splitting first can otherwise turn the issuer-bearing clause into an
    uncited fragment that bypasses company validation.
    """

    requested_companies = {
        canonical_company(company) for company in extract_companies(question)
    }
    claimed_companies = {
        canonical_company(company) for company in extract_companies(claim)
    }
    if requested_companies and claimed_companies - requested_companies:
        return "WRONG_COMPANY"

    requested_periods = extract_periods(question)
    claimed_periods = extract_periods(claim)
    if requested_periods and claimed_periods and not any(
        periods_equivalent(claimed, requested)
        for claimed in claimed_periods
        for requested in requested_periods
    ):
        return "WRONG_PERIOD"
    return None


def sanitize_answer(
    question: str,
    answer: str,
    evidence: Iterable[Evidence],
    *,
    require_qualitative_citations: bool = False,
) -> GroundingResult:
    """Filter citations and remove unsupported high-risk numeric claims.

    Evidence rejected by company/period/metric constraints is never passed to
    the final response.  If a line contains unsupported numbers, the whole line
    is replaced with an explicit insufficiency message; no unrelated citation
    is attached to rescue it.
    """

    candidates = list(evidence)
    filtered = filter_evidence_for_query(question, candidates)
    # YoY claims legitimately require the matching quarter from the prior
    # year. Query-period filtering must not discard that cited operand before
    # deterministic derivation runs.
    if re.search(r"(?i)\byoy\b|year[- ]over[- ]year|同比|较上年同期", question):
        requested = extract_periods(question)
        prior_periods: set[str] = set()
        for period in requested:
            if prior_period := _prior_comparable_period(period):
                prior_periods.add(prior_period)
        for item in candidates:
            if any(
                any(periods_equivalent(found, prior) for prior in prior_periods)
                for found in extract_periods(item.content)
            ) and item not in filtered:
                filtered.append(item)
    trusted = [
        item
        for item in filtered
        if item.metadata.get("semantic_support") != "unverified"
    ]
    def identity(item):
        return (item.metadata.get("chunk_id"), item.source, item.content)

    trusted_by_id = {identity(item): item for item in trusted}
    by_rank = {index: trusted_by_id[identity(item)] for index, item in enumerate(candidates, 1)
               if identity(item) in trusted_by_id}
    final_ranks = {identity(item): index for index, item in enumerate(trusted, 1)}
    output_lines: list[str] = []
    claims: list[GroundingClaim] = []
    judgments: list[CitationJudgment] = []
    requested_companies = {
        canonical_company(company) for company in extract_companies(question)
    }
    active_company_context: str | None = None
    for original_line in str(answer or "").splitlines():
        if not original_line.strip():
            # Blank paragraph separators are layout, not factual claims.
            # Treating them as uncited prose in strict mode creates a phantom
            # UNSUPPORTED claim whenever a localized answer includes a cited
            # source excerpt after a blank line.
            output_lines.append("")
            continue
        # A provider may place citations after sentence punctuation. Bind
        # those references to that sentence before splitting it into claims.
        bound_line = re.sub(
            r"([.;；。!?])\s*((?:\[Evidence\s+\d+\]\s*)+)",
            lambda match: " " + match.group(2).strip() + match.group(1) + " ",
            original_line, flags=re.I,
        ).strip()
        # Chinese providers commonly separate cited clauses with a comma:
        # ``事实 A [Evidence 1]，事实 B [Evidence 2]``.  Without an explicit
        # boundary the whole line is validated against Evidence 1 only and a
        # correctly supported first claim can be over-sanitized together with
        # the second claim.  Convert citation+comma into a sentence boundary
        # before binding evidence ranks to fragments.
        bound_line = re.sub(
            r"((?:\[Evidence\s+\d+\]\s*)+)\s*，",
            r"\1; ",
            bound_line,
            flags=re.I,
        )
        # Markdown reports commonly establish the issuer in a section heading
        # and then omit it from each following bullet.  Without carrying that
        # context, a cited Tesla numeric sentence can survive underneath an
        # Apple heading simply because the sentence itself does not repeat
        # "Tesla".  Keep context only for a single requested issuer; a
        # multi-issuer heading is intentionally ambiguous and resets it.
        heading_companies = {
            canonical_company(company)
            for company in extract_companies(
                re.sub(r"\[Evidence\s+\d+\]", "", bound_line, flags=re.I)
            )
            if canonical_company(company) in requested_companies
        }
        if original_line.lstrip().startswith("#"):
            active_company_context = (
                next(iter(heading_companies)) if len(heading_companies) == 1 else None
            )
        # A sentence can name an off-scope issuer once and continue with an
        # implicit subject ("Apple Inc. ... . It states ..."). Reject the
        # complete source line before punctuation splitting so the second
        # clause cannot shed the wrong-company antecedent.
        line_scope_violation = _scope_violation(
            question,
            re.sub(r"\[Evidence\s+\d+\]", "", bound_line, flags=re.I),
        )
        if line_scope_violation:
            replacement = (
                _insufficient_evidence_line(bound_line)
                if extract_normalized_numbers(bound_line)
                else _unsupported_prose_line(bound_line)
            )
            output_lines.append(replacement)
            claims.append(GroundingClaim(original_line.strip(), "UNSUPPORTED"))
            continue
        # Protect common corporate/geographic abbreviations before sentence
        # splitting. Otherwise "Apple Inc." or "U.S. dollar" can detach the
        # issuer/period scope from the claim and leave the following fragment
        # looking like uncited generic prose.
        abbreviation_dot = "\u0000"
        protected_line = re.sub(
            r"\b(?:inc|corp|co|ltd|llc|plc|u\.s|u\.k|e\.g|i\.e)\.",
            lambda match: match.group(0)[:-1] + abbreviation_dot,
            bound_line,
            flags=re.I,
        )
        # Company boundaries must be checked before pooling evidence. A line
        # saying Apple=$81.6B; NVIDIA=$100B cannot use the union of both firms.
        company_names = sorted({alias for item in candidates for alias in _company_aliases(item.company)},
                               key=len, reverse=True)
        company_boundary = (r"\s+(?:and\s+)?(?=(?:" + "|".join(map(re.escape, company_names))
                            + r")\s+(?:revenue|net income|营收|收入))") if company_names else r"(?!)"
        fragments = re.split(r"(?<=[;；。!?])\s*|(?<=\.)(?=\s|$)|" + company_boundary,
                             protected_line, flags=re.I)
        fragments = [part for part in fragments if part] or [original_line]
        rendered = []
        for fragment in fragments:
            line = fragment.replace(abbreviation_dot, ".")
            # Citation binding can leave a standalone punctuation fragment
            # when a provider writes ``[Evidence 2].``.  It carries no claim
            # and must not become an artificial UNSUPPORTED judgment.
            if not line.strip(" \t.,;:!?，。；：！？、"):
                continue
            explicit_ranks = [int(rank) for rank in re.findall(r"\[Evidence\s+(\d+)\]", line, re.I)]
            cited = [by_rank[rank] for rank in explicit_ranks if rank in by_rank]
            available = cited if explicit_ranks else trusted
            available = [item for item in available if item in trusted]
            # An explicit citation is a binding, not decorative punctuation.
            mentioned_companies = {canonical_company(company) for company in extract_companies(line)}
            if mentioned_companies:
                available = [item for item in available if canonical_company(item.company) in mentioned_companies]
            elif active_company_context:
                # An issuer named by the current section heading is the
                # implicit subject of uncited/implicitly-subjected bullets.
                # Apply the same company binding as an explicit issuer name.
                available = [
                    item
                    for item in available
                    if canonical_company(item.company) == active_company_context
                ]
            elif len(requested_companies) > 1 and _is_financial_numeric_claim(line):
                # In a multi-company answer an unlabelled financial number is
                # ambiguous.  Fail closed instead of borrowing a value from a
                # different issuer's cited chunk.
                available = []
            line = re.sub(r"\[Evidence\s+\d+\]", "", line, flags=re.I).strip()
            financial_numeric_claim = _is_financial_numeric_claim(line)
            typed_judgments_for_fragment: list[CitationJudgment] = []
            # TypeSafe-shaped deterministic judgment: code owns the policy,
            # while each explicitly cited chunk receives a typed relation.
            # The existing financial ledger/grounding gate remains the final
            # rejector; REVIEW is auditable and is not silently promoted to
            # proof by this generic layer.
            if explicit_ranks and available:
                typed_available: list[Evidence] = []
                for item in available:
                    judgment = judge_citation(
                        line,
                        item.content,
                        metadata=item.metadata,
                    )
                    judgments.append(judgment)
                    typed_judgments_for_fragment.append(judgment)
                    # Keep the evidence available to the existing ledger and
                    # table-column validator.  Its richer financial parser
                    # can prove values that a generic typed precheck must
                    # defer (for example unlabeled ``22,496`` under a
                    # ``$ in millions`` header).  The judgment remains part
                    # of the production result for policy/audit consumers;
                    # no generic semantic guess is allowed to override the
                    # domain-specific deterministic gate.
                    typed_available.append(item)
                available = typed_available
            scope_violation = _scope_violation(question, line)
            if scope_violation:
                replacement = (
                    _insufficient_evidence_line(line)
                    if financial_numeric_claim
                    else _unsupported_prose_line(line)
                )
                rendered.append(replacement)
                claims.append(GroundingClaim(line, "UNSUPPORTED"))
                continue
            if not financial_numeric_claim and explicit_ranks and _is_navigation_reference(line):
                rendered.append(line)
                claims.append(GroundingClaim(line, "NON_NUMERIC"))
                continue
            qualitative_references: list[Evidence] = []
            is_heading = line.lstrip().startswith("#")
            is_safe_refusal = bool(_SAFE_GROUNDING_REFUSAL.fullmatch(line.strip()))
            inferred_growth_references = (
                _supported_growth_inference_references(question, line, trusted)
                if not financial_numeric_claim
                else []
            )
            typed_review_only = bool(
                typed_judgments_for_fragment
                and not financial_numeric_claim
                and all(
                    judgment.action is CitationAction.REVIEW
                    for judgment in typed_judgments_for_fragment
                )
            )
            if (
                typed_review_only
                and not is_heading
                and not is_safe_refusal
                and not inferred_growth_references
                and not _is_verbatim_cited_excerpt(line, available)
            ):
                # TypeSafe REVIEW means that the generic relation checker
                # cannot establish entailment.  Do not let the richer domain
                # matcher silently promote that ambiguity to a user-visible
                # financial conclusion; exact source excerpts remain safe.
                rendered.append(_unsupported_prose_line(line))
                claims.append(GroundingClaim(line, "UNSUPPORTED"))
                continue
            if (
                not financial_numeric_claim
                and not is_heading
                and not is_safe_refusal
                and (explicit_ranks or require_qualitative_citations)
            ):
                qualitative_references = _qualitative_support_items(question, line, available)
                if not qualitative_references:
                    # A fully covered growth comparison may contain a concise
                    # ranking inference whose wording is not a verbatim
                    # substring of any one filing.  Synthesize citations only
                    # after the issuer-complete evidence check above; generic
                    # qualitative claims still fail closed.
                    qualitative_references = inferred_growth_references
            if (
                not financial_numeric_claim
                and not is_heading
                and not is_safe_refusal
                and (explicit_ranks or require_qualitative_citations)
                and not qualitative_references
            ):
                # A prose clause cannot keep a citation that was filtered out
                # for company/period mismatch, nor an unrelated citation that
                # has no meaningful lexical tie to the claim. In production
                # mode this also prevents an uncited factual assertion from
                # escaping merely because it contains no numeric claim.
                rendered.append(_unsupported_prose_line(line))
                claims.append(GroundingClaim(line, "UNSUPPORTED"))
                continue
            if not financial_numeric_claim and extract_normalized_numbers(line):
                # Bare identifiers (for example a battery-cell format) are
                # qualitative source details, not financial amounts. Keep the
                # clause with only the lexical evidence that supports it.
                reference_items = qualitative_references or _qualitative_support_items(
                    question, line, available,
                )
                refs = " ".join(
                    f"[Evidence {final_ranks[identity(item)]}]"
                    for item in reference_items
                )
                rendered.append(f"{line} {refs}".strip() if refs else line)
                claims.append(GroundingClaim(line, "NON_NUMERIC"))
                continue
            result_line, claim = _sanitize_fragment(question, line, available)
            # Provider citation numbers occasionally drift after retrieval
            # deduplication (the model cites the right filing chunk using an
            # earlier rank).  A numeric claim must still be bound to an
            # actually supporting, semantically filtered chunk; remap only
            # when the cited chunk fails and an alternative trusted chunk
            # proves every number in the same company/period scope.  This
            # repairs citation drift without accepting wrong-company,
            # wrong-period, or unrelated evidence.
            if (
                claim.disposition == "UNSUPPORTED"
                and explicit_ranks
                and financial_numeric_claim
                and any("\u3400" <= char <= "\u9fff" for char in line)
            ):
                alternatives = [
                    item for item in trusted
                    if not mentioned_companies
                    or canonical_company(item.company) in mentioned_companies
                ]
                alternative_supported = _numeric_support_items(question, line, alternatives)
                if alternative_supported:
                    result_line, claim = _sanitize_fragment(question, line, alternative_supported)
                    available = alternative_supported
            if claim.disposition != "UNSUPPORTED":
                reference_items = []
                if financial_numeric_claim:
                    # Use the validated/re-written clause for citation binding.
                    # For example, Chinese ``75.2 亿美元`` can be deterministically
                    # corrected to ``752 亿美元`` when the source proves $75.2B;
                    # binding against the pre-rewrite number would then wrongly
                    # discard the correct source and replace the answer with a refusal.
                    reference_items = _numeric_support_items(question, result_line, available)
                    if not reference_items:
                        result_line = _insufficient_evidence_line(line)
                        claim = GroundingClaim(line, "UNSUPPORTED")
                elif explicit_ranks or (
                    require_qualitative_citations and not is_heading and not is_safe_refusal
                ):
                    # Never keep every explicit marker just because one of
                    # them supports a numeric claim.  Bind numeric clauses to
                    # the cited chunks that prove their values; bind prose to
                    # a small lexical-support subset. When strict mode is on,
                    # synthesize citations only from chunks with that same
                    # per-clause support.
                    reference_items = qualitative_references or _qualitative_support_items(
                        question, line, available,
                    )
                if claim.disposition != "UNSUPPORTED":
                    refs = " ".join(
                        f"[Evidence {final_ranks[identity(item)]}]"
                        for item in reference_items
                    )
                    if refs:
                        # Keep the citation inside its clause across repeated passes.
                        punctuation = re.search(r"[.;；。!?]+$", result_line)
                        suffix = punctuation.group(0) if punctuation else ""
                        body = result_line[:-len(suffix)] if suffix else result_line
                        result_line = f"{body.rstrip()} {refs}{suffix}"
            claims.append(GroundingClaim(fragment, claim.disposition))
            rendered.append(result_line)
        output_lines.append(" ".join(rendered))

    return GroundingResult(
        answer=_deduplicate_standard_refusal_placeholders("\n".join(output_lines)),
        evidence=trusted,
        claims=claims,
        judgments=judgments,
    )


def _sanitize_fragment(question: str, line: str, trusted: list[Evidence]) -> tuple[str, GroundingClaim]:
    """Validate one company/period clause against only its bound citations."""
    claim_values = extract_normalized_numbers(line)
    mentioned_metrics = set(canonical_metrics(line))
    amount_values = [value for value in claim_values if value.kind == "amount"]
    if (
        "|" in line
        and len(amount_values) > 1
        and len(extract_periods(line)) < 2
    ):
        # A pipe-delimited financial row with several values is a comparative
        # claim, not a bag of amounts. Require both periods in the claim itself:
        # answer-table headers are not reliably preserved by downstream
        # renderers, and citation presence cannot bind values to columns.
        # Fail closed rather than silently treating Q4 -> Q1 as YoY (or
        # leaving the periods implicit).
        return _insufficient_evidence_line(line), GroundingClaim(line, "UNSUPPORTED")
    if len(mentioned_metrics) > 1 and len(amount_values) > 1:
        # A sentence that assigns several amounts to several financial
        # metrics is not safely verifiable by checking whether every number
        # appears somewhere in the same chunk. Without a claim boundary, that
        # union check accepts swapped labels (e.g. revenue=$58B; net income=
        # $81B when the filing says the reverse). Fail closed; the required
        # fact planner can re-add any requested values as independently
        # scoped, cited ledger facts.
        return _insufficient_evidence_line(line), GroundingClaim(line, "UNSUPPORTED")
    query_metrics = set(canonical_metrics(question))
    regional_main_business = (
        "main_business_revenue" in query_metrics
        and bool(re.search(
            r"分地区|地区|国内|境内|国外|海外|境外|"
            r"\b(?:by\s+region|regional|domestic|overseas|international)\b",
            question,
            re.IGNORECASE,
        ))
    )
    regional_category: str | None = None
    if regional_main_business:
        if re.search(r"国内|境内|\bdomestic\b", line, re.IGNORECASE):
            regional_category = "domestic"
        elif re.search(r"国外|海外|境外|\b(?:overseas|international)\b", line, re.IGNORECASE):
            regional_category = "overseas"
        # In a by-region query, the regional table's row metric is Revenue,
        # while the question may call the consolidated disclosure 主营业务收入.
        # Treat these labels as equivalent only for a cited row explicitly
        # tagged with the matching region; do not generalize the alias to totals.
        if regional_category:
            query_metrics.add("revenue")
    if query_metrics and claim_values and not query_metrics.intersection(mentioned_metrics):
        # Matching a number somewhere in a filing is not enough: a total
        # revenue figure must not answer a Data Center revenue question, and
        # net income must not substantiate operating income. The final answer
        # must name at least one requested metric on the same claim clause.
        return _insufficient_evidence_line(line), GroundingClaim(line, "UNSUPPORTED")
    allow_guidance = _guidance_claim_allowed(question, line)
    validation_evidence = trusted
    if regional_category:
        category_aliases = {
            "domestic": {"国内", "境内", "domestic"},
            "overseas": {"国外", "海外", "境外", "overseas", "international"},
        }[regional_category]
        validation_evidence = [
            item for item in trusted
            if any(
                fact.dimension == "region"
                and fact.metric_id == "revenue"
                and fact.category
                and fact.category.casefold() in category_aliases
                for fact in FactLedger.from_evidence([item]).facts
            )
        ]
        if not validation_evidence:
            return _insufficient_evidence_line(line), GroundingClaim(line, "UNSUPPORTED")
    line_numbers = [number for item in validation_evidence
                    for number in _numbers_for_line(
                        line,
                        item,
                        canonical_metric(question),
                        allow_guidance=allow_guidance,
                        requested_periods=extract_periods(question),
                    )]
    disposition = _line_disposition(line, line_numbers)
    # The line may state only the current amount plus a signed percentage;
    # validate a derived rate through the minimal evidence cover, which can
    # include the matching prior-period operand from another cited chunk.
    if disposition == "UNSUPPORTED" and any(value.kind == "percent" for value in claim_values):
        if _numeric_support_items(question, line, trusted):
            disposition = "DERIVABLE"
    rewritten = _rewrite_chinese_billion_unit(line, line_numbers)
    if rewritten != line:
        rewritten_disposition = _line_disposition(rewritten, line_numbers)
        if rewritten_disposition in {"SUPPORTED", "DERIVABLE"}:
            line, disposition = rewritten, rewritten_disposition
    if disposition == "UNSUPPORTED":
        return _insufficient_evidence_line(line), GroundingClaim(line, disposition)
    return line, GroundingClaim(line, disposition)


def _numeric_support_items(
    question: str,
    line: str,
    evidence: list[Evidence],
) -> list[Evidence]:
    """Choose the minimal chunks that support every numeric operand in a claim.

    A claim can be validated against the union of a context, but that does not
    make every context chunk a valid citation. This cover selects one exact
    source per directly supported number; a derived percentage may use two
    chunks that provide its calculation operands. It never falls back to
    citing the whole retrieval set.
    """

    claims = extract_normalized_numbers(line)
    if not claims or not evidence:
        return []
    metric = canonical_metric(question)
    allow_guidance = _guidance_claim_allowed(question, line)
    numbers_by_index = [
        _numbers_for_line(
            line,
            item,
            metric,
            allow_guidance=allow_guidance,
            requested_periods=extract_periods(question),
        )
        for item in evidence
    ]
    # A period-specific YoY claim needs one current and one matching prior
    # period operand. Do not let an unrelated quarter pair in the same
    # comparative row (for example Q4's -3% column) satisfy a Q2 claim.
    requested_periods = extract_periods(question)
    percent_claim = any(value.kind == "percent" for value in claims)
    if metric and percent_claim and _growth_basis_present(line, "yoy") and requested_periods:
        prior_periods = {
            prior
            for period in requested_periods
            if (prior := _prior_comparable_period(period))
        }
        if prior_periods:
            period_facts = [
                fact
                for item in evidence
                for fact in FactLedger.from_evidence([item]).facts
                if fact.metric_id == metric and fact.growth_basis is None
            ]
            all_period_facts = [
                fact
                for item in evidence
                for fact in FactLedger.from_evidence([item]).facts
                if fact.metric_id == metric
            ]
            has_matching_operands = any(
                any(periods_equivalent(fact.fact_period, current) for current in requested_periods)
                and any(periods_equivalent(other.fact_period, prior) for prior in prior_periods)
                for fact in period_facts
                for other in period_facts
            )
            has_period_bound_rate = any(
                fact.growth_basis
                and any(periods_equivalent(fact.fact_period, current) for current in requested_periods)
                for fact in all_period_facts
            )
            if not has_matching_operands and not has_period_bound_rate:
                return []
    selected: set[int] = set()
    ordered_operands = _ordered_growth_operands(claims, line)
    for claim in claims:
        direct = [
            index for index, values in enumerate(numbers_by_index)
            if any(numbers_equivalent(claim, value) for value in values)
        ]
        if direct:
            selected.add(direct[0])
            continue
        if claim.kind != "percent":
            return []
        if ordered_operands:
            current, prior = ordered_operands
            current_indices = [
                index for index, values in enumerate(numbers_by_index)
                if any(numbers_equivalent(current, value) for value in values)
            ]
            prior_indices = [
                index for index, values in enumerate(numbers_by_index)
                if any(numbers_equivalent(prior, value) for value in values)
            ]
            pairs = [
                (current_index, prior_index)
                for current_index in current_indices
                for prior_index in prior_indices
                if (derived := derived_growth(current, prior)) is not None
                and _close_growth_claim(claim, derived, line)
            ]
            if not pairs:
                return []
            selected.update(pairs[0])
            continue
        # A concise answer often states only the current-period amount and
        # the derived percentage.  For that case the prior-period operand may
        # be present in a cited comparative chunk but is intentionally absent
        # from the question's requested-period filter. Re-scan only the
        # derivation path without that filter; direct claims remain strict.
        derivation_numbers = [
            _numbers_for_line(
                re.sub(r"\bQ\d(?:[- ]\d{4}|\s+FY\d{4})\b", "", line, flags=re.IGNORECASE),
                item,
                metric,
                allow_guidance=allow_guidance,
                requested_periods=(),
            )
            for item in evidence
        ]
        derived_pairs: list[tuple[int, int]] = []
        for left_index, left_values in enumerate(derivation_numbers):
            for right_index in range(left_index, len(numbers_by_index)):
                right_values = derivation_numbers[right_index]
                for left in left_values:
                    if left.kind != "amount":
                        continue
                    for right in right_values:
                        derived = derived_growth(left, right)
                        if derived is not None and _close_growth_claim(claim, derived, line):
                            derived_pairs.append((left_index, right_index))
        if not derived_pairs:
            return []
        selected.update(derived_pairs[0])
    return [item for index, item in enumerate(evidence) if index in selected]
