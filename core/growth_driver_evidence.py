"""Provider-free detection and extractive recovery for cited growth drivers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from agent.planning.entity_extractor import (
    extract_allowed_source_companies,
    extract_companies,
)
from agent.reasoning_models import Evidence
from core.fact_ledger import canonical_company, periods_equivalent
from retrieval.periods import extract_periods

_GROWTH_DRIVER_QUESTION = re.compile(
    r"\bwhat\s+drove\b|"
    r"\bwhy\s+(?:does|did|has|have|is|was|were|are)\b.{0,100}\b"
    r"(?:grow\w*|increas\w*|ris\w*|expand\w*|accelerat\w*|"
    r"revenue|sales|business|performance|demand)\b|"
    r"\b(?:(?:main|major|key|primary)\s+)?"
    r"(?:(?:business|revenue|sales|product|service)\s+)?"
    r"(?:growth\s+)?drivers?\b|"
    r"\bwhat\s+drove\s+(?:the\s+)?(?:growth|revenue|business)\b|"
    r"\b(?:causes?|reasons?)\s+for\s+(?:the\s+)?growth\b|"
    r"(?:主要|核心|关键)(?:的)?增长(?:驱动(?:因素)?|动力|原因)|"
    r"增长(?:的)?[\s，,、]*(?:主要|核心|关键)?(?:驱动(?:因素)?|动力|原因)|"
    r"增长的主要原因|为何增长|为什么.{0,20}(?:增长|上升|提升|扩大|加速)|"
    r"(?:业务|营收|收入).{0,12}为什么(?:增长|上升|提升|扩大)|"
    r"(?:什么|哪些).{0,12}推动.{0,20}(?:增长|业务|营收|收入)|"
    r"\bbusiness\s+factors?\b.{0,40}\b(?:driv\w*|behind|affect\w*)\b|"
    r"\bfactors?\s+(?:driv\w*|behind)\s+(?:their\s+)?(?:reported\s+)?performance\b|"
    r"业务因素.{0,24}(?:驱动|影响|导致)|"
    r"(?:下降|减少|下滑|降低|收窄).{0,20}(?:主要)?(?:原因|归因|因素)|"
    r"(?:归因于|主要归因于|主要原因|原因在于)|"
    r"(?:reason|cause|attribution).{0,24}(?:declin|decreas|drop|fall)|"
    r"(?:declin|decreas|drop|fall).{0,24}(?:reason|cause|attribution)",
    re.IGNORECASE,
)
_FINANCIAL_CHANGE_CAUSE_QUESTION = re.compile(
    r"(?:declin|decreas|drop|fall|reduce).{0,28}(?:reason|cause|attribution)|"
    r"(?:reason|cause|attribution).{0,28}(?:declin|decreas|drop|fall|reduce)|"
    r"(?:下降|减少|下滑|降低|收窄).{0,20}(?:主要)?(?:原因|归因|因素)|"
    r"(?:归因于|主要归因于|主要原因|原因在于)",
    re.IGNORECASE,
)
_GROWTH_NARRATIVE_QUESTION = re.compile(
    r"\b(?:growth\s+(?:narrative|story|momentum|trajectory|profile)|"
    r"strongest\s+growth(?:\s+narrative)?|growth\s+momentum)\b|"
    r"增长(?:势头|叙事|故事|动能|轨迹|表现)|"
    r"增长(?:最|哪家|哪一家公司).{0,12}(?:强|快|好|显著)",
    re.IGNORECASE,
)
_FINANCIAL_SUMMARY_REQUEST = re.compile(
    r"\b(?:summari[sz]e|summary|overview)\b.{0,90}\b(?:financial\s+(?:performance|results?)|performance)\b|"
    r"\bfinancial\s+(?:performance|results?)\b|"
    r"\bhow\s+(?:did|does|is|was)\b.{0,80}\b(?:services?(?:-related)?|business\s+segment|segment)\b"
    r".{0,50}\b(?:perform\w*|do(?:ing)?|fare)\b|"
    r"\b(?:report|filing)\b.{0,90}\b(?:revenue|sales)\s+performance\b|"
    r"总结.{0,30}(?:财务表现|财务业绩|经营表现|经营业绩)|"
    r"(?:服务业务|业务分部|服务分部).{0,24}(?:表现|业绩|发展).{0,8}(?:如何|怎么样)|"
    r"(?:财报|报告).{0,30}(?:营收|收入|销售额).{0,12}(?:表现|业绩|情况)",
    re.IGNORECASE,
)
_SEGMENT_COMPARISON_REQUEST = re.compile(
    r"\b(?:compare|comparison)\b.{0,120}\b(?:major\s+)?(?:business\s+)?segments?\b|"
    r"\b(?:summari[sz]e|overview)\b.{0,120}\b(?:major\s+)?(?:business\s+)?segments?\b|"
    r"比较.{0,40}(?:主要)?业务(?:板块|分部)|"
    r"(?:总结|概览).{0,40}(?:主要)?业务(?:板块|分部)",
    re.IGNORECASE,
)
_FORWARD_LOOKING = re.compile(
    r"certain statements in this (?:press release|report|update)|"
    r"forward[- ]looking statements within the meaning|"
    r"subject to risks and uncertainties",
    re.IGNORECASE,
)
_DRIVER_CUE = re.compile(
    r"\b(?:driven\s+by|due\s+to|attribut\w*\s+to|because\s+of|"
    r"result\w*\s+from|fueled\s+by|led\s+by|primarily\s+from|"
    r"growth\s+drivers?|drivers?\s+(?:include|were|are)|positive\s+offset|"
    r"accelerat\w*|scal(?:ing|ed)\s+rapidly|generat\w+\s+real\s+value)\b|"
    r"由于|主要源于|主要因为|归因于|推动|带动|增长动力|增长驱动(?:因素)?|"
    r"快速扩张|迅速增长|主要是.{0,120}(?:减少|增加|下降|上升)|主要与.{0,120}有关",
    re.IGNORECASE,
)
_DRIVER_SUBJECT = re.compile(
    r"\b(?:revenue|revenues|net sales|sales|growth|demand|volume|"
    r"business|segment|cash flow|product mix|AI factories|agentic AI|advertising|"
    r"App Store|cloud services)\b|营收|收入|增长|需求|销量|业务|分部|产品组合|"
    r"现金流|AI工厂|AI 工厂|智能体 AI|Agentic AI",
    re.IGNORECASE,
)
_DRIVER_CHANGE = re.compile(
    r"\b(?:increas\w*|grow\w*|rose|risen|accelerat\w*|expand\w*|"
    r"improv\w*|record|higher|declin\w*|decreas\w*|up\s+by|scal(?:ing|ed)|"
    r"generat\w+\s+real\s+value)\b|增长|上升|提升|扩大|加速|改善|增加|下降|"
    r"创造实际价值|快速规模化",
    re.IGNORECASE,
)
_AI_DRIVER_NARRATIVE = re.compile(
    r"(?:build[- ]?out\s+of\s+AI\s+factories|AI\s+factory\s+build[- ]?out)"
    r"[^.!?]{0,140}\b(?:accelerat\w*|expand\w*|grow\w*|demand)\b|"
    r"\bagentic\s+AI\s+has\s+arrived[^.!?]{0,160}\b"
    r"(?:generat\w+\s+real\s+value|accelerat\w*|scal\w+\s+rapidly)\b",
    re.IGNORECASE,
)
_FINANCIAL_OUTCOME = re.compile(
    r"\b(?:revenue|revenues|net sales|sales|net income|operating income|"
    r"net profit|gross profit|earnings|gross margin|operating margin|cash flow|"
    r"deliveries|deployment|deployments|production|subscriptions|"
    r"average selling price|ASP|volume)\b|"
    r"营收|收入|销售额|净利润|营业利润|毛利率|营业利润率|现金流|交付量|销量|部署量|产量|订阅量",
    re.IGNORECASE,
)
_EXPLICIT_CAUSAL_LINK = re.compile(
    r"\b(?:due to|because of|driven by|attributable to|resulting from|"
    r"resulted from|primarily from|primarily due to|led by|fueled by|"
    r"as a result of|positive offset)\b|由于|因为|归因于|主要源于|主要由|导致|"
    r"主要是.{0,120}(?:减少|增加|下降|上升)|主要与.{0,120}有关",
    re.IGNORECASE,
)
_DRIVER_ABSENCE = re.compile(
    r"(?i)(?:(?:evidence|filing|report|document|source).{0,100}"
    r"(?:does not|doesn't|did not|didn't|do not|don't|not contain|not include|"
    r"not identify|not establish|lacks?).{0,100}"
    r"(?:driver|cause|reason|growth factor|business factor)|"
    r"(?:driver|cause|reason|growth factor|business factor).{0,100}"
    r"(?:not found|not identified|not disclosed|not available|missing)|"
    r"(?:证据|财报|报告|资料).{0,24}(?:没有|未能|无法|未找到|未说明|未披露).{0,24}"
    r"(?:驱动|增长原因|增长因素|业务因素)|"
    r"(?:没有|未能|无法|未找到|未说明|未披露).{0,24}"
    r"(?:驱动因素|增长原因|增长因素|业务因素))"
)
_TOKEN = re.compile(r"[a-z][a-z0-9'-]{2,}", re.IGNORECASE)
_STOPWORDS = {
    "about", "after", "among", "also", "and", "are", "because", "been",
    "being", "business", "could", "does", "from", "have", "into", "more",
    "report", "that", "their", "them", "there", "these", "they", "this",
    "those", "through", "were", "what", "when", "which", "while", "with",
    "would", "growth", "driver", "drivers", "increased", "increase",
}


@dataclass(frozen=True)
class GrowthDriverPassage:
    text: str
    evidence_rank: int
    explicit_financial_attribution: bool = False
    company: str = ""


def is_explicit_growth_driver_question(question: str) -> bool:
    """Return whether the user explicitly asks for financial causes/drivers.

    Retrieval uses this narrower intent to decide whether to filter out
    financial-statement evidence. It includes stated causes of financial
    declines as well as growth drivers. A broad financial summary may also
    benefit from extractive commentary, but must not be reduced to prose alone.
    """

    query = question or ""
    return bool(
        _GROWTH_DRIVER_QUESTION.search(query)
        or _FINANCIAL_CHANGE_CAUSE_QUESTION.search(query)
    )


def is_growth_narrative_question(question: str) -> bool:
    """Return whether a comparison asks for growth narrative/evidence.

    This is intentionally broader than the causal-driver classifier. A
    ranking such as "which company has the strongest growth narrative" still
    needs reported growth facts and management commentary for every issuer,
    but it must not be treated as a driver-only question that discards
    financial statement evidence.
    """

    return bool(_GROWTH_NARRATIVE_QUESTION.search(question or ""))


def is_growth_driver_question(question: str) -> bool:
    """Return whether driver evidence may help answer this request.

    Keep broad financial summaries eligible for cited driver excerpts at the
    answer-policy layer; use :func:`is_explicit_growth_driver_question` for
    retrieval filtering decisions.
    """

    query = question or ""
    return bool(
        is_explicit_growth_driver_question(query)
        or is_growth_narrative_question(query)
        or _FINANCIAL_SUMMARY_REQUEST.search(query)
        or _SEGMENT_COMPARISON_REQUEST.search(query)
    )


def is_segment_comparison_question(question: str) -> bool:
    """Return whether a broad segment comparison can use bounded driver context."""

    return bool(_SEGMENT_COMPARISON_REQUEST.search(question or ""))


def _driver_sentences(content: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?。！？;；])\s*|[\r\n]+", content or "")
    selected: list[str] = []
    for sentence in sentences:
        value = sentence.strip().strip("\"'“”‘’ ")
        if not value or _FORWARD_LOOKING.search(value):
            continue
        direct_ai_narrative = bool(_AI_DRIVER_NARRATIVE.search(value))
        causal_statement = bool(
            _DRIVER_CUE.search(value)
            and _DRIVER_SUBJECT.search(value)
            and _DRIVER_CHANGE.search(value)
            and _FINANCIAL_OUTCOME.search(value)
        )
        if direct_ai_narrative or causal_statement:
            selected.append(value)
        if len(selected) == 2:
            break
    return selected


def has_growth_driver_evidence(content: str) -> bool:
    return bool(_driver_sentences(content))


def _is_explicit_financial_attribution(text: str) -> bool:
    """Require a financial outcome and an explicit causal link in one passage.

    General management commentary about industry trends is useful context, but
    it must not be represented as the reported cause of a company's quarterly
    financial growth unless the filing explicitly connects the two.
    """
    return bool(
        _FINANCIAL_OUTCOME.search(text or "")
        and _EXPLICIT_CAUSAL_LINK.search(text or "")
    )


def has_explicit_financial_growth_driver_evidence(content: str) -> bool:
    """Return whether a passage explicitly attributes a financial outcome.

    General macroeconomic/risk commentary can contain words such as
    ``growth`` and ``impact`` without explaining a reported issuer result.
    Narrative comparisons should prefer this stricter signal, while retaining
    the separate AI-strategy narrative path for non-numeric management
    commentary.
    """

    return any(_is_explicit_financial_attribution(sentence) for sentence in _driver_sentences(content))


def extract_growth_driver_passages(
    question: str,
    evidence: Iterable[Evidence],
) -> tuple[GrowthDriverPassage, ...]:
    """Extract cited, issuer/period-compatible driver sentences from context.

    Only explicit source text with causal or management-driver signals is
    eligible. If the question names an issuer/period, evidence with conflicting
    or missing issuer/period metadata is rejected rather than guessed.
    """
    if not is_growth_driver_question(question):
        return ()

    requested_companies = {
        canonical_company(company) for company in extract_companies(question)
    }
    # A source-only instruction can mention one issuer as the permitted filing
    # set while asking about a different issuer (for example, "use only
    # Apple's filing to answer NVIDIA").  The allowed source is not the
    # answer target; otherwise its valid driver prose could incorrectly clear
    # a refusal for the off-scope issuer.  When the same issuer is both source
    # and target, retain it as the target normally.
    allowed_sources = {
        canonical_company(company)
        for company in extract_allowed_source_companies(question)
    }
    target_companies = requested_companies - allowed_sources
    if target_companies:
        requested_companies = target_companies
    requested_periods = extract_periods(question)
    result: list[GrowthDriverPassage] = []
    # A narrative comparison needs at least one cited driver/context passage
    # per named issuer.  Explicit multi-company driver questions have the same
    # coverage requirement even when they do not use the word "narrative";
    # otherwise the first two ranked chunks (often Apple + NVIDIA) crowd out
    # Tesla entirely.  A single-company explicit driver question also needs a
    # larger bounded pool so a first chunk's iPhone/Mac rows do not crowd out
    # a later Services driver paragraph.
    explicit_driver = is_explicit_growth_driver_question(question)
    narrative = (
        is_growth_narrative_question(question)
        or is_segment_comparison_question(question)
        or (explicit_driver and len(requested_companies) > 1)
    )
    max_passages = 8 if narrative else (6 if explicit_driver else 2)
    covered_companies: set[str] = set()
    seen: set[tuple[int, str]] = set()
    for rank, item in enumerate(evidence, 1):
        source_company = canonical_company(
            str(item.company or item.metadata.get("company", ""))
        )
        if requested_companies and source_company not in requested_companies:
            continue
        content = str(item.content or "")
        metadata_periods = extract_periods(
            str(item.metadata.get("quarter") or item.metadata.get("period") or "")
        )
        source_periods = metadata_periods or extract_periods(content)
        if requested_periods and (
            not source_periods
            or not any(
                periods_equivalent(requested, source)
                for requested in requested_periods
                for source in source_periods
            )
        ):
            continue
        for sentence in _driver_sentences(content):
            explicit = _is_explicit_financial_attribution(sentence)
            # Narrative comparisons must not promote an arbitrary risk/table
            # sentence to a growth story merely because it contains the word
            # "growth". Keep explicit financial attribution and the dedicated
            # AI-strategy narrative; otherwise fail closed for that issuer.
            if narrative and not explicit and not _AI_DRIVER_NARRATIVE.search(sentence):
                continue
            key = rank, sentence.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(
                GrowthDriverPassage(
                    sentence[:360],
                    rank,
                    explicit,
                    source_company,
                )
            )
            if source_company:
                covered_companies.add(source_company)
            if not narrative and len(result) >= max_passages:
                return tuple(result)
            # Do not stop immediately after seeing every issuer.  The first
            # passage for an issuer can be a PDF-split table fragment that the
            # citation sanitizer correctly rejects; continuing through a
            # small bounded pool lets a later complete passage represent the
            # same issuer without weakening the safety gate.
            if narrative and len(result) >= max_passages:
                return tuple(result)
    return tuple(result)


def answer_has_cited_growth_driver(
    answer: str,
    passages: Iterable[GrowthDriverPassage],
) -> bool:
    """Check whether a draft already uses one of the cited driver passages."""
    passage_list = tuple(passages)
    ranks = {
        int(value)
        for value in re.findall(r"\[Evidence\s+(\d+)\]", answer or "", re.IGNORECASE)
    }
    if not ranks:
        return False
    if not _DRIVER_CUE.search(answer or ""):
        return False
    answer_tokens = {
        token.casefold() for token in _TOKEN.findall(answer or "")
        if token.casefold() not in _STOPWORDS
    }
    for passage in passage_list:
        if not passage.explicit_financial_attribution:
            continue
        if passage.evidence_rank not in ranks:
            continue
        source_tokens = {
            token.casefold() for token in _TOKEN.findall(passage.text)
            if token.casefold() not in _STOPWORDS
        }
        if len(answer_tokens & source_tokens) >= 1:
            return True
    return False


def is_driver_absence_claim(text: str) -> bool:
    return bool(_DRIVER_ABSENCE.search(text or ""))
