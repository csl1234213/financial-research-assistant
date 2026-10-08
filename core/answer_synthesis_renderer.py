"""Deterministic, restricted projections; never accept free-form model prose as verified."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from core.answer_synthesis_contracts import (
    AnswerPlan,
    AnswerType,
    ClaimType,
    SynthesisInput,
    VerificationFailure,
    VerificationResult,
)
from core.answer_synthesis_planner import DeterministicAnswerPlanner, DeterministicAnswerVerifier
from core.fact_ledger import canonical_company
from core.financial_metric_registry import FINANCIAL_METRIC_REGISTRY


def company_display_name(source: SynthesisInput, claim) -> str:
    """Project a source name without changing the locked company identity."""
    identity = claim.observation["company"]
    evidence = next(item for item in source.evidence if item.evidence_id == claim.evidence_ids[0])
    key = "company_name_zh" if source.locale == "zh-CN" else "company_name_en"
    name = evidence.payload["provenance"].get(key)
    if name is None:
        return identity
    if (
        not isinstance(name, str)
        or not name.strip()
        or any(char in name for char in "\n\r[]<>*|`")
        or canonical_company(name) != canonical_company(identity)
    ):
        raise ValueError("company display name does not match source identity")
    return name


@dataclass(frozen=True)
class NumericPresentation:
    original_value: Decimal
    currency: str
    original_unit: str
    divisor: Decimal
    displayed_value: Decimal
    rounded: bool
    text: str

    @classmethod
    def build(cls, value: Decimal, *, currency: str, unit: str, locale: str) -> NumericPresentation:
        if type(value) is not Decimal or not value.is_finite():
            raise ValueError("finite Decimal required")
        expected = "CNY_YUAN" if currency == "CNY" else f"{currency}_UNIT"
        if currency not in {"CNY", "USD"} or unit != expected or locale not in {"zh-CN", "en"}:
            raise ValueError("unsupported monetary unit/currency/locale")
        if len(value.as_tuple().digits) > 1000 or abs(value.as_tuple().exponent) > 1000:
            raise ValueError("numeric presentation exceeds precision budget")
        chinese = locale == "zh-CN"
        divisor = Decimal(1)
        suffix = "元" if chinese and currency == "CNY" else ("美元" if chinese else "")
        magnitude = value.copy_abs()  # abs(Decimal) 会受全局精度影响；阈值判断也必须精确。
        if chinese and magnitude >= Decimal("100000000"):
            divisor, suffix = Decimal("100000000"), "亿元" if currency == "CNY" else "亿美元"
        elif not chinese and magnitude >= Decimal("1000000000"):
            divisor, suffix = Decimal("1000000000"), "billion"
        elif not chinese and magnitude >= Decimal("1000000"):
            divisor, suffix = Decimal("1000000"), "million"
        with localcontext() as context:
            context.prec = max(50, len(value.as_tuple().digits) + abs(value.as_tuple().exponent) + 20)
            exact = value / divisor
            display = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if divisor != 1 else exact
        rounded = display != exact
        number = format(display, ",f")
        if divisor == 1 and "." in number:
            number = number.rstrip("0").rstrip(".")
        if chinese:
            text = ("约" if rounded else "") + ("人民币 " if currency == "CNY" else "") + number + " " + suffix
        else:
            text = ("approximately " if rounded else "") + number + (" " + suffix if suffix else "") + " " + currency
        return cls(value, currency, unit, divisor, display, rounded, text)


@dataclass(frozen=True)
class RenderedAnswer:
    text: str
    citation_evidence_ids: tuple[str, ...]
    presentations: tuple[NumericPresentation, ...]
    template_version: str = "p2.2.restricted.v1"


class RestrictedAnswerRenderer:
    """Render locked observations only; unsupported modes and caveats fail closed."""

    def render(self, source: SynthesisInput, plan: AnswerPlan) -> RenderedAnswer:
        checked = DeterministicAnswerVerifier().verify(source, plan)
        if source.answer_type == AnswerType.AMBIGUOUS:
            if checked.failures or plan != DeterministicAnswerPlanner().plan(source):
                raise ValueError("invalid clarification plan")
            text = {
                "zh-CN": "这个问题的财务口径尚未明确。你想了解哪个指标，或比较哪些对象？",
                "zh-TW": "這個問題的財務口徑尚未明確。你想了解哪個指標，或比較哪些對象？",
                "en": "The financial basis of this question is not yet clear. Which metric or comparison do you mean?",
            }[source.locale]
            return RenderedAnswer(text, (), (), "p2.2.clarification.v1")
        if source.answer_type not in {AnswerType.FACT, AnswerType.COMPARISON, AnswerType.TREND}:
            raise ValueError("answer strategy not implemented")
        if checked.failures or plan.caveats or plan.relationships or not plan.claims:
            raise ValueError("plan is not eligible for restricted rendering")
        if source.locale not in {"zh-CN", "en"}:
            raise ValueError("locale not implemented")
        lines, citations, presentations = [], [], []
        scopes = {
            "zh-CN": {"CONSOLIDATED": "合并报表", "PARENT_COMPANY": "母公司报表"},
            "en": {"CONSOLIDATED": "consolidated statements", "PARENT_COMPANY": "parent-company statements"},
        }
        for claim in plan.claims:
            if claim.claim_type != ClaimType.FACT or claim.observation is None:
                raise ValueError("only locked factual observations can be rendered")
            observation = claim.observation
            definition = FINANCIAL_METRIC_REGISTRY.get(observation["metric"])
            if definition is None or definition.value_type != "monetary":
                raise ValueError("registered monetary metric required")
            aliases = definition.aliases_zh if source.locale == "zh-CN" else definition.aliases_en
            scope = scopes[source.locale].get(observation["scope"])
            if not aliases or scope is None:
                raise ValueError("metric label or financial scope unavailable")
            period = observation["period"]
            dates = (
                period["period_end"]
                if period["period_type"] == "INSTANT"
                else (period["period_start"] + " – " + period["period_end"])
            )
            presentation = NumericPresentation.build(
                observation["value"], currency=observation["currency"], unit=observation["unit"], locale=source.locale
            )
            evidence_id = claim.evidence_ids[0]
            if evidence_id not in citations:
                citations.append(evidence_id)
            rank = citations.index(evidence_id) + 1
            # 公司名禁止 Markdown/换行控制内容；无需翻译公司身份，也不从正文提取标题。
            company = company_display_name(source, claim)
            if not isinstance(company, str) or any(char in company for char in "\n\r[]<>*|`"):
                raise ValueError("unsafe company display name")
            lines.append(
                f"{company}，{dates}，{scope}：{aliases[0]}为{presentation.text} [{rank}]。"
                if source.locale == "zh-CN"
                else f"{company}, {dates}, {scope}: {aliases[0]} was {presentation.text} [{rank}]."
            )
            presentations.append(presentation)
        return RenderedAnswer("\n\n".join(lines), tuple(citations), tuple(presentations))


class RestrictedOutputVerifier:
    """Certification is limited to exact deterministic templates, never arbitrary prose."""

    def verify(self, source: SynthesisInput, plan: AnswerPlan, rendered: RenderedAnswer) -> VerificationResult:
        checks = DeterministicAnswerVerifier().verify(source, plan)
        failures = list(checks.failures)
        try:
            expected = RestrictedAnswerRenderer().render(source, plan)
        except ValueError:
            return VerificationResult(tuple(failures or [VerificationFailure.UNSUPPORTED_CLAIM]))
        if rendered.citation_evidence_ids != expected.citation_evidence_ids:
            failures.append(VerificationFailure.CITATION_WRONG_SOURCE)
        if rendered.presentations != expected.presentations:
            failures.append(VerificationFailure.NUMERIC_MUTATION)
        if rendered.text != expected.text or rendered.template_version != expected.template_version:
            failures.append(VerificationFailure.UNSUPPORTED_CLAIM)
        # 仅固定模板、逐字段验证后的 observation 语义投影；不代表通用叙述蕴含评测。
        return VerificationResult(tuple(dict.fromkeys(failures)), checks.reviewed_claim_ids, True)
