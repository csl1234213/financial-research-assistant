"""One production boundary for completing and grounding the final answer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from agent.planning.entity_extractor import extract_companies
from agent.reasoning_models import Evidence
from core.answer_grounding import (
    _GROWTH_RANKING_CUE,
    GroundingResult,
    sanitize_answer,
)
from core.fact_ledger import FactLedger, canonical_company, canonical_metric_id, periods_equivalent
from core.financial_grounding import (
    NormalizedNumber,
    canonical_metrics,
    derived_growth,
    extract_normalized_numbers,
    numbers_equivalent,
)
from core.growth_driver_evidence import (
    answer_has_cited_growth_driver,
    extract_growth_driver_passages,
    is_driver_absence_claim,
    is_explicit_growth_driver_question,
    is_growth_narrative_question,
    is_segment_comparison_question,
)
from core.query_scope import (
    QueryScope,
    classify_query_scope,
    current_turn_query,
    is_nonfinancial_business_development_summary,
)
from core.required_fact_plan import (
    RequiredFactPlan,
    _fact_alias_present,
    _preferred_fact,
    _prior_comparable_period,
    complete_from_fact_ledger,
    infer_required_fact_plan,
    remove_mislabeled_eps_claims,
    safe_answer_from_fact_ledger,
)
from retrieval.periods import extract_periods


@dataclass(frozen=True)
class FinalAnswer:
    grounded: GroundingResult
    raw_grounding: GroundingResult
    plan: RequiredFactPlan
    ledger: FactLedger
    added_fact_ids: tuple[str, ...]
    removed_lines: tuple[str, ...]
    prepared_answer: str
    verified_facts_only_projection: bool = False

    @property
    def answer(self) -> str:
        return self.grounded.answer


def no_evidence_response(
    question: str,
    response_language: str | None = None,
) -> str:
    """Return a useful, localized explanation when retrieval found no source.

    Keep this issuer-agnostic: absence from the current retrieval result must
    not be converted into a benchmark-specific answer or a claim that a
    company does not publish the requested data.
    """

    is_chinese = (
        response_language == "zh-CN"
        if response_language in {"en", "zh-CN"}
        else any("\u3400" <= char <= "\u9fff" for char in str(question or ""))
    )
    if is_chinese:
        return (
            "当前可检索的上传财报中没有找到足以支持该问题的证据，"
            "证据不足以可靠回答。"
            "请上传相关公司及报告期的财报后再试。"
        )
    return (
        "No relevant uploaded-filing evidence was retrieved for this question, "
        "so I can't answer it reliably. Upload the relevant company's filing "
        "for the requested period and try again."
    )


def _retrieved_evidence_insufficient_response(
    question: str,
    response_language: str | None = None,
) -> str:
    """Describe a non-empty retrieval set that yielded no trusted evidence."""
    is_chinese = (
        response_language == "zh-CN"
        if response_language in {"en", "zh-CN"}
        else any("\u3400" <= char <= "\u9fff" for char in str(question or ""))
    )
    if is_chinese:
        return "当前检索到的证据不足以可靠回答该问题。"
    return "The retrieved passages are insufficient to answer this question reliably."


_GENERAL_CONCEPT_LIMITATION = re.compile(
    r"(?is)^(?:\s*(?:the\s+)?(?:retrieved|available|cited)\s+"
    r"(?:passages?|evidence|filing\s+evidence).{0,80}"
    r"(?:insufficient|does\s+not\s+establish|cannot\s+answer).*$|"
    r"\s*当前(?:检索到的)?(?:证据|财报证据)不足[^。！？]*[。！？]?\s*)$"
)


def _prepare_general_concept_answer(
    question: str,
    raw_answer: str,
) -> tuple[str, tuple[str, ...]]:
    """Keep a provider's educational answer outside the filing gate.

    ``GENERAL_CONCEPT`` questions (for example, "what is gross margin?") do
    not ask for a company, period, or filing fact.  Running their explanatory
    examples through the financial citation validator incorrectly treats the
    examples as unsupported financial claims and can turn a valid definition
    into a refusal.  The answer still goes through structural cleanup and
    citation-marker removal, but it intentionally has no filing citations.
    """

    text = re.sub(r"\[Evidence\s+\d+\]", "", str(raw_answer or ""), flags=re.IGNORECASE)
    text = _clean_structural_artifacts(text).strip()
    removed: list[str] = []
    kept: list[str] = []
    for line in text.splitlines():
        if _GENERAL_CONCEPT_LIMITATION.fullmatch(line.strip()):
            removed.append(line)
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    if text:
        return text, tuple(removed)
    chinese = any("\u3400" <= char <= "\u9fff" for char in current_turn_query(question))
    fallback = (
        "毛利率是销售收入扣除直接成本后，毛利占销售收入的比例。"
        "例如卖出 100 元、直接成本 60 元，毛利率就是 40%。"
        if chinese
        else (
            "Gross margin is the share of revenue left after direct costs. "
            "For example, if a product sells for $100 and its direct cost is $60, "
            "the gross margin is 40%."
        )
    )
    return fallback, tuple(removed)


def _scope_claim_fragments(line: str) -> list[str]:
    """Split an answer line into clauses without breaking decimals/citations."""
    bound = re.sub(
        r"([.;；。!?])\s*((?:\[Evidence\s+\d+\]\s*)+)",
        lambda match: " " + match.group(2).strip() + match.group(1) + " ",
        line,
        flags=re.I,
    )
    # Requiring whitespace after a Latin full stop avoids splitting decimals
    # such as 17.2%; CJK sentence punctuation may be immediately adjacent.
    fragments = re.split(r"(?<=[!?。！？；;])\s*|(?<=\.)\s+", bound)
    return [fragment for fragment in fragments if fragment.strip()]


def _scope_answer(question: str, answer: str) -> tuple[str, tuple[str, ...]]:
    """Drop answer claims that exceed the financial scope the user requested."""
    intent_question = current_turn_query(question)
    scope = classify_query_scope(intent_question)
    if is_nonfinancial_business_development_summary(intent_question):
        financial_metrics = {
            "revenue",
            "automotive_revenue",
            "services_revenue",
            "data_center_revenue",
            "edge_computing_revenue",
            "gross_profit",
            "net_income",
            "operating_income",
            "gross_margin",
            "operating_margin",
            "eps",
            "operating_cash_flow",
            "free_cash_flow",
        }
        financial_heading = re.compile(
            r"(?i)^\s{0,3}#{0,3}\s*(?:financial\s+(?:summary|performance|results?)|"
            r"财务(?:摘要|表现|业绩|情况)|经营业绩)\s*:?\s*$"
        )
        business_heading = re.compile(
            r"(?i)^\s{0,3}#{0,3}\s*(?:business\s+developments?|operational\s+highlights?|"
            r"业务发展|业务进展|运营亮点|经营动态)\s*:?\s*$"
        )
        event_language = re.compile(
            r"(?i)launch|launched|roll(?:ed)?\s+out|deployed|began|opened|expanded|"
            r"production|deliver(?:y|ies)|robotaxi|cybercab|optimus|FSD|storage|"
            r"milestone|initiative|partnership|announced|introduced|built|installed|"
            r"推出|发布|启动|部署|开展|扩大|生产|交付|储能|里程碑|合作|建成|安装|投产|开设"
        )
        financial_section = False
        kept: list[str] = []
        removed: list[str] = []
        for line in answer.splitlines():
            if financial_heading.search(line):
                financial_section = True
                kept.append(line)
                continue
            if business_heading.search(line):
                financial_section = False
                kept.append(line)
                continue
            fragments = _scope_claim_fragments(line)
            retained: list[str] = []
            for fragment in fragments:
                metrics = set(canonical_metrics(fragment))
                if metrics & financial_metrics:
                    removed.append(fragment)
                elif (
                    financial_section
                    and extract_normalized_numbers(fragment)
                    and not event_language.search(fragment)
                ):
                    # A financial-summary table is not evidence of a dated
                    # business development. Keep operational milestones and
                    # launch/update claims, but not adjacent financial stats.
                    removed.append(fragment)
                else:
                    retained.append(fragment)
            if retained:
                kept.append(" ".join(retained))
            elif not line.strip():
                kept.append(line)
        return "\n".join(kept).strip(), tuple(removed)
    risk_only_query = bool(
        re.search(r"(?i)\brisk\b|\brisks\b|\bchallenge\b|\bchallenges\b|风险|挑战", intent_question)
        and not canonical_metrics(intent_question)
    )
    if risk_only_query:
        # Risk answers may contain quantitative exposure evidence, but a
        # supported revenue/earnings fact is not automatically relevant just
        # because it came from the same filing. Keep metric claims only when
        # the same sentence connects them to an identified risk mechanism.
        risk_link = re.compile(
            r"(?i)risk|uncertain|challenge|exposure|concentrat|depend|reliance|"
            r"vulnerab|threat|pressure|shortage|constraint|regulat|tariff|litigat|"
            r"debt|liquidity|supply|safety|风险|不确定|挑战|暴露|集中|依赖|脆弱|"
            r"威胁|压力|短缺|约束|监管|关税|诉讼|债务|流动性|供应|安全"
        )
        kept: list[str] = []
        removed: list[str] = []
        for line in answer.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                kept.append(line)
                continue
            fragments = _scope_claim_fragments(line)
            kept_fragments: list[str] = []
            for fragment in fragments:
                if not fragment.strip():
                    continue
                metrics = canonical_metrics(fragment)
                if metrics and not risk_link.search(fragment):
                    removed.append(fragment)
                else:
                    kept_fragments.append(fragment)
            if kept_fragments:
                kept.append(" ".join(kept_fragments))
        return "\n".join(kept).strip(), tuple(removed)

    segment_overview = bool(
        scope == QueryScope.SUMMARY
        and re.search(
            r"\b(?:business\s+)?segments?\b|\bbusiness\s+lines\b|"
            r"业务分部|业务板块|各业务|分部情况",
            question,
            re.IGNORECASE,
        )
        and not canonical_metrics(intent_question)
    )
    if segment_overview:
        overview_with_headlines = bool(
            re.search(
                r"\b(?:summari[sz]e|overview|major|main|key)\b|总结|概览|主要|关键",
                intent_question,
                re.IGNORECASE,
            )
        )
        # Segment summaries can include segment-level metrics, but unrelated
        # consolidated figures should not be appended as extra answer claims
        # unless the user explicitly asked for a broad/major segment overview;
        # those questions need headline context to interpret the segment mix.
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
        consolidated_metrics = {
            "revenue", "net_income", "operating_income", "eps",
            "gross_margin", "operating_margin", "operating_cash_flow",
        }
        kept, removed = [], []
        for line in answer.splitlines():
            kept_fragments: list[str] = []
            for fragment in _scope_claim_fragments(line):
                line_metrics = set(canonical_metrics(fragment))
                if (
                    line_metrics & consolidated_metrics
                    and not line_metrics & segment_metrics
                    and not overview_with_headlines
                    and not _EVIDENCE_ABSENCE.search(fragment)
                ):
                    removed.append(fragment)
                else:
                    kept_fragments.append(fragment)
            if kept_fragments:
                kept.append(" ".join(kept_fragments))
            elif not line.strip():
                kept.append(line)
        return "\n".join(kept).strip(), tuple(removed)

    if scope not in {QueryScope.FACT, QueryScope.COMPARE} or not canonical_metric_id(intent_question):
        return answer, ()
    irrelevant = re.compile(
        r"business strategy|ai technology|infrastructure|competitive advantages|investment (?:implications|outlook)|"
        r"opportunities|risks|future outlook|业务战略|商业战略|人工智能技术|基础设施|"
        r"竞争优势|投资建议|投资展望|风险|未来展望", re.I,
    )
    kept, removed = [], []
    skip = False
    for line in answer.splitlines():
        heading = line.strip().strip("#* ").strip()
        is_heading = line.lstrip().startswith("#") or bool(re.fullmatch(r"\d+[.)]\s+[^.!?。]+", heading))
        if is_heading:
            skip = bool(irrelevant.search(heading))
        if skip:
            removed.append(line)
        else:
            kept.append(line)
    return "\n".join(kept), tuple(removed)


_EN_REFUSAL = "Insufficient evidence to support this numeric claim."
_ZH_REFUSAL = "证据不足，无法可靠支持该数字结论。"
_REFUSAL_FRAGMENT = re.compile(
    r"(?i)insufficient evidence to support this numeric claim\.?|"
    r"证据不足，无法可靠支持该数字结论。?"
)
_RETRIEVAL_LIMITATION = re.compile(
    r"(?i)(?:(?:the\s+)?(?:retrieved\s+passages|retrieved\s+evidence|available\s+evidence)\s+"
    r"(?:are|is)\s+insufficient\s+to\s+(?:establish\s+this\s+information|"
    r"answer\s+(?:this|the)\s+question\s+reliably|reliably\s+answer\s+"
    r"(?:this|the)\s+question|support\s+(?:this|the)\s+answer)\.?|"
    r"当前检索到的证据不足以(?:确认该信息|可靠回答该问题|回答该问题|"
    r"可靠回答此问题|确认该事项)。?)"
)
_EVIDENCE_ABSENCE = re.compile(
    r"(?i)(?:\b(?:evidence|filing|report|document|source|passages?|provided data)\s+"
    r"(?:does not|doesn't|did not|didn't|do not|don't)\s+"
    r"(?:provide|contain|include|show|identify|disclose|report|establish)\b|"
    r"\b(?:not provided|not contained|not included|not disclosed|not reported|not available|"
    r"no\s+(?:[\w-]+\s+){0,5}(?:revenue|sales|income|earnings|margin|eps|cash flow|"
    r"segment data|business segments)\b|"
    r"(?:is|are|remains?)\s+(?:absent|missing|unavailable)\b|"
    r"(?:evidence|filing|report|document|source)\s+(?:lacks?|omits?)\b|"
    r"\bno\b.{0,180}\b(?:figures?|values?|facts?|data|breakdown|disclosures?)\s+"
    r"(?:appear|appears|are|is|were|was)\s+(?:in|from|within)\s+(?:the\s+)?"
    r"(?:retrieved\s+)?(?:evidence|filing|report|document|source)\b|"
    r"no\s+(?:[\w-]+\s+){0,12}(?:figures?|values?|facts?|data|breakdown|disclosures?)\s+"
    r"(?:appear|appears|are|is|were|was)\s+(?:in|from|within)\s+(?:the\s+)?"
    r"(?:evidence|filing|report|document|source)\b|"
    r"cannot determine|can't determine|unable to determine|unable to verify|"
    r"insufficient evidence|evidence.{0,24}insufficient)\b|"
    r"(?:證據|证据|财报|財報|报告|報告|资料|資料|文档|文件).{0,36}"
    r"(?:未提供|未披露|未报告|未報告|没有包含|沒有包含|没有出现|沒有出現|不包含|不包括|缺少|缺失|未见|未找到|不存在|无法确认|無法確認|无法确定|無法確定)|"
    r"(?:未提供|未披露|未报告|未報告|没有包含|沒有包含|没有出现|沒有出現|不包含|不包括|缺少|缺失|未见|未找到|不存在).{0,36}"
    r"(?:财报|財報|报告|報告|证据|證據|资料|資料|文档|文件)|"
    r"所引财报证据不足以支持该表述|"
    r"(?:没有|沒有|未能|无法|無法).{0,12}(?:提供|披露|报告|報告|确认|確認|找到|确定|確定))"
)
_GROWTH_EVIDENCE_ABSENCE = re.compile(
    r"(?i)(?:\b(?:cannot|can't|unable to|insufficient(?:ly)?)\b.{0,90}"
    r"\b(?:assess|assessed|evaluate|evaluated|determine|compare)\b.{0,90}"
    r"\b(?:revenue|revenues|sales|growth)\b|"
    r"\b(?:not|cannot|can't)\s+(?:be\s+)?(?:assessable|assessed|evaluated|determined|verified|scored)\b.{0,90}"
    r"\b(?:revenue|revenues|sales|growth)\b|"
    r"\b(?:revenue|revenues|sales|growth)\b.{0,90}"
    r"\b(?:cannot|can't|unable to|not)\s+(?:be\s+)?(?:assessable|assessed|evaluated|determined|verified|scored)\b|"
    r"\bno\s+(?:[\w-]+\s+){0,8}(?:revenue|revenues|sales|growth)\s+"
    r"(?:figure|figures|value|values|data|evidence)\b|"
    r"\b(?:evidence|filing|report|document|source)\s+contains?\s+no\s+(?:[\w-]+\s+){0,8}"
    r"(?:revenue|revenues|sales|growth)(?:\s+(?:figure|figures|value|values|data|evidence))?\b|"
    r"\b(?:revenue|revenues|sales|growth)(?:\s+(?:figure|figures|value|values|data))?\b.{0,60}"
    r"\b(?:absent|missing|unavailable)\b|"
    r"(?:无法|不能|不足以|难以).{0,24}(?:评估|判断|比较|确认).{0,36}"
    r"(?:营收|收入|销售额|增长))"
)

_UNSTRUCTURED_METRIC_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"(?i)\b(?:price\s+target|target\s+price|12[- ]month\s+target)\b|股价目标|目标股价|目标价"),
        ("price target", "target price", "12-month target", "股价目标", "目标股价", "目标价"),
    ),
    (
        re.compile(r"(?i)\b(?:expected\s+stock\s+price|stock\s+price\s+(?:forecast|prediction)|future\s+stock\s+price)\b|预期股价|(?:预测|未来)股价"),
        (
            "expected stock price", "stock price forecast", "stock price prediction",
            "future stock price", "预期股价", "股价预测", "预测股价", "未来股价",
        ),
    ),
    (
        re.compile(r"(?i)\b(?:stock|share)\s+price\b|股价|股票价格"),
        ("stock price", "share price", "股价", "股票价格"),
    ),
    (
        re.compile(r"(?i)\bmarket\s+share\b|市场份额|市场占有率"),
        ("market share", "市场份额", "市场占有率"),
    ),
    (
        re.compile(r"(?i)\b(?:gross\s+hires?|hires?|employees?\s+hired)\b|招聘人数|招聘总人数|新招聘"),
        ("gross hires", "gross hire", "hires", "employees hired", "招聘人数", "招聘总人数", "新招聘"),
    ),
)


def _unstructured_metric_aliases(question: str) -> tuple[str, ...] | None:
    question_lower = str(question or "").casefold()
    for pattern, aliases in _UNSTRUCTURED_METRIC_PATTERNS:
        if not pattern.search(question_lower):
            continue
        return aliases
    return None


def _unstructured_metric_answer_is_grounded(
    question: str,
    answer: str,
    evidence: Iterable[Evidence],
) -> bool:
    """Require same-citation, same-local-row support for non-ledger metrics.

    A keyword anywhere in a chunk is not enough: the chunk might mention
    market share in one paragraph and contain a percentage for an unrelated
    metric elsewhere. Numeric claims must be backed by values in the same
    source fragment that names the requested metric.
    """
    aliases = _unstructured_metric_aliases(question)
    if aliases is None:
        return True
    items = list(evidence)
    seen_claim = False
    safe_refusal = re.compile(
        r"(?i)insufficient evidence|does not establish the requested metric|"
        r"证据不足|未能证明所询|无法可靠作答"
    )
    for raw_line in str(answer or "").splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"\|?\s*:?-{2,}:?(?:\s*\|\s*:?-{2,}:?)*\s*\|?", line):
            continue
        if safe_refusal.search(line):
            continue
        if line.startswith("#") or re.fullmatch(r"[*_`|\s-]+", line):
            continue
        seen_claim = True
        references = [int(value) for value in re.findall(r"\[Evidence\s+(\d+)\]", line, re.I)]
        cited = [items[rank - 1] for rank in references if 1 <= rank <= len(items)]
        if not cited:
            return False
        claim_text = re.sub(r"\[Evidence\s+\d+\]", "", line, flags=re.I)
        claim_companies = {canonical_company(value) for value in extract_companies(claim_text)}
        if claim_companies:
            cited = [item for item in cited if canonical_company(item.company) in claim_companies]
        claim_numbers = extract_normalized_numbers(claim_text)
        if not claim_numbers:
            # These requests require a numeric answer. A qualitative narrative
            # that merely repeats the metric name is not proof of a value.
            return False
        supported = False
        for item in cited:
            source_lines = [
                fragment.strip()
                for fragment in re.split(r"[\r\n]+|(?<=[;。.!?])\s+", str(item.content or ""))
                if fragment.strip()
            ]
            for source_line in source_lines:
                if not any(alias.casefold() in source_line.casefold() for alias in aliases):
                    continue
                source_numbers = extract_normalized_numbers(source_line)
                if all(
                    any(numbers_equivalent(value, source_value) for source_value in source_numbers)
                    for value in claim_numbers
                ):
                    supported = True
                    break
            if supported:
                break
        if not supported:
            return False
    return seen_claim


def _insufficient_metric_answer(question: str) -> str:
    query = str(question or "").casefold()
    for pattern, _ in _UNSTRUCTURED_METRIC_PATTERNS:
        if not pattern.search(query):
            continue
        if any(token in query for token in ("hire", "hires", "employee", "招聘", "员工")):
            return (
                "现有财报证据未能证明所询招聘人数，无法可靠作答。"
                if any("\u3400" <= char <= "\u9fff" for char in query)
                else "The available filing evidence does not establish the requested metric: hires."
            )
        if any(token in query for token in ("market share", "市场份额", "市场占有率")):
            return (
                "现有财报证据未能证明所询市场份额，无法可靠作答。"
                if any("\u3400" <= char <= "\u9fff" for char in query)
                else "The available filing evidence does not establish the requested metric: market share."
            )
        target_terms = ("price target", "target price", "target", "目标价", "股价目标", "目标股价")
        if any(token in query for token in target_terms):
            return (
                "现有财报证据未能证明所询股价目标，无法可靠作答。"
                if any("\u3400" <= char <= "\u9fff" for char in query)
                else "The available filing evidence does not establish the requested metric: price target."
            )
        if any(token in query for token in (
            "expected", "forecast", "prediction", "future", "next", "2027", "12 months",
            "12-month", "预期", "预测", "未来",
        )):
            return (
                "现有财报证据未能证明所询股价预测，无法可靠作答。"
                if any("\u3400" <= char <= "\u9fff" for char in query)
                else "The available filing evidence does not establish the requested metric: stock price forecast."
            )
        if any(token in query for token in ("stock price", "share price", "股价", "股票价格")):
            return (
                "现有财报证据未能证明所询股价，无法可靠作答。"
                if any("\u3400" <= char <= "\u9fff" for char in query)
                else "The available filing evidence does not establish the requested metric: stock price."
            )
        return (
            "现有财报证据未能证明所询股价目标，无法可靠作答。"
            if any("\u3400" <= char <= "\u9fff" for char in query)
            else "The available filing evidence does not establish the requested metric: price target."
        )
    if any("\u3400" <= char <= "\u9fff" for char in str(question or "")):
        return "现有财报证据未能证明所询指标，无法可靠作答。"
    return "The available filing evidence does not establish the requested metric."


def _answer_language_mismatch(
    question: str,
    answer: str,
    response_language: str | None = None,
) -> bool:
    """Return whether the response prose clearly ignores the user's language.

    Short entity/unit tokens such as ``NVIDIA``, ``Q1 FY2027`` and ``USD`` are
    acceptable in a Chinese answer.  The check is deliberately only a guard
    for an answer written almost entirely in the other language; it does not
    attempt to score code-switching or translate arbitrary prose.
    """

    value = re.sub(
        r"(?:Growth-driver source excerpt|财报原文（增长相关驱动）)[:：]\s*"
        r"[\"“].*?[\"”]\s*\[Evidence\s+\d+\]",
        "",
        str(answer or ""),
        flags=re.I | re.S,
    )
    value = re.sub(r"\[Evidence\s+\d+\]", "", value, flags=re.I)
    cjk = len(re.findall(r"[\u3400-\u9fff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    expects_chinese = (
        response_language == "zh-CN"
        if response_language in {"en", "zh-CN"}
        else any("\u3400" <= char <= "\u9fff" for char in current_turn_query(question))
    )
    if expects_chinese:
        # Company names, financial acronyms, and period labels are naturally
        # Latin in Chinese answers.  Detect a language violation by the share
        # of Latin prose, not by requiring the answer to contain almost no
        # Chinese at all; otherwise a short Chinese heading can mask a wholly
        # English response.
        if response_language == "zh-CN":
            # Explicit Chinese UI selections require translated financial
            # labels/scales, even when the rest of a short answer is Chinese.
            # Acronyms and filing periods remain acceptable; English metric
            # words and currency scales do not.
            if re.search(
                r"(?i)\b(?:revenue|net income|net profit|gross profit|gross margin|"
                r"operating income|operating cash flow|free cash flow|billion|million|"
                r"thousand|basis points|fiscal year|quarter)\b|\b(?:CNY|RMB|USD)\b",
                value,
            ):
                return True
        return latin >= 24 and latin >= max(24, (cjk + latin) * 0.8)
    # An English response may retain a company name written in CJK, but
    # Chinese metric labels or prose still violate an explicitly selected
    # English UI language. Strip named issuers first, then reject even short
    # remaining Chinese phrases (for example, "净利润").
    if response_language == "en":
        for company in extract_companies(current_turn_query(question)):
            if any("\u3400" <= char <= "\u9fff" for char in company):
                value = value.replace(company, "")
        cjk = len(re.findall(r"[\u3400-\u9fff]", value))
        return cjk >= 2
    # Preserve the historical tolerance for an isolated Chinese source term
    # when no explicit UI language was supplied by an older API client.
    return cjk >= 12 and cjk >= (cjk + latin) * 0.12


def _remove_driver_absence_claims(answer: str) -> tuple[str, tuple[str, ...]]:
    """Drop stale refusals/driver denials when retrieved text proves a driver."""

    def contradicted_by_driver(fragment: str) -> bool:
        value = fragment.strip()
        return bool(
            is_driver_absence_claim(value)
            or _RETRIEVAL_LIMITATION.fullmatch(value)
            or _REFUSAL_FRAGMENT.fullmatch(value)
            or re.fullmatch(
                r"(?i)(?:the cited filing evidence is insufficient to support this statement\.?|"
                r"所引财报证据不足以支持该表述。?)",
                value,
            )
        )

    kept_lines: list[str] = []
    removed: list[str] = []
    for line in str(answer or "").splitlines():
        fragments = _scope_claim_fragments(line)
        kept_fragments = [
            fragment for fragment in fragments
            if fragment.strip() and not contradicted_by_driver(fragment)
        ]
        removed.extend(
            fragment for fragment in fragments if contradicted_by_driver(fragment)
        )
        if kept_fragments:
            kept_lines.append(" ".join(kept_fragments))
        elif not fragments and not line.strip():
            kept_lines.append(line)
    return "\n".join(kept_lines).strip(), tuple(removed)


def _render_driver_source_excerpt(question: str, passages) -> str:
    chinese = any("\u3400" <= char <= "\u9fff" for char in current_turn_query(question))
    explicit_attribution = any(
        passage.explicit_financial_attribution for passage in passages
    )
    financial_change_cause = bool(
        re.search(
            r"declin|decreas|drop|fall|下降|减少|下滑|降低|收窄",
            str(question or ""),
            re.I,
        )
        and is_explicit_growth_driver_question(question)
    )
    if explicit_attribution:
        if financial_change_cause:
            heading = (
                "### \u8d22\u62a5\u539f\u6587"
                "\uff08\u62a5\u544a\u671f\u8d22\u52a1\u53d8\u5316\u7684\u660e\u786e\u5f52\u56e0\uff09"
                if chinese
                else "### Filing excerpt (explicit attribution of the reported financial change):"
            )
        else:
            heading = (
                "### \u8d22\u62a5\u539f\u6587\uff08\u589e\u957f\u76f8\u5173\u9a71\u52a8\uff09"
                if chinese
                else "### Growth-driver source excerpt:"
            )
    else:
        heading = (
            "### \u8d22\u62a5\u76f8\u5173\u80cc\u666f"
            "\uff08\u672a\u660e\u786e\u5f52\u56e0\u4e8e\u672c\u62a5\u544a\u671f\u589e\u957f\uff09"
            if chinese
            else "### Related filing context "
            "(not an explicit attribution of reported-period growth):"
        )
    rendered = [heading]
    for passage in passages:
        issuer = f"{passage.company.title()}: " if passage.company else ""
        source_text = (
            passage.text
            if re.search(r"[\u3400-\u9fff]", passage.text)
            else f"\u201c{passage.text}\u201d"
        )
        rendered.append(
            f"{issuer}{source_text} [Evidence {passage.evidence_rank}]"
        )
    return "\n".join(rendered)


def _narrative_driver_coverage(answer: str, passages) -> set[str]:
    """Return issuers whose cited growth context is actually present.

    A single supported driver for one issuer is not enough for a multi-company
    growth comparison.  Keep this check deliberately structural: the answer
    must cite a passage rank and name the same issuer.  If a provider omits an
    issuer, the caller can append the bounded source excerpts for every
    retrieved issuer instead of silently accepting an incomplete comparison.
    """

    ranks = {
        int(value)
        for value in re.findall(r"\[Evidence\s+(\d+)\]", str(answer or ""), re.I)
    }
    named = {
        canonical_company(company)
        for company in extract_companies(str(answer or ""))
    }
    return {
        canonical_company(passage.company)
        for passage in passages
        if passage.company
        and passage.evidence_rank in ranks
        and canonical_company(passage.company) in named
    }


def _render_risk_context_excerpt(question: str, evidence: list[Evidence]) -> str:
    """Render bounded, cited risk sentences when the model used the wrong language."""

    chinese = any("\u3400" <= char <= "\u9fff" for char in current_turn_query(question))
    period_specific = bool(extract_periods(current_turn_query(question)))
    if chinese:
        heading = (
            "### 财报风险背景（未明确对应所询报告期）"
            if period_specific
            else "### 财报风险摘录"
        )
    else:
        heading = (
            "### Related general risk disclosures (not period-specific):"
            if period_specific
            else "### Risk disclosures from the cited filings:"
        )
    rendered = [heading]
    selected = 0
    for rank, item in enumerate(evidence, 1):
        sentences = re.split(
            r"(?<=[.!?。！？;；])\s*|[\r\n]+",
            str(item.content or ""),
        )
        for sentence in sentences:
            value = sentence.strip().strip("\"'“”‘’ ")
            if not value or not _RISK_CONTEXT_CUE.search(value):
                continue
            # PDF chunking can begin in the middle of an English word or
            # sentence (for example ``...ions and management``).  Do not
            # expose that fragment as a quoted source excerpt; a later
            # complete sentence from the same disclosure is safer and more
            # readable.  Chinese chunks do not use this heuristic.
            if re.match(r"^[a-z]", value):
                # PDF layout extraction can split a disclosure at the page or
                # chunk boundary, leaving a lowercase continuation such as
                # ``ing Vera Rubin ... Important factors ...``.  Do not emit
                # that unreadable prefix, but retain the complete risk clause
                # beginning at a deterministic disclosure anchor when one is
                # present in the same source sentence.
                anchor = re.search(
                    r"(?i)(?:important factors that could cause actual results to differ materially include:|"
                    r"risks and uncertainties that could cause results to be materially different than expectations\.)",
                    value,
                )
                if anchor:
                    value = value[anchor.start():].strip()
                else:
                    continue
            # A broad ``regulatory`` cue can also match an ordinary financial
            # performance sentence such as ``regulatory credit revenue``.
            # Risk fallback must not surface that table/MD&A fragment as a
            # risk disclosure, especially when it would fail qualitative
            # citation validation.
            metric_only = re.search(
                r"(?i)\b(?:revenue|income|gross\s+profit|operating\s+margin|"
                r"expenses?|deliveries|SBC|gross\s+margin|net\s+sales)\b",
                value,
            )
            risk_specific = re.search(
                r"(?i)\b(?:risk|uncertain(?:ty|ties)?|laws?|regulations?|"
                r"recall|competition|supply\s+chain|tariff\s+risks?|"
                r"liability|financing|indebtedness|foreign\s+exchange|"
                r"constraint(?:s|ed)?|not\s+assum(?:e|ing)|excluded|exclusion)\b|"
                r"风险|不确定性|法规|召回|竞争|供应链|关税风险|责任|融资|债务|汇率",
                value,
            )
            if metric_only and not risk_specific:
                continue
            issuer = str(item.company or item.metadata.get("company", "")).strip()
            prefix = f"{issuer.title()}: " if issuer else ""
            excerpt = value[:360]
            if len(value) > 360:
                excerpt = excerpt.rstrip() + "…"
            rendered.append(f"- {prefix}{excerpt} [Evidence {rank}]")
            selected += 1
            if selected >= 4:
                return "\n".join(rendered)
    return "\n".join(rendered)


def _render_segment_source_excerpt(question: str, evidence: list[Evidence]) -> str:
    """Render bounded filing-native segment facts when model prose is unsafe.

    Segment disclosures are not uniform across issuers: one filing may use
    titled sections (Data Center/Edge Computing), while another exposes
    Products/Services net-sales rows under a generic table heading. The
    excerpt is built only from source lines containing a recognized segment
    label and a numeric value, then revalidated by the normal citation gate.
    """

    chinese = any("\u3400" <= char <= "\u9fff" for char in current_turn_query(question))
    heading = "### 财报分部披露摘录" if chinese else "### Segment disclosures from the cited filings:"
    rendered = [heading]
    seen: set[tuple[str, str]] = set()
    selected = 0
    for rank, item in enumerate(evidence, 1):
        content = str(item.content or "")
        label_match = _SEGMENT_SOURCE_LABEL.search(content)
        has_growth_clause = bool(
            re.search(
                r"(?i)\b(?:increased|decreased|grew|growth|higher|lower|driven\s+by)\b|"
                r"增长|增加|上升|下降|提高|主要由",
                content,
            )
        )
        if not _SEGMENT_SOURCE_CUE.search(content) or not (
            extract_normalized_numbers(content) or (label_match and has_growth_clause)
        ):
            continue
        section = str(item.metadata.get("section") or "").strip()
        if not section:
            first_line = next(
                (line.strip() for line in content.splitlines() if line.strip()),
                "",
            )
            if first_line.casefold() in {"data center", "edge computing"}:
                section = first_line
        # Do not treat an outlook sentence such as "not assuming Data Center
        # revenue" as a segment disclosure. A titled Data Center/Edge section
        # or a filing-native Products/Services label is required.
        label_value = label_match.group(0).strip() if label_match else ""
        label_is_section = label_value.casefold() in {"data center", "edge computing"}
        structured_product_label = bool(
            label_match
            and re.search(r"(?i)resolved\s+financial\s+label\s*:", label_value)
        )
        disaggregated_product_label = bool(
            label_match
            and re.search(r"(?i)disaggregated\s+(?:net\s+sales|revenue)|reportable\s+segment", content)
            and not label_is_section
        )
        qualitative_segment_label = bool(
            label_match and has_growth_clause and not label_is_section
        )
        if not (
            section.casefold() in {
                "data center",
                "edge computing",
                "products",
                "services",
                "iphone",
                "ipad",
                "mac",
                "wearables, home and accessories",
            }
            or structured_product_label
            or disaggregated_product_label
            or qualitative_segment_label
        ):
            continue
        if section.casefold() == "outlook" and label_is_section:
            continue
        label = label_value.casefold() if label_match else section.casefold()
        key = (str(item.company or item.metadata.get("company") or "").casefold(), label)
        if key in seen:
            continue
        # Keep the fallback qualitative and bounded. The full PDF table row
        # may contain several periods or malformed decimal spacing; exposing
        # it would create unsupported numeric fragments after sentence
        # splitting. The source label itself is enough to answer which
        # segments are disclosed, and citations remain auditable.
        candidate = re.sub(
            r"(?i)^resolved\s+financial\s+label\s*:\s*", "", label_value,
        ).strip() if label_match else section
        if not extract_normalized_numbers(content) and has_growth_clause:
            candidate = next(
                (
                    re.sub(r"\s+", " ", line).strip()
                    for line in re.split(r"\r?\n+", content)
                    if label_match
                    and label_match.group(0).casefold() in line.casefold()
                    and has_growth_clause
                ),
                candidate,
            )
        if len(candidate) > 320:
            candidate = candidate[:320].rstrip() + "…"
        issuer = str(item.company or item.metadata.get("company") or "").strip()
        prefix = f"{issuer.title()}: " if issuer else ""
        rendered.append(f"- {prefix}{candidate} [Evidence {rank}]")
        seen.add(key)
        selected += 1
        if selected >= 6:
            break
    return "\n".join(rendered) if selected else ""


def _safe_driver_passages(
    question: str,
    passages,
    evidence: Iterable[Evidence],
) -> tuple:
    """Keep only source excerpts that the normal citation gate can support.

    A retrieved chunk may contain a causal-looking table fragment that is not
    lexically tied to the narrative question. Rendering it as a quote would
    make the final result carry an UNSUPPORTED claim even though the quote is
    verbatim. Preflight each excerpt through the same sanitizer and fail
    closed for that fragment.
    """

    safe = []
    candidates = list(evidence)
    for passage in passages:
        issuer = f"{passage.company.title()}: " if passage.company else ""
        source_text = (
            passage.text
            if re.search(r"[\u3400-\u9fff]", passage.text)
            else f"\u201c{passage.text}\u201d"
        )
        line = f"{issuer}{source_text} [Evidence {passage.evidence_rank}]"
        checked = sanitize_answer(
            question, line, candidates, require_qualitative_citations=True,
        )
        if not any(claim.disposition == "UNSUPPORTED" for claim in checked.claims):
            safe.append(passage)
    return tuple(safe)


def _localized_grounded_fallback(
    question: str,
    plan: RequiredFactPlan,
    ledger: FactLedger,
    evidence: list[Evidence],
    response_language: str | None = None,
) -> str:
    """Render only verified planned facts when the draft is in the wrong language."""

    intent_question = current_turn_query(question)
    question_is_chinese = any("\u3400" <= char <= "\u9fff" for char in intent_question)
    requested_is_chinese = (
        response_language == "zh-CN"
        if response_language in {"en", "zh-CN"}
        else question_is_chinese
    )
    if response_language in {"en", "zh-CN"} and requested_is_chinese != question_is_chinese:
        return (
            "当前证据不足以用中文可靠回答该问题。"
            if requested_is_chinese
            else "The available evidence is insufficient to answer this question reliably."
        )
    projected, _, _ = complete_from_fact_ledger(
        "", plan, ledger, question=intent_question, evidence=evidence,
        response_language=response_language,
    )
    if projected.strip():
        return projected.strip()
    if is_growth_narrative_question(intent_question):
        if any("\u3400" <= char <= "\u9fff" for char in intent_question):
            return "现有财报摘录不足以建立完整的跨公司增长排名。"
        return "The cited filing excerpts do not establish a complete cross-company growth ranking."
    if any("\u3400" <= char <= "\u9fff" for char in intent_question):
        return "当前证据不足以用中文可靠回答该问题。"
    return "The available evidence is insufficient to answer this question reliably."


_PROSE_INTENT_CUE = re.compile(
    r"(?i)\b(?:why|factor|factors|driver|drivers|cause|causes|caused|affect|affected|"
    r"impact|influence|growth|performance|perform|what happened)\b|"
    r"\bhow\s+(?:is|was|did)\b.{0,100}\b(?:business|segment|company|service)\b|"
    r"因素|驱动|原因|影响|增长|表现|业绩|经营情况|业务发展|业务进展|怎么样|如何表现"
)

_RISK_CONTEXT_CUE = re.compile(
    r"(?i)\b(?:risk|risks|uncertaint(?:y|ies)|regulatory|regulations?|laws?|"
    r"tariffs?|indebtedness|financing|foreign exchange|competition|recall|"
    r"supply chain|forward[- ]looking|important\s+factors|constraint(?:s|ed)?|not\s+assum(?:e|ing)|"
    r"excluded|exclusion)\b|风险|不确定性|监管|法规|关税|债务|融资|汇率|竞争|召回|"
    r"供应链|约束|限制|未假设|不假设|排除"
)

_SEGMENT_QUERY_CUE = re.compile(
    r"(?i)\b(?:business|operating|reportable)\s+segments?\b|"
    r"\bsegments?\s+(?:breakdown|revenue|performance)\b|"
    r"\brevenue\s+by\s+segment\b|\bby\s+business\s+unit\b|"
    r"业务板块|业务分部|各分部|分部(?:收入|营收|表现)"
)
_SEGMENT_SOURCE_CUE = re.compile(
    r"(?i)\b(?:products?|services?|iphone|ipad|mac|wearables(?:,\s*home\s+and\s+accessories)?|"
    r"data\s+center|edge\s+computing)\s+(?:net\s+sales|revenue)\b|"
    r"\b(?:data\s+center|edge\s+computing)\b|"
    r"产品|服务|数据中心|边缘"
)
_SEGMENT_SOURCE_LABEL = re.compile(
    r"(?i)(?:resolved\s+financial\s+label\s*:\s*)?"
    r"\b(?:products?|services?|iphone|ipad|mac|wearables(?:,\s*home\s+and\s+accessories)?)\s+"
    r"(?:net\s+sales|revenue)\b|\b(?:data\s+center|edge\s+computing)\b"
)

_FOLLOWUP_COMPARE_CUE = re.compile(
    r"(?i)\b(?:compare|comparison)\b|比较|对比"
)


def _is_contextual_followup_compare(question: str, plan: RequiredFactPlan) -> bool:
    """Identify an inherited compare turn whose facts are deterministic.

    Follow-up compare turns often have no metric in the latest user text (for
    example, ``Now compare it with Tesla``).  The resolver adds the prior
    request below a marker.  If we leave the provider prose in this case, the
    model can repeat alternate table values or invent a ratio even though the
    fact ledger already has the authoritative values.  This narrow predicate
    deliberately excludes standalone qualitative comparisons.
    """

    if plan.scope != QueryScope.COMPARE.value:
        return False
    value = str(question or "")
    marker = "\nrelevant prior user request for reference resolution:"
    return bool(
        marker in value.casefold()
        and _FOLLOWUP_COMPARE_CUE.search(current_turn_query(value))
    )


def _can_project_verified_facts_only(
    question: str, plan: RequiredFactPlan, ledger: FactLedger,
) -> bool:
    """Use ledger-only output for fully evidenced fact/comparison queries.

    A direct fact or numeric comparison has a deterministic answer in the
    source. Keeping provider prose in that response can turn otherwise
    correct values into a wrong-company, wrong-period, or unsupported answer.
    This does not apply to summaries, analysis, risks, or general-concept
    questions; comparison plans without a complete set of source facts also
    remain on the ordinary grounded path.
    """
    contextual_followup_compare = _is_contextual_followup_compare(question, plan)
    # Segment-overview answers intentionally retain filing-native labels and
    # explanatory prose in addition to ledger-completed numeric cells. A
    # ledger-only projection would erase those labels and turn a useful
    # comparison into an unlabeled list of numbers.
    segment_overview = bool(
        re.search(
            r"\b(?:business\s+)?segments?\b|\bbusiness\s+lines\b|"
            r"业务分部|业务板块|各业务|分部情况",
            current_turn_query(question),
            re.IGNORECASE,
        )
    )
    if (
        plan.scope not in {QueryScope.FACT.value, QueryScope.COMPARE.value}
        or not plan.required
        or segment_overview
        or (
            _PROSE_INTENT_CUE.search(current_turn_query(question))
            and not contextual_followup_compare
        )
    ):
        return False
    statuses = plan.statuses(ledger, "")
    if not statuses:
        return False
    if not contextual_followup_compare and not all(status.available for status in statuses):
        return False
    if contextual_followup_compare and not any(status.available for status in statuses):
        return False
    # A growth requirement may be derivable from two period facts without a
    # directly stored rate. Keep the provider claim in that case so the
    # grounding layer can retain the derivable percentage and its two
    # evidence citations; ledger-only projection would erase it.
    return not any(
        status.spec.growth_basis
        and not ledger.lookup(
            company=status.spec.company,
            metric_id=status.spec.metric_id,
            period=status.spec.period,
            growth_basis=status.spec.growth_basis,
        )
        for status in statuses
    )


def _is_broad_financial_comparison(question: str) -> bool:
    """Identify comparisons where the requested headline facts are deterministic.

    A provider draft for a broad financial-performance comparison often mixes
    GAAP/non-GAAP rows or repeats several table columns.  The fact ledger is
    safer for this narrow intent: it can render one preferred fact per
    company/metric/period and omit conflicting prose.  Strategy, risk, and
    growth-narrative comparisons remain on the normal prose path.
    """

    if classify_query_scope(question) != QueryScope.COMPARE:
        return False
    return bool(
        re.search(
            r"\bfinancial\s+(?:performance|results?)\b|"
            r"\b(?:revenue|sales)\s+(?:performance|comparison|trajectory)\b|"
            r"\bperform(?:ed|ance)\s+financially\b|"
            r"财务表现|财务业绩|财务状况|经营表现|经营业绩",
            current_turn_query(question),
            re.IGNORECASE,
        )
    )


def _preferred_growth_fact(facts):
    """Choose a consolidated reported growth fact from duplicate table rows."""

    def score(fact):
        text = str(fact.evidence_text or "").casefold()
        value = 0
        if re.search(r"\b(?:total\s+(?:net\s+)?sales|total\s+revenues?)\b", text):
            value += 36
        if re.search(r"\brevenue\s+(?:of|decreased|increased|grew|rose|fell)\b", text):
            value += 20
        if any(marker in text for marker in ("services", "energy generation", "automotive")):
            value -= 12
        return (value, float(fact.confidence), str(fact.fact_id))

    return max(facts, key=score)


def _growth_citation_ranks(facts, evidence) -> tuple[int, ...]:
    """Map growth operands to the current trusted evidence rank space."""

    ranks: list[int] = []
    for fact in facts:
        for index, item in enumerate(evidence, start=1):
            chunk_id = str(item.metadata.get("chunk_id", ""))
            if fact.chunk_id and chunk_id == str(fact.chunk_id):
                ranks.append(index)
                break
            source_text = str(item.content or "")
            if fact.evidence_text and fact.evidence_text.strip() in source_text:
                ranks.append(index)
                break
    return tuple(dict.fromkeys(ranks))


def _render_deterministic_growth_ranking(
    question: str,
    plan: RequiredFactPlan,
    ledger: FactLedger,
    evidence,
) -> str:
    """Render a safe ranking from issuer-partitioned revenue YoY facts.

    This is intentionally conservative: every named issuer must have a
    reported or matching-period-derived consolidated revenue YoY value.  The
    output labels issuer-local periods and calls a mixed-period result a
    directional comparison, never a same-quarter ranking.
    """

    companies = [canonical_company(company) for company in extract_companies(question)]
    companies = list(dict.fromkeys(companies))
    if len(companies) < 2:
        return ""

    records: list[dict[str, object]] = []
    for company in companies:
        specs = [
            spec
            for spec in plan.required
            if canonical_company(spec.company or "") == company
            and spec.metric_id == "revenue"
            and spec.growth_basis == "yoy"
        ]
        if not specs:
            return ""
        spec = specs[0]
        reported = ledger.lookup(
            company=company,
            metric_id="revenue",
            period=spec.period,
            growth_basis="yoy",
        )
        if reported:
            selected = _preferred_growth_fact(reported)
            records.append({
                "company": company,
                "period": selected.fact_period or spec.period,
                "value": selected.normalized_value,
                "facts": (selected,),
            })
            continue

        prior_period = _prior_comparable_period(spec.period)
        if not prior_period:
            return ""
        current = ledger.lookup(company=company, metric_id="revenue", period=spec.period)
        prior = ledger.lookup(company=company, metric_id="revenue", period=prior_period)
        if not current or not prior:
            return ""
        current_fact = _preferred_fact(
            current,
            "revenue",
            question=question,
            requested_period=spec.period,
        )
        prior_fact = _preferred_fact(
            prior,
            "revenue",
            question=question,
            requested_period=prior_period,
        )
        derived = derived_growth(
            NormalizedNumber(current_fact.normalized_value, "amount", current_fact.currency),
            NormalizedNumber(prior_fact.normalized_value, "amount", prior_fact.currency),
        )
        if derived is None:
            return ""
        records.append({
            "company": company,
            "period": spec.period,
            "value": derived.value,
            "facts": (current_fact, prior_fact),
        })

    top_value = max(record["value"] for record in records)
    leaders = [
        record for record in records
        if abs(record["value"] - top_value) <= 0.01
    ]
    if len(leaders) != 1:
        return ""
    leader = leaders[0]
    chinese = any("\u3400" <= char <= "\u9fff" for char in str(question or ""))
    labels = {
        "apple": "苹果" if chinese else "Apple",
        "nvidia": "英伟达" if chinese else "NVIDIA",
        "tesla": "特斯拉" if chinese else "Tesla",
        "microsoft": "微软" if chinese else "Microsoft",
    }
    citation_ranks = tuple(
        rank
        for record in records
        for rank in _growth_citation_ranks(record["facts"], evidence)
    )
    if not citation_ranks:
        return ""
    citation_text = " ".join(f"[Evidence {rank}]" for rank in dict.fromkeys(citation_ranks))
    period_set = {str(record["period"] or "") for record in records}
    mixed_periods = len(period_set) > 1
    leader_label = labels.get(str(leader["company"]), str(leader["company"]))
    if chinese:
        qualifier = (
            "各公司报告期不同，因此这里只作方向性比较，不代表同一季度的严格排名。"
            if mixed_periods
            else "各公司采用相同报告期。"
        )
        return (
            f"按各公司财报可验证的营收同比增速，{leader_label}最高。{qualifier} {citation_text}"
        )
    qualifier = (
        "Because the reporting periods differ, this is directional rather than a strict same-quarter ranking."
        if mixed_periods
        else "The issuers use the same reporting period."
    )
    return (
        f"By the reported revenue YoY rates, {leader_label} is highest. {qualifier} {citation_text}"
    )


def _can_project_partial_financial_comparison(
    question: str, plan: RequiredFactPlan, ledger: FactLedger,
) -> bool:
    """Allow a safe partial ledger projection for broad comparisons.

    Unlike a complete fact gate, this intentionally requires at least one
    available fact for every requested company.  Missing metrics stay absent;
    no unrelated value is substituted just to make the comparison look
    complete.  This prevents conflicting provider numbers from surviving while
    preserving the source limitation.
    """

    if not _is_broad_financial_comparison(question) or not plan.required:
        return False
    statuses = plan.statuses(ledger, "")
    if not statuses:
        return False
    requested_companies = {
        canonical_company(str(status.spec.company or ""))
        for status in statuses
        if status.spec.company
    }
    available_companies = {
        canonical_company(str(status.spec.company or ""))
        for status in statuses
        if status.available and status.spec.company
    }
    if not requested_companies or available_companies != requested_companies:
        return False
    return not any(
        status.spec.growth_basis
        and not ledger.lookup(
            company=status.spec.company,
            metric_id=status.spec.metric_id,
            period=status.spec.period,
            growth_basis=status.spec.growth_basis,
        )
        for status in statuses
    )


def _localize_standard_refusals(
    question: str,
    answer: str,
    response_language: str | None = None,
) -> str:
    """Keep deterministic grounding refusals in the requested UI language."""

    chinese = (
        response_language == "zh-CN"
        if response_language in {"en", "zh-CN"}
        else any("\u3400" <= char <= "\u9fff" for char in current_turn_query(question))
    )
    replacements = (
        (
            "Direct financial answer:",
            "直接财务回答：",
        ),
        (
            "Insufficient evidence to support this numeric claim.",
            "证据不足，无法可靠支持该数字结论。",
        ),
        (
            "The cited filing evidence is insufficient to support this statement.",
            "所引财报证据不足以支持该表述。",
        ),
    )
    for english, chinese_text in replacements:
        source, target = (english, chinese_text) if chinese else (chinese_text, english)
        answer = re.sub(re.escape(source), target, answer, flags=re.I)
    return answer


def _compact_refusal_fragments(
    answer: str,
    *,
    has_supported_facts: bool,
) -> str:
    """Remove repeated provider refusal placeholders after fact completion.

    Providers often emit a refusal for a missing sub-field and then also emit
    the supported requested fact.  Repeating that placeholder makes a valid
    answer look contradictory and can cause downstream evaluators to treat
    the response as unsupported.  We retain one refusal only when no trusted
    fact is available at all; explanatory limitation sentences are untouched.
    """

    kept: list[str] = []
    retained_refusal = False
    for raw_line in str(answer or "").splitlines():
        line = raw_line.strip()
        if not line:
            kept.append(raw_line)
            continue
        limitation_matches = list(_RETRIEVAL_LIMITATION.finditer(raw_line))
        if limitation_matches:
            pieces: list[str] = []
            cursor = 0
            for match in limitation_matches:
                pieces.append(raw_line[cursor:match.start()])
                if not has_supported_facts and not retained_refusal:
                    pieces.append(match.group(0))
                    retained_refusal = True
                cursor = match.end()
            pieces.append(raw_line[cursor:])
            cleaned = "".join(pieces)
            cleaned = re.sub(r"\s{2,}", " ", cleaned)
            cleaned = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", cleaned)
            cleaned = re.sub(r"(?:[.;。]\s*){2,}", ". ", cleaned)
            cleaned = cleaned.strip(" \t-•")
            if cleaned:
                kept.append(cleaned)
            continue
        had_refusal = bool(_REFUSAL_FRAGMENT.search(line))
        cleaned = _REFUSAL_FRAGMENT.sub("", line)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", cleaned).strip()
        if cleaned:
            # Remove a trailing placeholder from a conclusion, but keep the
            # factual sentence and its citation intact.
            kept.append(cleaned if had_refusal else raw_line)
            continue
        if had_refusal and not has_supported_facts and not retained_refusal:
            kept.append(_ZH_REFUSAL if any("\u3400" <= char <= "\u9fff" for char in line) else _EN_REFUSAL)
            retained_refusal = True
    return "\n".join(kept).strip()


def _remove_covered_growth_absence_claims(answer: str) -> str:
    """Drop stale growth-evidence disclaimers when the ledger is complete.

    Historical/provider drafts sometimes say that an issuer's revenue growth
    cannot be assessed even though the current trusted context contains the
    issuer's consolidated revenue and YoY operands.  This helper is only used
    after the deterministic ranking gate has proven complete issuer coverage;
    it does not weaken ordinary missing-evidence refusals.
    """

    kept_lines: list[str] = []
    for raw_line in str(answer or "").splitlines():
        if not _GROWTH_EVIDENCE_ABSENCE.search(raw_line):
            kept_lines.append(raw_line)
            continue
        fragments = re.split(r"(?<=[.!?。！？])\s*", raw_line)
        retained = [
            fragment.strip()
            for fragment in fragments
            if fragment.strip() and not _GROWTH_EVIDENCE_ABSENCE.search(fragment)
        ]
        if retained:
            kept_lines.append(" ".join(retained))
    return "\n".join(kept_lines).strip()


_EMPTY_NUMBERED_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:\d+[.)]?|[一二三四五六七八九十]+[、.)]?)\s*$"
)
_EMPTY_BULLET = re.compile(r"^\s*(?:[-*+]\s*)?(?:\*\*)?\s*$")
_INCOMPLETE_COMPARISON_TAIL = re.compile(
    r"(?i)\b(?:vs\.?|versus)\s*(?:\[Evidence\s+\d+\]\s*)+(?:[.;。；])?\s*$"
)
_AFFIRMATIVE_INFERENCE = re.compile(
    r"(?i)\b(?:can\s+be\s+inferred|typically\s+(?:has|have|具备)|"
    r"usually\s+(?:has|have)|it\s+follows\s+that)\b|"
    r"可(?:以)?推断|可(?:以)?推测|通常具备|据此推断"
)
_NEGATED_INFERENCE = re.compile(
    r"(?i)\b(?:cannot|can't|not\s+(?:be\s+)?inferred|not\s+established)\b|"
    r"无法推断|不能推断|无法据此|并非推断"
)


def _clean_structural_artifacts(answer: str) -> str:
    """Remove empty outline markers left after claim-level grounding.

    Sanitization can legitimately remove every claim under a provider-created
    numbered section.  Keeping headings such as ``#### 2.`` makes the final
    response look truncated even though the safety decision was correct.  This
    cleanup is deliberately structural only: it never removes a non-empty
    sentence, citation, number, or evidence excerpt.
    """

    kept: list[str] = []
    previous_blank = False
    for raw_line in str(answer or "").splitlines():
        line = raw_line.strip()
        if _EMPTY_NUMBERED_HEADING.fullmatch(line) or _EMPTY_BULLET.fullmatch(line):
            continue
        if _INCOMPLETE_COMPARISON_TAIL.search(line):
            continue
        if _AFFIRMATIVE_INFERENCE.search(line) and not _NEGATED_INFERENCE.search(line):
            continue
        if not line:
            if previous_blank:
                continue
            previous_blank = True
            kept.append("")
            continue
        previous_blank = False
        kept.append(raw_line.rstrip())
    return "\n".join(kept).strip()


def _refusal_matches_available_fact(line: str, plan: RequiredFactPlan, ledger: FactLedger) -> bool:
    """Detect a stale absence claim only when its same metric/scope is proven."""
    companies = {canonical_company(value) for value in extract_companies(line)}
    periods = extract_periods(line)
    for spec in plan.required:
        facts = ledger.lookup(
            company=spec.company,
            metric_id=spec.metric_id,
            period=spec.period,
            growth_basis=spec.growth_basis,
        )
        line_lower = line.casefold()
        alias_present = _fact_alias_present(line, spec.metric_id)
        if not alias_present and spec.metric_id in {"gross_margin", "operating_margin"}:
            # A generic statement such as "no margin figures are reported"
            # denies either requested margin type. Keep this special case in
            # absence handling only: a bare "margin" must not make an answer
            # containing one value count as both gross and operating margin.
            alias_present = bool(
                re.search(r"\bmargins?\b|利润率", line_lower)
                and not re.search(
                    r"\bgross\b|\boperating\b|毛利|营业利润|经营利润",
                    line_lower,
                )
            )
        if spec.metric_id in {"data_center_revenue", "edge_computing_revenue"} and (
            ("segment" in line_lower and "revenue" in line_lower)
            or ("business" in line_lower and "revenue" in line_lower)
            or ("分部" in line and "收入" in line)
        ):
            alias_present = True
        if not facts or not alias_present:
            continue
        if companies and canonical_company(spec.company or "") not in companies:
            continue
        if spec.period and periods and not any(periods_equivalent(value, spec.period) for value in periods):
            continue
        return True
    return False


def _is_redundant_wrong_period_correction(
    line: str, question: str, plan: RequiredFactPlan, ledger: FactLedger
) -> bool:
    """Drop a number-free outlook-vs-actual correction after its false denial is removed.

    The correction is only redundant when one supported fact exists for the
    requested period. Numeric outlook comparisons remain for ordinary
    grounding and are never removed here.
    """
    if classify_query_scope(question) != QueryScope.FACT:
        return False
    query_periods = extract_periods(question)
    if len(query_periods) != 1:
        return False
    requested_period = query_periods[0]
    line_periods = extract_periods(line)
    if not any(periods_equivalent(period, requested_period) for period in line_periods):
        return False
    if not any(not periods_equivalent(period, requested_period) for period in line_periods):
        return False
    correction = re.search(
        r"\b(?:outlook|guidance|forecast)\b.*\bnot\b.*\b(?:reported|actual|result)\b|"
        r"(?:展望|指引|预测).{0,48}(?:并非|不是|而非).{0,24}(?:实际|报告|实绩)",
        line,
        re.IGNORECASE,
    )
    if not correction:
        return False
    if re.search(
        r"[$€£¥]\s*\d|\d(?:[.,]\d+)?\s*%|\b(?:USD|dollars?|millions?|billions?)\b",
        line,
        re.IGNORECASE,
    ):
        return False
    return any(
        spec.period
        and periods_equivalent(spec.period, requested_period)
        and ledger.lookup(
            company=spec.company,
            metric_id=spec.metric_id,
            period=spec.period,
            growth_basis=spec.growth_basis,
        )
        for spec in plan.required
    )


def _remove_superseded_absence_claims(
    answer: str, question: str, plan: RequiredFactPlan, ledger: FactLedger
) -> tuple[str, tuple[str, ...]]:
    """Remove or scope absence claims to what retrieval actually established.

    Non-financial refusals (e.g. gross employee hires) are not removed merely
    because another metric exists in the same filing. Scope is bound to an
    available fact, matching metric alias, and any company/period named in the
    refusal text. If no matching fact was retrieved, however, a partial top-k
    result cannot prove that the filing itself lacks that information. Rewrite
    the global absence assertion as a retrieval-scoped limitation and remove
    its citation markers, which otherwise imply that an unrelated chunk
    proves absence from the whole report.
    """

    def retrieval_scoped_limitation(line: str) -> str:
        # Preserve the standardized numeric refusal; it makes no claim about
        # whether the complete source document contains the requested fact.
        if _REFUSAL_FRAGMENT.search(line):
            return line
        if any("\u3400" <= char <= "\u9fff" for char in current_turn_query(question)):
            return "当前检索到的证据不足以确认该信息。"
        return "The retrieved passages are insufficient to establish this information."

    kept_paragraphs: list[str] = []
    removed: list[str] = []
    for paragraph in str(answer or "").split("\n\n"):
        kept_lines: list[str] = []
        for line in paragraph.splitlines():
            kept_fragments: list[str] = []
            # Grounding sanitization may place a supported sentence and a
            # refusal in one physical line after splitting citation-bound
            # clauses. Process each sentence independently so a stale
            # evidence-absence statement cannot erase its supported sibling.
            for fragment in _scope_claim_fragments(line):
                if _EVIDENCE_ABSENCE.search(fragment):
                    removed.append(fragment)
                    if _refusal_matches_available_fact(fragment, plan, ledger):
                        continue
                    rewritten = retrieval_scoped_limitation(
                        re.sub(r"\[Evidence\s+\d+\]", "", fragment, flags=re.I).strip()
                    )
                    if rewritten:
                        kept_fragments.append(rewritten)
                elif _is_redundant_wrong_period_correction(fragment, question, plan, ledger):
                    removed.append(fragment)
                else:
                    kept_fragments.append(fragment)
            if kept_fragments:
                kept_lines.append(" ".join(kept_fragments))
            elif not line.strip():
                kept_lines.append(line)
        if kept_lines:
            kept_paragraphs.append("\n".join(kept_lines))
    return "\n\n".join(part for part in kept_paragraphs if part.strip()).strip(), tuple(removed)


_PERIOD_GROWTH_CUE = re.compile(
    r"(?i)\b(?:yoy|year[- ]over[- ]year|year on year|同比)\b|同比"
)
_CLAUSE_BOUNDARY = re.compile(r"(?i)(\s*(?:,|，|;|；|\bwhile\b|\bwhereas\b|\bbut\b|而)\s*)")


def _growth_claim_has_period_support(
    company: str,
    metric_id: str,
    period: str,
    claim: str,
    ledger: FactLedger,
) -> bool:
    """Check a growth percentage only against evidence for its planned period.

    Narrative sentences can cite a filing that contains multiple periods. A
    citation's presence therefore does not prove that its YoY figure belongs
    to the period selected for the issuer/metric in the required-fact plan.
    """

    claimed_percentages = [
        number
        for number in extract_normalized_numbers(claim)
        if number.kind == "percent"
    ]
    if not claimed_percentages:
        return False

    reported = ledger.lookup(
        company=company,
        metric_id=metric_id,
        period=period,
        growth_basis="yoy",
    )
    supported_values = [
        NormalizedNumber(fact.normalized_value, "percent", fact.currency)
        for fact in reported
        if fact.normalized_value is not None
    ]

    if not supported_values:
        prior_period = _prior_comparable_period(period)
        if prior_period:
            current = ledger.lookup(company=company, metric_id=metric_id, period=period)
            prior = ledger.lookup(company=company, metric_id=metric_id, period=prior_period)
            if current and prior:
                current_fact = _preferred_fact(
                    current, metric_id, question=claim, requested_period=period,
                )
                prior_fact = _preferred_fact(
                    prior, metric_id, question=claim, requested_period=prior_period,
                )
                derived = derived_growth(
                    NormalizedNumber(
                        current_fact.normalized_value, "amount", current_fact.currency,
                    ),
                    NormalizedNumber(
                        prior_fact.normalized_value, "amount", prior_fact.currency,
                    ),
                )
                if derived is not None:
                    supported_values.append(derived)

    negative_trend = bool(
        re.search(
            r"(?i)\b(?:down|decreased|declined|fell|lower)\b|下降|减少|下滑",
            claim,
        )
    )
    return any(
        numbers_equivalent(claimed, supported)
        or (
            negative_trend
            and supported.value < 0
            and abs(claimed.value - abs(supported.value)) <= 0.2
        )
        for claimed in claimed_percentages
        for supported in supported_values
    )


def _remove_period_contaminated_growth_claims(
    answer: str,
    plan: RequiredFactPlan,
    ledger: FactLedger,
) -> tuple[str, tuple[str, ...]]:
    """Remove issuer-specific YoY numbers unsupported for the planned period.

    This is intentionally limited to numeric growth claims. Ordinary
    qualitative wording continues through the existing citation validator,
    and claims with no unique planned issuer/metric period are left untouched
    for the normal fail-closed grounding path.
    """

    selected: dict[str, dict[str, list[str]]] = {}
    for spec in plan.required:
        company = canonical_company(spec.company or "")
        if not company or not spec.period or spec.growth_basis:
            continue
        selected.setdefault(company, {}).setdefault(spec.metric_id, []).append(spec.period)
    for metrics in selected.values():
        for metric_id, periods in metrics.items():
            metrics[metric_id] = list(dict.fromkeys(periods))

    if not selected:
        return answer, ()

    labels = {
        "apple": r"\bApple\b|苹果",
        "tesla": r"\bTesla\b|特斯拉",
        "nvidia": r"\bNVIDIA\b|英伟达",
        "microsoft": r"\bMicrosoft\b|微软",
    }
    removed: list[str] = []
    output: list[str] = []
    active_company: str | None = None
    for line in str(answer or "").splitlines():
        companies_in_line = {
            company
            for company, pattern in labels.items()
            if re.search(rf"(?i)(?:{pattern})", line)
        }
        if line.lstrip().startswith("#") and len(companies_in_line) == 1:
            active_company = next(iter(companies_in_line))

        # Company-specific headings often govern a following bullet such as
        # "YoY growth: -3%". Carry that issuer context until another heading.
        if _PERIOD_GROWTH_CUE.search(line) and extract_normalized_numbers(line):
            pieces = _CLAUSE_BOUNDARY.split(line)
            content_indexes = list(range(0, len(pieces), 2))
            changed = False
            keep = {index: True for index in content_indexes}
            for index in content_indexes:
                fragment = pieces[index]
                if not _PERIOD_GROWTH_CUE.search(fragment):
                    continue
                fragment_companies = {
                    company
                    for company, pattern in labels.items()
                    if re.search(rf"(?i)(?:{pattern})", fragment)
                }
                if not fragment_companies and active_company:
                    fragment_companies = {active_company}
                if len(fragment_companies) != 1:
                    continue
                company = next(iter(fragment_companies))
                metrics = canonical_metrics(fragment)
                metric_ids = [
                    metric_id for metric_id in metrics
                    if metric_id in selected.get(company, {})
                ]
                if not metric_ids and len(selected.get(company, {})) == 1:
                    metric_ids = list(selected[company])
                if len(metric_ids) != 1:
                    continue
                periods = selected[company][metric_ids[0]]
                if len(periods) != 1:
                    continue
                if _growth_claim_has_period_support(
                    company, metric_ids[0], periods[0], fragment, ledger,
                ):
                    continue
                keep[index] = False
                changed = True
                removed.append(fragment.strip())

            if changed:
                kept_indexes = [index for index in content_indexes if keep[index]]
                rebuilt: list[str] = []
                for position, index in enumerate(kept_indexes):
                    if position:
                        previous_index = kept_indexes[position - 1]
                        separator_index = previous_index + 1
                        if separator_index < index:
                            rebuilt.append(pieces[separator_index])
                    rebuilt.append(pieces[index])
                # Citations on a multi-issuer sentence are re-bound by the
                # regular final sanitizer after this policy removes a clause.
                output.append(re.sub(r"\[Evidence\s+\d+\]", "", "".join(rebuilt), flags=re.I).strip())
                continue
        output.append(line)
    return "\n".join(output), tuple(removed)


def finalize_grounded_answer(
    question: str,
    raw_answer: str,
    evidence: Iterable[Evidence],
    *,
    response_language: str | None = None,
) -> FinalAnswer:
    """Every completion passes through the final validator before serialization.

    The ledger only supplies missing requested facts, with original citation
    ranks. No legacy unscaled-value appender is run after this boundary.
    """
    intent_question = current_turn_query(question)
    items = list(evidence)
    if classify_query_scope(intent_question) is QueryScope.GENERAL_CONCEPT:
        # Definitions and other general educational questions are deliberately
        # direct-chat answers.  They must not be forced through filing
        # evidence: examples such as "$100 revenue - $60 direct cost" are
        # explanatory arithmetic, not unsupported company financial claims.
        concept_answer, concept_removed = _prepare_general_concept_answer(
            intent_question,
            str(raw_answer),
        )
        concept_grounding = GroundingResult(
            concept_answer,
            [],
            [],
            [],
        )
        empty_ledger = FactLedger()
        empty_plan = infer_required_fact_plan(intent_question, (), empty_ledger)
        return FinalAnswer(
            concept_grounding,
            concept_grounding,
            empty_plan,
            empty_ledger,
            (),
            concept_removed,
            concept_answer,
            False,
        )
    scoped, removed = _scope_answer(intent_question, str(raw_answer))
    risk_only_query = bool(
        re.search(
            r"(?i)\brisk\b|\brisks\b|\bchallenge\b|\bchallenges\b|风险|挑战",
            intent_question,
        )
        and not canonical_metrics(intent_question)
    )
    synthesized_risk_excerpt = ""
    synthesized_segment_excerpt = ""
    risk_context_only = bool(
        classify_query_scope(intent_question) is QueryScope.RISK
        and items
        and all(
            str(item.metadata.get("semantic_support", "")).casefold()
            == "related_context"
            for item in items
        )
    )
    if risk_context_only:
        chinese = any("\u3400" <= char <= "\u9fff" for char in intent_question)
        limitation = (
            "现有财报摘录包含一般风险披露，但未明确对应所询报告期。"
            if chinese
            else (
                "The cited filing contains general risk disclosures but does not "
                "identify risks specific to the requested reporting period."
            )
        )
        # Use only a bounded source excerpt for document-level risks. This
        # prevents a provider draft from presenting generic disclosures as
        # Q2-specific facts or from leaking a wrong-language answer.
        synthesized_risk_excerpt = _render_risk_context_excerpt(intent_question, items)
        scoped = "\n\n".join(
            part
            for part in (
                synthesized_risk_excerpt,
                limitation,
            )
            if part.strip()
        )
    driver_passages = extract_growth_driver_passages(intent_question, items)
    driver_passages = _safe_driver_passages(
        intent_question, driver_passages, items,
    )
    driver_removed: tuple[str, ...] = ()
    synthesized_driver_excerpt = ""
    explicit_driver_passages = tuple(
        passage for passage in driver_passages
        if passage.explicit_financial_attribution
    )
    driver_background_only = bool(
        driver_passages
        and is_explicit_growth_driver_question(intent_question)
        and not explicit_driver_passages
    )
    if driver_background_only:
        # Management commentary can be useful context without being an
        # explicit attribution of the requested quarter's financial growth.
        # Discard provider causal prose in this case; the fact ledger may add
        # independently supported metrics later in the pipeline.
        chinese = any("\u3400" <= char <= "\u9fff" for char in intent_question)
        limitation = (
            "现有财报摘录仅提供相关背景，未明确将其归因于所询报告期的增长。"
            if chinese else (
                "The cited filing excerpts provide related context but do not explicitly "
                "attribute it to growth in the requested reporting period."
            )
        )
        scoped = limitation
        synthesized_driver_excerpt = _render_driver_source_excerpt(
            intent_question, driver_passages,
        )
        scoped = "\n\n".join(
            part for part in (scoped, synthesized_driver_excerpt) if part
        )
        driver_removed = tuple(
            line for line in str(raw_answer or "").splitlines() if line.strip()
        )
    narrative_driver_coverage = _narrative_driver_coverage(scoped, driver_passages)
    required_narrative_companies = {
        canonical_company(passage.company)
        for passage in driver_passages
        if passage.company
    }
    narrative_coverage_missing = bool(
        (is_growth_narrative_question(intent_question) or is_segment_comparison_question(intent_question))
        and required_narrative_companies
        and narrative_driver_coverage != required_narrative_companies
    )
    if (
        driver_passages
        and not driver_background_only
        and (
            not answer_has_cited_growth_driver(scoped, driver_passages)
            or narrative_coverage_missing
        )
    ):
        if explicit_driver_passages:
            # Only a cited, period-compatible statement explicitly connecting
            # a financial result to its cause can overturn an insufficiency
            # claim. Related industry commentary is shown as context instead.
            scoped, driver_removed = _remove_driver_absence_claims(scoped)
        synthesized_driver_excerpt = _render_driver_source_excerpt(
            intent_question, driver_passages,
        )
        scoped = "\n\n".join(
            part for part in (scoped, synthesized_driver_excerpt) if part
        )
    raw_grounding = sanitize_answer(
        question, scoped, items, require_qualitative_citations=True,
    )
    trusted = raw_grounding.evidence
    provider_refusal_projection = False
    deterministic_projection_draft: str | None = None
    if synthesized_driver_excerpt:
        # The first grounding pass removes incompatible/untrusted candidates
        # and compacts citation ranks. Rebuild the synthesized source quote
        # against that exact trusted order; keeping its pre-filter rank can
        # bind the quote to another chunk (or to a rank that no longer exists),
        # especially for a Chinese summary with English filing evidence.
        driver_passages = extract_growth_driver_passages(intent_question, trusted)
        driver_passages = _safe_driver_passages(
            intent_question, driver_passages, trusted,
        )
        synthesized_driver_excerpt = _render_driver_source_excerpt(
            intent_question, driver_passages,
        )
    if not trusted:
        # An empty or scope-mismatched retrieval set cannot support qualitative
        # prose either. Numeric sanitization alone used to leave uncited
        # narrative claims untouched, which let stale-company and
        # out-of-period drafts escape when no trusted chunks survived.
        empty_ledger = FactLedger()
        empty_plan = infer_required_fact_plan(question, (), empty_ledger)
        if risk_only_query and items:
            # A Chinese provider draft can be mojibake or otherwise too far
            # from the English filing wording for the first qualitative pass,
            # leaving no trusted claims even though the retrieved chunks are
            # valid general risk disclosures. Preserve those exact, bounded
            # source sentences rather than returning an empty/refusal-only
            # answer. The excerpt is revalidated before it becomes visible.
            risk_excerpt = _render_risk_context_excerpt(intent_question, items)
            checked_excerpt = sanitize_answer(
                question,
                risk_excerpt,
                items,
                require_qualitative_citations=True,
            )
            if risk_excerpt.strip() and not any(
                claim.disposition == "UNSUPPORTED"
                for claim in checked_excerpt.claims
            ):
                return FinalAnswer(
                    checked_excerpt,
                    raw_grounding,
                    empty_plan,
                    empty_ledger,
                    (),
                    tuple(line for line in str(raw_answer or "").splitlines() if line.strip()),
                    risk_excerpt,
                    False,
                )
        # A model may refuse despite the retrieved filing containing every
        # requested fact. Since the refusal has no citation, ordinary
        # grounding removes all evidence and used to return early here,
        # preventing the deterministic fact ledger from correcting that
        # over-refusal. Project only when every explicit requirement is
        # present and the projection itself passes the citation gate.
        if items:
            refusal_ledger = FactLedger.from_evidence(items)
            refusal_plan = infer_required_fact_plan(question, items, refusal_ledger)
            refusal_statuses = refusal_plan.statuses(refusal_ledger, "")
            projection, projection_ids, _ = complete_from_fact_ledger(
                "", refusal_plan, refusal_ledger,
                question=question, evidence=items, response_language=response_language,
            )
            if (
                refusal_statuses
                and all(status.available for status in refusal_statuses)
                and len(projection_ids) == len(refusal_statuses)
            ):
                projected_grounding = sanitize_answer(
                    question,
                    projection,
                    items,
                    require_qualitative_citations=True,
                )
                if projected_grounding.evidence and not any(
                    claim.disposition == "UNSUPPORTED"
                    for claim in projected_grounding.claims
                ):
                    trusted = projected_grounding.evidence
                    deterministic_projection_draft = projected_grounding.answer
                    provider_refusal_projection = True

        if not trusted:
            raw_text = str(raw_answer or "").strip()
            if raw_text in {_EN_REFUSAL, _ZH_REFUSAL} or _RETRIEVAL_LIMITATION.fullmatch(raw_text):
                refusal = _localize_standard_refusals(intent_question, raw_text, response_language)
            elif items:
                refusal = _retrieved_evidence_insufficient_response(intent_question, response_language)
            else:
                refusal = no_evidence_response(intent_question, response_language)
            grounded_refusal = sanitize_answer(intent_question, refusal, [])
            return FinalAnswer(
                grounded_refusal,
                raw_grounding,
                empty_plan,
                empty_ledger,
                (),
                tuple(line for line in str(raw_answer or "").splitlines() if line.strip()),
                refusal,
                False,
            )
    ledger = FactLedger.from_evidence(trusted)
    plan = infer_required_fact_plan(question, trusted, ledger)
    draft_to_ground = deterministic_projection_draft or raw_grounding.answer
    period_scoped_draft, period_removed = _remove_period_contaminated_growth_claims(
        draft_to_ground, plan, ledger,
    )
    grounded_draft, absence_removed = _remove_superseded_absence_claims(
        period_scoped_draft, question, plan, ledger
    )
    grounded_draft, basis_removed = remove_mislabeled_eps_claims(
        grounded_draft, plan, ledger
    )
    dimension_removed: tuple[str, ...] = ()
    # 分组表格的数字不能满足未指定维度的公司级指标。即便引用本身真实，
    # 也必须在确定性补全前剔除把产品/地区/渠道数值写成公司总数的回答。
    if plan.required and (
        any(spec.category for spec in plan.required)
        or any(fact.dimension or fact.category for fact in ledger.facts)
    ):
        grounded_draft, dimension_removed = safe_answer_from_fact_ledger(
            grounded_draft, plan, ledger,
        )
    completed, added, _ = complete_from_fact_ledger(
        grounded_draft, plan, ledger, question=question, evidence=trusted,
        response_language=response_language,
    )
    verified_facts_only_projection = False
    projection_removed: tuple[str, ...] = ()
    projection_mode = (
        _can_project_verified_facts_only(question, plan, ledger)
        or _can_project_partial_financial_comparison(question, plan, ledger)
    )
    if projection_mode:
        projected, projected_ids, _ = complete_from_fact_ledger(
            "", plan, ledger, question=question, evidence=trusted,
            response_language=response_language,
        )
        available_required_count = sum(
            1 for status in plan.statuses(ledger, "") if status.available
        )
        complete_projection = len(projected_ids) == available_required_count
        partial_comparison_projection = (
            _can_project_partial_financial_comparison(question, plan, ledger)
            and bool(projected_ids)
        )
        if projected_ids and (complete_projection or partial_comparison_projection):
            verified_facts_only_projection = True
            projection_removed = tuple(
                line for line in str(raw_answer or "").splitlines() if line.strip()
            )
            completed = projected.strip()
            missing = [
                status.spec
                for status in plan.statuses(ledger, "")
                if not status.available
            ]
            if missing and _is_contextual_followup_compare(question, plan):
                chinese = any(
                    "\u3400" <= char <= "\u9fff"
                    for char in current_turn_query(question)
                )
                missing_labels = {
                    "operating_margin": "营业利润率" if chinese else "operating margin",
                    "gross_margin": "毛利率" if chinese else "gross margin",
                    "revenue": "营收" if chinese else "revenue",
                    "net_income": "净利润" if chinese else "net income",
                    "operating_cash_flow": "经营活动现金流"
                    if chinese else "operating cash flow",
                    "eps": "每股收益" if chinese else "EPS",
                }
                missing_lines = []
                company_labels = {
                    "apple": "苹果" if chinese else "Apple",
                    "tesla": "特斯拉" if chinese else "Tesla",
                    "nvidia": "英伟达" if chinese else "NVIDIA",
                    "microsoft": "微软" if chinese else "Microsoft",
                }
                for spec in missing:
                    company = company_labels.get(
                        str(spec.company or "").casefold(),
                        spec.company or ("所请求公司" if chinese else "the requested company"),
                    )
                    period = (spec.period or "the requested period").replace("_", " ")
                    label = missing_labels.get(spec.metric_id, spec.metric_id)
                    if chinese:
                        missing_lines.append(
                            f"{company} {period} {label}：现有财报摘录未提供。"
                        )
                    else:
                        missing_lines.append(
                            f"{company} {period} {label}: not available in the cited filing."
                        )
                completed = f"{completed}\n\n" + "\n".join(
                    f"- {line}" for line in missing_lines
                )
            added = projected_ids
    # If the ledger contains a trusted requested fact, refusal-only lines are
    # stale provider placeholders rather than useful uncertainty.  Remove
    # them before the final grounding pass so the user sees one coherent
    # answer while genuine evidence limitations remain explicit.
    completed = _compact_refusal_fragments(
        completed,
        # An unrelated fact in the same retrieval context must not erase an
        # insufficiency refusal (e.g. Tesla revenue cannot answer a price-target
        # or gross-hires question). Count only facts required by this question.
        # ``answer_present`` is intentionally not required here: a provider
        # may emit a refusal before the ledger safely projects the requested
        # fact.  If the requested identity is available in trusted evidence,
        # keeping the stale refusal would make a correct answer appear
        # contradictory.  Unstructured metrics such as market share have no
        # available ledger status and therefore keep their refusal.
        has_supported_facts=bool(added or any(
            status.available for status in plan.statuses(ledger, "")
        )),
    )
    completed = _localize_standard_refusals(question, completed, response_language)
    grounded = sanitize_answer(
        question, completed, trusted, require_qualitative_citations=True,
    )
    grounded = GroundingResult(
        _localize_standard_refusals(question, grounded.answer, response_language),
        grounded.evidence,
        grounded.claims,
        grounded.judgments,
    )
    # Citation ranks are compacted relative to the trusted evidence set. When
    # duplicate or filtered evidence changes that rank space, one normalization
    # pass may expose a stale marker from the prior rank map. Iterate to a
    # stable answer so downstream serializers and audits see the same claims
    # and citations on every validation pass.
    for _ in range(min(3, len(grounded.evidence) + 1)):
        normalized = sanitize_answer(
            question,
            grounded.answer,
            grounded.evidence,
            require_qualitative_citations=True,
        )
        normalized = GroundingResult(
            _localize_standard_refusals(question, normalized.answer, response_language),
            normalized.evidence,
            normalized.claims,
            normalized.judgments,
        )
        if normalized.answer == grounded.answer:
            grounded = normalized
            break
        grounded = normalized
    # A comparison model can mention every issuer in its raw draft, yet the
    # claim-level gate may remove those paraphrases because their citations do
    # not entail the wording.  Recompute coverage after that gate and append
    # bounded, verbatim issuer excerpts for any missing company.  This keeps
    # the comparison evidence-complete without trusting the removed prose.
    if is_growth_narrative_question(intent_question) and grounded.evidence:
        final_driver_passages = _safe_driver_passages(
            intent_question,
            extract_growth_driver_passages(intent_question, grounded.evidence),
            grounded.evidence,
        )
        required_final_companies = {
            canonical_company(passage.company)
            for passage in final_driver_passages
            if passage.company
        }
        covered_final_companies = _narrative_driver_coverage(
            grounded.answer, final_driver_passages,
        )
        if required_final_companies and covered_final_companies != required_final_companies:
            coverage_excerpt = _render_driver_source_excerpt(
                intent_question, final_driver_passages,
            )
            checked_excerpt = sanitize_answer(
                question,
                coverage_excerpt,
                grounded.evidence,
                require_qualitative_citations=True,
            )
            if not any(
                claim.disposition == "UNSUPPORTED"
                for claim in checked_excerpt.claims
            ):
                combined = "\n\n".join(
                    part for part in (grounded.answer, coverage_excerpt) if part.strip()
                )
                grounded = sanitize_answer(
                    question,
                    combined,
                    grounded.evidence,
                    require_qualitative_citations=True,
                )
                synthesized_driver_excerpt = coverage_excerpt
    # If a provider returns only a refusal or source excerpts for a growth
    # ranking, use the same issuer-partitioned ledger to add a deterministic
    # conclusion when every named company has a supported/derived revenue YoY
    # rate.  This is deliberately period-labelled and refuses ties or missing
    # operands; it is not a benchmark-specific company rule.
    if is_growth_narrative_question(intent_question) and grounded.evidence:
        deterministic_ranking = _render_deterministic_growth_ranking(
            intent_question,
            plan,
            ledger,
            # Use the full trusted context for ranking coverage.  A prior
            # sanitizer pass may compact ``grounded.evidence`` to only the
            # already-visible issuer, which would make a complete comparison
            # look incomplete even though the trusted context contains all
            # named issuers.
            trusted,
        )
        if deterministic_ranking:
            has_stale_absence = bool(
                _GROWTH_EVIDENCE_ABSENCE.search(grounded.answer or "")
            )
            has_deterministic_output = bool(
                re.search(
                    r"(?i)\b(?:reported|verifiable)\s+revenue\s+(?:yoy|year[- ]over[- ]year)\b|"
                    r"按各公司财报可验证的营收同比增速",
                    grounded.answer or "",
                )
            )
            if not has_deterministic_output or has_stale_absence:
                base_answer = (
                    _remove_covered_growth_absence_claims(grounded.answer)
                    if has_stale_absence
                    else grounded.answer
                )
                candidate_parts = (
                    base_answer,
                    deterministic_ranking,
                )
            else:
                candidate_parts = (grounded.answer,)
            ranked_candidate = sanitize_answer(
                question,
                "\n\n".join(part for part in candidate_parts if part.strip()),
                trusted,
                require_qualitative_citations=True,
            )
            if ranked_candidate.answer and ranked_candidate.unsupported_count == 0:
                grounded = ranked_candidate
                completed = ranked_candidate.answer
            else:
                # A long historical/provider draft may contain unrelated
                # unsupported tables that prevent re-sanitizing the combined
                # answer, even though the already-sanitized answer and the
                # deterministic ranking are each safe independently.  Append
                # only the independently validated ranking in that case; do
                # not let bulky stale prose suppress a proven core conclusion.
                safe_ranking = sanitize_answer(
                    question,
                    deterministic_ranking,
                    trusted,
                    require_qualitative_citations=True,
                )
                if safe_ranking.answer and safe_ranking.unsupported_count == 0:
                    grounded = GroundingResult(
                        "\n\n".join(
                            part
                            for part in (
                                _remove_covered_growth_absence_claims(grounded.answer)
                                if has_stale_absence
                                else grounded.answer,
                                safe_ranking.answer,
                            )
                            if part.strip()
                        ),
                        trusted,
                        grounded.claims + safe_ranking.claims,
                        grounded.judgments + safe_ranking.judgments,
                    )
                    completed = grounded.answer
    # If the only model text that survived grounding is a generic retrieval
    # limitation, prefer the explicit narrative limitation plus the trusted
    # source excerpts.  This keeps the response auditable instead of hiding
    # valid evidence behind a boilerplate refusal.
    if (
        is_growth_narrative_question(intent_question)
        and synthesized_driver_excerpt
        and _RETRIEVAL_LIMITATION.search(grounded.answer or "")
    ):
        localized = _localized_grounded_fallback(
            intent_question, plan, ledger, trusted,
        )
        localized = "\n\n".join(
            part for part in (localized, synthesized_driver_excerpt) if part
        )
        grounded = sanitize_answer(
            question, localized, trusted, require_qualitative_citations=True,
        )
    grounded_refusal = bool(
        _RETRIEVAL_LIMITATION.search(grounded.answer or "")
        or re.search(
            r"(?i)cited filing evidence is insufficient|所引财报证据不足|"
            r"证据不足，无法可靠支持|当前证据不足以用中文可靠回答",
            grounded.answer or "",
        )
    )
    if (
        risk_only_query
        and trusted
        and grounded_refusal
        and len(str(raw_answer or "").strip()) >= 400
    ):
        # A risk comparison often contains valid paraphrases that are too far
        # from the chunk wording for the qualitative citation matcher.  Do not
        # return a refusal plus a dangling fragment in that case.  Replace the
        # provider prose with bounded, verbatim, issuer-labelled excerpts and
        # run the same citation gate again.
        risk_excerpt = _render_risk_context_excerpt(intent_question, trusted)
        if risk_excerpt.strip():
            checked_excerpt = sanitize_answer(
                question,
                risk_excerpt,
                trusted,
                require_qualitative_citations=True,
            )
            if not any(
                claim.disposition == "UNSUPPORTED"
                for claim in checked_excerpt.claims
            ):
                synthesized_risk_excerpt = risk_excerpt
                grounded = checked_excerpt
                completed = risk_excerpt
    # Segment questions need evidence coverage even when no numeric fact plan
    # can be inferred (for example a cross-company "major business segments"
    # comparison). If provider prose is discarded or only an unrelated
    # consolidated metric survives, render bounded filing-native segment rows
    # instead of returning a refusal or a margin-only answer.
    segment_query = bool(_SEGMENT_QUERY_CUE.search(intent_question))
    segment_visible = bool(
        _SEGMENT_SOURCE_CUE.search(grounded.answer or "")
        and re.search(r"\[Evidence\s+\d+\]", grounded.answer or "", re.IGNORECASE)
    )
    if segment_query and trusted and not segment_visible:
        segment_excerpt = _render_segment_source_excerpt(intent_question, trusted)
        if segment_excerpt.strip():
            checked_segment = sanitize_answer(
                question,
                segment_excerpt,
                trusted,
                require_qualitative_citations=True,
            )
            if not any(
                claim.disposition == "UNSUPPORTED"
                for claim in checked_segment.claims
            ):
                synthesized_segment_excerpt = segment_excerpt
                grounded = checked_segment
                completed = segment_excerpt
    language_removed: tuple[str, ...] = ()
    # The model prompt requests the question's language, but historic and
    # provider-generated answers can still violate that contract.  Do not
    # expose an untranslated answer: project the scoped evidence ledger into
    # the requested language using deterministic labels, or fail closed when
    # no structured requested fact exists.  This deliberately avoids a second
    # model/provider call and does not translate unsupported prose.
    language_check_answer = grounded.answer
    if synthesized_risk_excerpt or synthesized_segment_excerpt:
        # The risk fallback is intentionally a verbatim evidence excerpt; its
        # source language is not model prose and must not trigger a language
        # mismatch refusal for a Chinese question. Segment fallbacks use the
        # same source-excerpt contract.
        language_check_answer = ""
    for source_excerpt in (
        synthesized_driver_excerpt,
        synthesized_risk_excerpt,
        synthesized_segment_excerpt,
    ):
        if source_excerpt:
            # A cited, verbatim filing quotation may remain in English inside
            # an otherwise Chinese response. Do not misclassify that deliberate
            # source excerpt as untranslated model prose; doing so would replace
            # a valid narrative answer with a generic refusal when no numeric
            # fact is present in the ledger.
            language_check_answer = language_check_answer.replace(
                source_excerpt, "",
            ).strip()
    if _answer_language_mismatch(intent_question, language_check_answer, response_language):
        language_removed = (grounded.answer,)
        # A local model can answer a narrative comparison in the wrong
        # language while still attaching valid evidence markers.  In that
        # case the normal ledger fallback has no structured facts to render
        # and would collapse the whole answer to a refusal.  Rebuild a
        # deterministic, cited source excerpt from the trusted evidence so
        # language safety does not become evidence loss.
        if (
            (is_growth_narrative_question(intent_question) or is_segment_comparison_question(intent_question))
            and not synthesized_driver_excerpt
        ):
            driver_passages = extract_growth_driver_passages(
                intent_question, trusted,
            )
            driver_passages = _safe_driver_passages(
                intent_question, driver_passages, trusted,
            )
            synthesized_driver_excerpt = _render_driver_source_excerpt(
                intent_question, driver_passages,
            )
        localized = _localized_grounded_fallback(
            intent_question, plan, ledger, trusted, response_language,
        )
        # A source excerpt is not untranslated model prose: it is a verbatim,
        # cited passage deliberately added because the question asks for
        # qualitative drivers that are present in English-language filings.
        # Keep that evidence beside the localized ledger facts rather than
        # dropping it during the language-safety fallback.
        for source_excerpt in (
            synthesized_driver_excerpt,
            synthesized_risk_excerpt,
            synthesized_segment_excerpt,
        ):
            if source_excerpt:
                localized = "\n\n".join(
                    part for part in (localized, source_excerpt) if part
                )
        safe_localized_refusal = localized.strip() in {
            "当前证据不足以用中文可靠回答该问题。",
            "The available evidence is insufficient to answer this question reliably.",
        }
        if safe_localized_refusal:
            # This is a deterministic fail-closed response, not a provider
            # claim.  Do not let the citation matcher count the refusal itself
            # as an unsupported claim merely because unrelated evidence was
            # retrieved for the wrong company/source scope.
            grounded = GroundingResult(
                _localize_standard_refusals(question, localized, response_language),
                [],
                [],
                [],
            )
        else:
            grounded = sanitize_answer(
                question, localized, trusted, require_qualitative_citations=True,
            )
        completed = localized
    # Price targets, market share, and hires are not fungible with their nearby
    # financial facts. Until a source contains an explicit metric phrase,
    # fail closed even if the provider emitted qualitative prose without a
    # number (or unrelated evidence happened to contain the same number).
    if (
        not _unstructured_metric_answer_is_grounded(
            intent_question,
            grounded.answer,
            grounded.evidence,
        )
        and not (
            is_growth_narrative_question(intent_question)
            and synthesized_driver_excerpt
        )
        and not (segment_query and synthesized_segment_excerpt)
    ):
        unavailable = _insufficient_metric_answer(intent_question)
        grounded = sanitize_answer(question, unavailable, trusted)
        completed = unavailable
        language_removed += (str(raw_answer),) if str(raw_answer).strip() else ()
    # A final citation pass can reintroduce the standard refusal when it
    # rejects one provider sentence, even though other requested identities
    # are available in the trusted ledger.  Remove that generated placeholder
    # once more at the response boundary; the rejected sentence remains in the
    # raw grounding audit and any genuinely unsupported claim is still absent.
    final_refusal_removed: tuple[str, ...] = ()
    # A prose comparison/analysis may intentionally have no required-fact
    # plan, yet still contain validated numeric claims or deterministic
    # projections. In that case a provider's leading generic retrieval
    # refusal is contradictory and must be removed just as it is for a
    # ledger-backed fact plan. Do not use mere evidence presence here: an
    # exact quoted excerpt alone should keep its explicit limitation.
    has_supported_visible_claims = bool(
        grounded.supported_count
        or grounded.derivable_count
        # Qualitative driver excerpts are NON_NUMERIC claims, so they do not
        # increment the numeric support counters above.  An explicitly
        # attributed driver is nevertheless sufficient to remove a stale
        # generic retrieval-refusal line; background-only commentary remains
        # fail-closed through the separate ``driver_background_only`` path.
        or bool(explicit_driver_passages)
    )
    if any(status.available for status in plan.statuses(ledger, "")) or has_supported_visible_claims:
        compacted_grounded = _compact_refusal_fragments(
            grounded.answer,
            has_supported_facts=True,
        )
        if compacted_grounded != grounded.answer:
            final_refusal_removed = tuple(
                line for line in grounded.answer.splitlines()
                if line.strip() and line not in compacted_grounded.splitlines()
            )
            grounded = GroundingResult(
                compacted_grounded,
                grounded.evidence,
                grounded.claims,
                grounded.judgments,
            )
    # Keep structural cleanup auditable.  These fragments are deliberately
    # removed from the user-visible answer, but they must still be reported as
    # removed provider lines rather than silently disappearing from the
    # grounding audit.
    pre_structural_cleanup = grounded.answer
    cleaned_answer = _clean_structural_artifacts(pre_structural_cleanup)
    structural_removed = tuple(
        line
        for line in pre_structural_cleanup.splitlines()
        if line.strip() and line not in cleaned_answer.splitlines()
    )
    if cleaned_answer != grounded.answer:
        grounded = sanitize_answer(
            question,
            cleaned_answer,
            grounded.evidence,
            require_qualitative_citations=True,
        )
        grounded = GroundingResult(
            _localize_standard_refusals(
                question,
                _clean_structural_artifacts(grounded.answer),
                response_language,
            ),
            grounded.evidence,
            grounded.claims,
            grounded.judgments,
        )
    completed = _clean_structural_artifacts(completed)
    # Keep a fully covered comparative ranking when an earlier conservative
    # pass replaced the provider narrative with a generic limitation.  The
    # ranking is restored only through the same issuer-complete growth
    # inference check used by ``sanitize_answer``; unsupported or partially
    # covered comparisons still fail closed as before.
    if (
        is_growth_narrative_question(intent_question)
        and not re.search(
            r"(?i)\b(?:reported|verifiable)\s+revenue\s+(?:yoy|year[- ]over[- ]year)\b|"
            r"按各公司财报可验证的营收同比增速",
            grounded.answer or "",
        )
    ):
        for candidate in completed.splitlines():
            if not _GROWTH_RANKING_CUE.search(candidate):
                continue
            ranked = sanitize_answer(
                question,
                candidate,
                trusted,
                require_qualitative_citations=True,
            )
            if not ranked.answer or ranked.unsupported_count:
                continue
            parts = [ranked.answer]
            if synthesized_driver_excerpt:
                parts.append(synthesized_driver_excerpt)
            restored = sanitize_answer(
                question,
                "\n\n".join(parts),
                trusted,
                require_qualitative_citations=True,
            )
            if restored.answer and restored.unsupported_count == 0:
                grounded = restored
                break
    # A late narrative/source-excerpt pass can compact citation ranks and
    # conservatively drop one otherwise-supported structured fact (notably a
    # filing-native iPhone row whose label is bilingual). Re-run the same
    # deterministic ledger completion once at the response boundary so a
    # fact that is still available in the trusted evidence cannot disappear
    # merely because of the ordering of the prose cleanup passes.
    final_missing = tuple(
        status for status in plan.statuses(ledger, grounded.answer)
        if status.available and not status.answer_present
    )
    if final_missing:
        repaired_answer, repaired_ids, _ = complete_from_fact_ledger(
            grounded.answer,
            plan,
            ledger,
            question=question,
            evidence=trusted,
            response_language=response_language,
        )
        if repaired_ids:
            repaired_grounding = sanitize_answer(
                question,
                repaired_answer,
                trusted,
                require_qualitative_citations=True,
            )
            if repaired_grounding.unsupported_count == 0:
                grounded = repaired_grounding
                completed = repaired_answer
                added = tuple(dict.fromkeys((*added, *repaired_ids)))
    # Late fact completion above can replace a correctly localized draft with
    # the question-script version (for example Chinese labels on an English
    # UI). Enforce the selected interface language at the final response
    # boundary and rebuild only from the already-validated fact ledger.
    final_language_check = grounded.answer
    for source_excerpt in (
        synthesized_driver_excerpt,
        synthesized_risk_excerpt,
        synthesized_segment_excerpt,
    ):
        if source_excerpt:
            final_language_check = final_language_check.replace(source_excerpt, "").strip()
    if (
        response_language in {"en", "zh-CN"}
        and _answer_language_mismatch(
            intent_question, final_language_check, response_language,
        )
    ):
        localized, localized_ids, _ = complete_from_fact_ledger(
            "", plan, ledger, question=question, evidence=trusted,
            response_language=response_language,
        )
        if localized_ids:
            localized_grounding = sanitize_answer(
                question,
                localized,
                trusted,
                require_qualitative_citations=True,
            )
            if localized_grounding.unsupported_count == 0:
                language_removed += (grounded.answer,)
                grounded = localized_grounding
                completed = localized
                added = tuple(dict.fromkeys((*added, *localized_ids)))
            else:
                localized_ids = ()
        if not localized_ids:
            refusal = (
                "当前证据不足以用中文可靠回答该问题。"
                if response_language == "zh-CN"
                else "The available evidence is insufficient to answer this question reliably."
            )
            grounded = GroundingResult(refusal, [], [], [])
            completed = refusal
    # Fact completion can run after the ranking pass and replace the visible
    # prose with a compact ledger projection.  Re-attach the validated ranking
    # at the final boundary so late completion cannot silently remove the core
    # comparison conclusion or its mixed-period disclosure.
    if is_growth_narrative_question(intent_question) and trusted:
        final_deterministic_ranking = _render_deterministic_growth_ranking(
            intent_question,
            plan,
            ledger,
            trusted,
        )
        if (
            final_deterministic_ranking
            and not re.search(
                r"(?i)\b(?:reported|verifiable)\s+revenue\s+(?:yoy|year[- ]over[- ]year)\b|"
                r"按各公司财报可验证的营收同比增速",
                grounded.answer or "",
            )
        ):
            safe_ranking = sanitize_answer(
                question,
                final_deterministic_ranking,
                trusted,
                require_qualitative_citations=True,
            )
            if safe_ranking.answer and safe_ranking.unsupported_count == 0:
                grounded = GroundingResult(
                    "\n\n".join(
                        part for part in (grounded.answer, safe_ranking.answer) if part.strip()
                    ),
                    trusted,
                    grounded.claims + safe_ranking.claims,
                    grounded.judgments + safe_ranking.judgments,
                )
                completed = grounded.answer
    # Last user-visible consistency boundary. Late language, ledger, and
    # narrative projections can append content after the earlier refusal
    # cleanup; never return a generic refusal beside a supported answer.
    if grounded.supported_count or grounded.derivable_count:
        consistent_answer = _compact_refusal_fragments(
            grounded.answer,
            has_supported_facts=True,
        )
        if consistent_answer != grounded.answer:
            grounded = GroundingResult(
                consistent_answer,
                grounded.evidence,
                grounded.claims,
                grounded.judgments,
            )
    # Do not merge rejected raw-provider claims back into ``grounded.claims``.
    # ``grounded`` is the user-visible production response and its counters
    # are consumed by the final safety gate.  The rejected claims remain
    # available in ``raw_grounding`` and ``removed`` for audit/reporting; if
    # they were appended here, a safe ledger-only projection would be reported
    # as containing unsupported claims even though those claims were removed.
    # Recover a requested, verbatim named risk from an explicitly applicable
    # annual-report list after paraphrase filtering. Do not infer consequences,
    # amounts, or periods, and do not let a stale refusal contradict the quote.
    for rank, item in enumerate(trusted, 1):
        content = str(item.content or "")
        if response_language and not response_language.lower().startswith("zh"):
            continue
        from retrieval.periods import matches_filter

        periods = extract_periods(intent_question)
        source_metadata = dict(item.metadata, source=item.source)
        if periods and not all(matches_filter(content, source_metadata, "period", period)
                               for period in periods):
            continue
        if not ("√适用" in content and "□不适用" in content
                and "可能面对的风险" in content):
            continue
        for risk in re.findall(r"(?:一是|二是|三是|四是|五是)([^；;。\n]{2,30}风险)", content):
            if risk not in intent_question:
                continue
            excerpt = f"“可能面对的风险”部分的财报原文：{risk} [Evidence {rank}]。"
            checked = sanitize_answer(question, excerpt, trusted, require_qualitative_citations=True)
            if risk not in checked.answer or checked.unsupported_count:
                continue
            base = _compact_refusal_fragments(grounded.answer, has_supported_facts=True)
            if base != grounded.answer:
                grounded = checked
                completed = grounded.answer
                continue
            if risk in grounded.answer:
                continue
            grounded = sanitize_answer(
                question, "\n\n".join(part for part in (base, excerpt) if part.strip()),
                trusted, require_qualitative_citations=True,
            )
            completed = grounded.answer
    # Claim filtering can legitimately remove every sentence while preserving
    # Markdown headings. A title is not an answer: expose the localized safety
    # refusal instead of an apparently successful, empty research result.
    if not any(line.strip() and not line.lstrip().startswith("#")
               for line in grounded.answer.splitlines()):
        grounded = sanitize_answer(
            question, no_evidence_response(question, response_language), [],
        )
        completed = grounded.answer
    return FinalAnswer(
        grounded, raw_grounding, plan, ledger, added,
        removed + driver_removed + absence_removed + basis_removed + period_removed
        + dimension_removed + language_removed + projection_removed
        + final_refusal_removed + structural_removed
        + (tuple(line for line in str(raw_answer or "").splitlines() if line.strip())
           if provider_refusal_projection else ()),
        completed,
        verified_facts_only_projection,
    )
