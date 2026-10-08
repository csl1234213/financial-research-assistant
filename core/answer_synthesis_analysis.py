"""Auditable two-observation arithmetic; no causal or free-prose certification."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from core.answer_synthesis_contracts import AnswerType
from core.answer_synthesis_planner import DeterministicAnswerVerifier
from core.answer_synthesis_renderer import NumericPresentation, RestrictedAnswerRenderer
from core.fact_ledger import canonical_company


@dataclass(frozen=True)
class DifferenceAudit:
    evidence_ids: tuple[str, str]
    baseline: Decimal
    current: Decimal
    difference: Decimal
    percentage_display: Decimal | None
    percentage_rounded: bool
    percentage_unavailable_reason: str | None
    formula: str = "difference=current-baseline; percentage=difference/baseline*100"


def audited_difference(source, plan):
    if (source.answer_type not in {AnswerType.TREND, AnswerType.COMPARISON}
            or plan.caveats or plan.relationships or len(plan.claims) != 2
            or DeterministicAnswerVerifier().verify(source, plan).failures):
        raise ValueError("ANALYSIS_PLAN_NOT_ELIGIBLE")
    left, right = plan.claims
    baseline, current = left.observation, right.observation
    dimensions = ("metric", "scope", "currency", "unit", "statement")
    if any(baseline[key] != current[key] for key in dimensions):
        raise ValueError("ANALYSIS_DIMENSION_MISMATCH")
    a, b = baseline["period"], current["period"]
    if source.answer_type == AnswerType.TREND:
        if baseline["company"] != current["company"] or a["period_type"] != b["period_type"]:
            raise ValueError("TREND_IDENTITY_MISMATCH")
        keys = ("period_end", "period_start") if a["period_type"] == "DURATION" else ("period_end",)
        for key in keys:
            first, second = date.fromisoformat(a[key]), date.fromisoformat(b[key])
            if second.year != first.year + 1 or (first.month, first.day) != (second.month, second.day):
                raise ValueError("TREND_NOT_COMPARABLE_YEAR_ON_YEAR")
    else:
        if a != b or canonical_company(baseline["company"]) == canonical_company(current["company"]):
            raise ValueError("COMPARISON_PERIOD_OR_COMPANY_MISMATCH")
        standards = [item.payload["provenance"].get("accounting_standard") for item in source.evidence
                     if item.evidence_id in {left.evidence_ids[0], right.evidence_ids[0]}]
        if len(standards) != 2 or standards[0] not in {"CAS", "US_GAAP", "IFRS"} or standards[0] != standards[1]:
            raise ValueError("COMPARISON_ACCOUNTING_STANDARD_NOT_ALIGNED")
        if any(not item.payload["provenance"].get("accounting_standard_source") for item in source.evidence
               if item.evidence_id in {left.evidence_ids[0], right.evidence_ids[0]}):
            raise ValueError("COMPARISON_ACCOUNTING_STANDARD_SOURCE_MISSING")
    values = (baseline["value"], current["value"])
    if any(len(value.as_tuple().digits) > 1000 or abs(value.as_tuple().exponent) > 1000 for value in values):
        raise ValueError("ANALYSIS_PRECISION_BUDGET_EXCEEDED")
    with localcontext() as context:
        # Span both operands' decimal positions, not merely each digit count.
        context.prec = max(50, max(value.adjusted() for value in values)
                           - min(value.as_tuple().exponent for value in values) + 30)
        difference = values[1] - values[0]
        percentage = None
        rounded = False
        if values[0] > 0:
            percentage = (difference / values[0] * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rounded = percentage * values[0] != difference * 100
    return DifferenceAudit((left.evidence_ids[0], right.evidence_ids[0]), *values, difference, percentage,
                           rounded, None if percentage is not None else "NON_POSITIVE_BASELINE")


@dataclass(frozen=True)
class AnalyticalAnswer:
    text: str
    audit: DifferenceAudit


class AnalyticalAnswerRenderer:
    def render(self, source, plan):
        audit = audited_difference(source, plan)
        factual = RestrictedAnswerRenderer().render(source, plan)
        observation = plan.claims[0].observation
        difference = NumericPresentation.build(audit.difference, currency=observation["currency"],
                                                unit=observation["unit"], locale=source.locale)
        ranks = [factual.citation_evidence_ids.index(identity) + 1 for identity in audit.evidence_ids]
        citations = " ".join(f"[{rank}]" for rank in ranks)
        if source.locale == "zh-CN":
            line = f"按上述同口径数据计算，第二项减第一项的差额为{difference.text}。"
            label = "同比变动比例" if source.answer_type == AnswerType.TREND else "差额占第一项的比例"
            line += (f"{label}为{'约' if audit.percentage_rounded else ''}{audit.percentage_display:.2f}%。"
                     if audit.percentage_display is not None else "基数不大于零，不计算变动百分比。")
        else:
            line = f"On the aligned basis above, the second value minus the first is {difference.text}. "
            label = ("year-on-year percentage change" if source.answer_type == AnswerType.TREND
                     else "relative difference")
            line += (f"The {label} is {'approximately ' if audit.percentage_rounded else ''}"
                     f"{audit.percentage_display:.2f}%."
                     if audit.percentage_display is not None
                     else "No percentage is computed for a non-positive baseline.")
        return AnalyticalAnswer(factual.text + "\n\n" + line + " " + citations, audit)

    def verify(self, source, plan, answer):
        return answer == self.render(source, plan)
