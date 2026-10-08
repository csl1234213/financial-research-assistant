# retrieval/hybrid_retriever.py

"""
V4 Hybrid Retriever (Retrieval Orchestrator)

Step 3: Full Refactor

Before (V3):
    retrieve(chunks, embeddings, question, company, document_ids, top_k)
    Retriever = algorithm

After (V4):
    retrieve(context, store)
    Retriever = orchestration layer
    Store = data layer
    Context = planning layer
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from threading import Lock
from typing import Dict, List

from agent.planning.entity_extractor import extract_companies
from agent.reasoning_models import Evidence
from core.fact_ledger import canonical_company
from core.financial_facts import rows_from_json
from core.financial_grounding import canonical_metrics, extract_normalized_numbers
from core.financial_metric_registry import MetricMappingStatus, normalize_financial_table_row
from core.financial_table_rows import VerificationStatus
from core.growth_driver_evidence import (
    has_explicit_financial_growth_driver_evidence,
    is_explicit_growth_driver_question,
    is_growth_narrative_question,
)
from core.query_scope import QueryScope, classify_query_scope
from embedding import embed_query
from retrieval.bm25_retriever import BM25Retriever
from retrieval.document_filter import DocumentFilter
from retrieval.metadata_filter import MetadataFilter
from retrieval.periods import (
    extract_annual_periods,
    extract_metrics,
    extract_periods,
    has_explicit_period_conflict,
    matches_filter,
    query_filters,
)
from retrieval.query_enrichment import enrich_financial_query
from retrieval.retrieval_context import RetrievalContext
from storage.embedding_store import EmbeddingStore
from storage.vector_models import SearchResult

logger = logging.getLogger(__name__)

_SEGMENT_QUESTION = re.compile(
    r"\b(?:business|operating|reportable)\s+segments?\b|"
    r"\bsegments?\s+(?:breakdown|revenue|performance)\b|"
    r"\brevenue\s+by\s+segment\b|\bby\s+business\s+unit\b|"
    r"业务板块|业务分部|各分部|分部(?:收入|营收|表现)",
    re.IGNORECASE,
)
_NON_SEGMENT_SECTION = re.compile(
    r"^(?:page\s*\d+|summary|highlights?|outlook|about(?:\s+.*)?|"
    r"non[ -]?gaap(?:\s+.*)?|cfo commentary|conference call.*|"
    r"(?:condensed consolidated )?statements? of .+|"
    r"(?:three|six|nine|twelve) months ended.*|financial summary)$",
    re.IGNORECASE,
)
_SEGMENT_FINANCIAL_VALUE = re.compile(
    r"\b(?:revenue|revenues|net sales|sales|operating income|segment profit)\b|"
    r"营收|收入|销售额|营业利润|分部利润",
    re.IGNORECASE,
)
_SEGMENT_DISCLOSURE_LABEL = re.compile(
    r"(?:resolved\s+financial\s+label\s*:\s*)?"
    r"\b(products?|services?|iphone|ipad|mac|wearables(?:,\s*home\s+and\s+accessories)?)\s+"
    r"(?:net\s+sales|revenue)\b",
    re.IGNORECASE,
)
_SEGMENT_DISCLOSURE_TABLE = re.compile(
    r"\b(?:disaggregated\s+(?:net\s+sales|revenue)|reportable\s+segment(?:s|\s+information)?)\b",
    re.IGNORECASE,
)
_FORWARD_LOOKING_BOILERPLATE = re.compile(
    r"certain statements in this (?:press release|report|update)|"
    r"forward[- ]looking statements within the meaning|"
    r"subject to risks and uncertainties",
    re.IGNORECASE,
)
_GROWTH_DRIVER_EVIDENCE = re.compile(
    r"\b(?:driven\s+by|due\s+to|attribut\w+\s+to|because\s+of|"
    r"demand\s+for|build[- ]out|accelerat\w+|scal(?:ing|ed)\s+rapidly|"
    r"generat\w+\s+real\s+value|result(?:ing)?\s+from|fueled\s+by)\b|"
    r"由.{0,12}(?:推动|带动)|需求.{0,12}(?:增长|加速)|快速扩张",
    re.IGNORECASE,
)
_GROWTH_DRIVER_SUBJECT = re.compile(
    r"\b(?:revenue|revenues|net sales|sales|gross margin|operating income|"
    r"profit|income|growth|demand|volume|product mix|segment)\b|"
    r"营收|收入|净销售额|销售额|毛利率|营业利润|利润|增长|需求|销量|产品组合",
    re.IGNORECASE,
)
_GROWTH_DRIVER_CHANGE = re.compile(
    r"\b(?:increas\w*|grow\w*|rose|risen|accelerat\w*|expand\w*|"
    r"improv\w*|record|higher|lower|declin\w*|up\s+by|down\s+by)\b|"
    r"增长|上升|提高|提升|扩大|加速|改善|创纪录|增加|下降",
    re.IGNORECASE,
)
_GROWTH_DRIVER_CAUSE = re.compile(
    r"\b(?:driven\s+by|due\s+to|attribut\w*\s+to|because\s+of|"
    r"result(?:ing)?\s+from|fueled\s+by|led\s+by|primarily\s+from|"
    r"reflecting)\b|由于|主要源于|主要因为|归因于|推动|带动|得益于",
    re.IGNORECASE,
)
_AI_GROWTH_DRIVER_NARRATIVE = re.compile(
    r"(?:build[- ]out\s+of\s+AI\s+factories|AI\s+factory\s+build[- ]out)"
    r"[^.!?]{0,120}\b(?:accelerat\w*|expand\w*|grow\w*|demand)\b|"
    r"agentic\s+AI\s+has\s+arrived[^.!?]{0,120}"
    r"\b(?:generat\w+\s+real\s+value|accelerat\w*|scal\w+\s+rapidly)\b",
    re.IGNORECASE,
)
_SPECIFIC_RISK_EVIDENCE = re.compile(
    r"\b(?:risk factors? include|risks? include|important factors?[^.]{0,100}?could cause|"
    r"factors? that could adversely affect|could adversely affect|may adversely affect|"
    r"supply constraints?|export controls?|export restrictions?|tariffs?|"
    r"regulatory (?:requirements?|risks?|actions?|uncertaint\w*|changes|exposure|restrictions?)|"
    r"legal proceedings?|lawsuits?|litigation (?:risks?|claims?|exposure)|"
    r"claims? (?:against|alleging|relating to)|substantial competition|"
    r"reliance on third parties|dependence on|ability to attract and retain|"
    r"risk of\s+[a-z]|materially(?:\s+and)?\s+adversely affect\w*|"
    r"not assuming.{0,80}(?:revenue|sales).{0,80}(?:from|in)\s+[A-Z][A-Za-z]+)\b|"
    r"风险因素(?:包括|是)|风险包括|可能(?:会)?(?:导致|造成|对.{0,12}产生不利影响)|"
    r"供应(?:限制|受限)|出口(?:管制|限制)|关税|监管要求|诉讼|"
    r"依赖第三方|竞争压力|吸引并留住关键员工",
    re.IGNORECASE,
)
_RISK_QUESTION = re.compile(
    r"\b(?:risks?|risk factors?|constraints?|limitations?)\b|"
    r"风险(?:因素|点)?|限制因素|约束",
    re.IGNORECASE,
)
_AUDIT_REPORT_QUESTION = re.compile(
    r"\b(?:auditor|audit firm|audited by|audit opinion|opinion on (?:the )?financial statements)\b|"
    r"会计师事务所|审计机构|谁审计|审计意见|审计报告由",
    re.IGNORECASE,
)
_AUDITOR_IDENTITY_EVIDENCE = re.compile(
    r"\b(?:independent\s+auditor|audit\s+firm|auditor(?:s)?\s*:|audited\s+by)\b|"
    r"会计师事务所|审计机构|审计单位",
    re.IGNORECASE,
)
_AUDIT_OPINION_EVIDENCE = re.compile(
    r"\b(?:unmodified|unqualified)\s+opinion\b|"
    r"标准无保留意见|(?<!非)无保留意见",
    re.IGNORECASE,
)
_RISK_FACTOR_QUESTION = re.compile(
    r"\b(?:risks?|risk factors?)\b|风险(?:因素|点)?",
    re.IGNORECASE,
)
_CONSTRAINT_QUESTION = re.compile(
    r"\b(?:constraints?|limitations?)\b|限制因素|约束",
    re.IGNORECASE,
)
_RISK_FACTOR_EVIDENCE = re.compile(
    r"\b(?:risk factors? include|risks? include|important factors?[^.]{0,100}?could cause|"
    r"factors? that could adversely affect|could adversely affect|may adversely affect|"
    r"risk of\s+[a-z]|materially(?:\s+and)?\s+adversely affect\w*)\b|"
    r"风险因素(?:包括|是)|风险包括",
    re.IGNORECASE,
)
_CONSTRAINT_EVIDENCE = re.compile(
    r"\b(?:constraints?|limitations?|supply restrictions?|export controls?|"
    r"export restrictions?|tariffs?|regulatory (?:requirements?|risks?|actions?|"
    r"uncertaint\w*|changes|exposure|restrictions?)|"
    r"not assuming.{0,80}(?:revenue|sales).{0,80}(?:from|in)\s+[A-Z][A-Za-z]+)\b|"
    r"供应(?:限制|受限)|出口(?:管制|限制)|关税|监管要求|限制因素|约束",
    re.IGNORECASE,
)


def _is_segment_question(question: str) -> bool:
    return bool(_SEGMENT_QUESTION.search(question))


def _is_growth_driver_question(question: str) -> bool:
    # A summary can benefit from driver excerpts, but filtering all non-driver
    # financial evidence would discard its requested headline metrics. Only
    # explicit causal/driver questions use the driver-only retrieval path.
    return is_explicit_growth_driver_question(question)


def _has_growth_driver_evidence(item: SearchResult) -> bool:
    content = item.content or ""
    if (
        not _GROWTH_DRIVER_EVIDENCE.search(content)
        or _FORWARD_LOOKING_BOILERPLATE.search(content)
    ):
        return False
    if _AI_GROWTH_DRIVER_NARRATIVE.search(content):
        return True
    clauses = re.split(r"(?<=[.!?。！？;；])\s*|[\r\n]+", content)
    return any(
        _GROWTH_DRIVER_SUBJECT.search(clause)
        and _GROWTH_DRIVER_CHANGE.search(clause)
        and _GROWTH_DRIVER_CAUSE.search(clause)
        for clause in clauses
    )


_SUMMARY_METRIC_LABELS = (
    re.compile(r"\b(?:total\s+)?(?:net\s+)?(?:sales|revenues?)\b", re.IGNORECASE),
    re.compile(r"\bnet\s+(?:income|profit)\b", re.IGNORECASE),
    re.compile(r"\bgross\s+(?:profit|margin)\b", re.IGNORECASE),
    re.compile(r"\boperating\s+(?:income|margin|cash\s+flow)\b", re.IGNORECASE),
    re.compile(r"\b(?:diluted\s+)?earnings\s+per\s+(?:diluted\s+)?share\b|\beps\b", re.IGNORECASE),
    re.compile(r"\bdata\s+center\s+(?:compute\s+)?revenues?\b", re.IGNORECASE),
    re.compile(r"\bautomotive\s+(?:net\s+)?sales\b", re.IGNORECASE),
    re.compile(r"\bservices\s+(?:net\s+)?sales\b", re.IGNORECASE),
)
_GROWTH_NARRATIVE_EVIDENCE = re.compile(
    r"\b(?:growth|grew|increased|rose|higher|momentum|trajectory|"
    r"year[- ]over[- ]year|yoy|net sales growth|revenue growth)\b|"
    r"增长|同比|上升|提升|势头|动能|轨迹",
    re.IGNORECASE,
)
_SEGMENT_REVENUE_METRICS = frozenset(
    {
        "automotive_revenue",
        "services_revenue",
        "iphone_revenue",
        "products_revenue",
        "mac_revenue",
        "ipad_revenue",
        "wearables_revenue",
        "products_gross_margin",
        "services_gross_margin",
        "energy_revenue",
        "data_center_revenue",
        "edge_computing_revenue",
    }
)
_BROAD_COMPARISON_METRICS = (
    "revenue",
    "net_income",
    "gross_margin",
    "operating_margin",
    "operating_cash_flow",
    "eps",
)
_BROAD_COMPARISON_METRIC_SET = frozenset(_BROAD_COMPARISON_METRICS)


def _has_financial_summary_evidence(item: SearchResult) -> bool:
    """Recognize compact multi-metric summary evidence, not outlook boilerplate."""

    content = item.content or ""
    if (
        not extract_normalized_numbers(content)
        or _FORWARD_LOOKING_BOILERPLATE.search(content)
    ):
        return False
    return sum(bool(pattern.search(content)) for pattern in _SUMMARY_METRIC_LABELS) >= 2


def _has_growth_narrative_evidence(item: SearchResult) -> bool:
    """Recognize reported growth evidence for narrative comparisons.

    A narrative comparison needs more than a causal-driver sentence: a
    period-mapped row with a reported change (for example Apple net sales
    rising year over year) is also evidence. Safe-harbor boilerplate is
    explicitly excluded and unknown metadata remains eligible.
    """

    content = item.content or ""
    if (
        _FORWARD_LOOKING_BOILERPLATE.search(content)
        or re.search(
            r"\b(?:emerging growth company|large accelerated filer|"
            r"certification|registrant is)\b",
            content,
            re.IGNORECASE,
        )
    ):
        return False
    return bool(
        _GROWTH_NARRATIVE_EVIDENCE.search(content)
        and extract_normalized_numbers(content)
    ) or _has_growth_driver_evidence(item) or _has_financial_summary_evidence(item)


def _has_verified_financial_table_evidence(item: SearchResult) -> bool:
    """Recognize numeric, period-mapped table rows safe for summary coverage."""

    content = item.content or ""
    metadata = item.metadata or {}
    if str(metadata.get("content_type", "")).casefold() == "unverified_table":
        return False
    table_context = str(metadata.get("table_context", "") or "")
    is_table = bool(
        re.search(r"\bstructured\s+financial\s+table\s+row\b", content, re.IGNORECASE)
        or table_context.strip()
    )
    metric_ids = set(extract_metrics(f"{table_context}\n{content}"))
    return bool(
        is_table
        and extract_normalized_numbers(content)
        and metric_ids
        & {
            "revenue",
            "net_income",
            "gross_margin",
            "operating_margin",
            "operating_income",
            "eps",
            "operating_cash_flow",
        }
    )


def _verified_statement_metric_periods(item: SearchResult) -> frozenset[tuple[str, str]]:
    """Read canonical metric hints only from source-bound consolidated table rows.

    This is a retrieval hint, not Fact eligibility. The latter still requires
    the full P1.5 gate (including fiscal-calendar provenance) after retrieval.
    """

    metadata = item.metadata or {}
    if str(metadata.get("content_type", "")).casefold() != "table":
        return frozenset()
    payload = metadata.get("financial_table_rows_json")
    if not isinstance(payload, str) or not payload:
        return frozenset()
    try:
        rows = rows_from_json(payload)
    except (TypeError, ValueError):
        return frozenset()
    expected_company = canonical_company(str(metadata.get("company", "")))
    return frozenset(
        (normalization.canonical_metric, row.period)
        for row in rows
        if row.verification_status == VerificationStatus.VERIFIED
        and row.column_binding_proven
        and row.scope == "consolidated"
        and row.value is not None
        and row.period
        and row.source_locator
        and canonical_company(row.company or "") == expected_company
        if (normalization := normalize_financial_table_row(row)).canonical_metric
        and normalization.mapping_status in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}
    )


def _is_unverified_table(item: SearchResult) -> bool:
    """True when a chunk's numeric table layout was explicitly quarantined."""

    return str((item.metadata or {}).get("content_type", "")).casefold() == "unverified_table"


def _has_detailed_income_statement(item: SearchResult) -> bool:
    """Detect filings whose income statement is split across structured rows."""

    content = item.content or ""
    table_context = str(item.metadata.get("table_context", "") or "")
    combined = f"{table_context}\n{content}"
    return bool(
        re.search(r"\bstatements?\s+of\s+operations\b", combined, re.IGNORECASE)
        and re.search(r"\b(?:total\s+net\s+sales|total\s+revenues?)\b", content, re.IGNORECASE)
        and extract_normalized_numbers(content)
    )


def _extract_company_period_targets(question: str) -> dict[str, str]:
    """Bind one explicit period to a company when comparison clauses do so."""

    if len({name.casefold() for name in extract_companies(question)}) < 2:
        return {}
    targets: dict[str, str] = {}
    clauses = re.split(
        r"\b(?:and|vs\.?|versus|compared\s+(?:to|with))\b|[;,，、]|(?:以及|并且|对比|相比|和|与|及)",
        question or "",
        flags=re.IGNORECASE,
    )
    for clause in clauses:
        companies = extract_companies(clause)
        periods = extract_periods(clause)
        if len(companies) == 1 and len(periods) == 1:
            targets[companies[0].casefold()] = periods[0]
    return targets


def _has_specific_risk_evidence(item: SearchResult) -> bool:
    """Identify concrete risk/constraint content, not a generic safe-harbor disclaimer."""

    content = item.content or ""
    if content.count("Item ") >= 3:
        return False
    # Chinese annual reports may enumerate named risks without the English
    # causal phrasing or "风险包括". Require both an actual risk section and
    # a concrete numbered disclosure, not an isolated disclaimer keyword.
    chinese_risk_list = (
        re.search(r"(?:可能面对的风险|风险因素|主要风险)",
                  str(item.metadata.get("section", "")) + "\n" + content)
        and re.search(r"(?:一是|二是|三是|[（(][一二三四][）)])[^。；;\n]{2,40}风险", content)
    )
    return bool(_SPECIFIC_RISK_EVIDENCE.search(content) or chinese_risk_list)


def _is_risk_question(question: str) -> bool:
    return bool(_RISK_QUESTION.search(question or ""))


def _is_audit_report_question(question: str) -> bool:
    return bool(_AUDIT_REPORT_QUESTION.search(question or ""))


def _has_risk_factor_evidence(item: SearchResult) -> bool:
    content = item.content or ""
    return bool(
        content.count("Item ") < 3
        and _RISK_FACTOR_EVIDENCE.search(content)
    )


def _has_constraint_evidence(item: SearchResult) -> bool:
    content = item.content or ""
    return bool(
        content.count("Item ") < 3
        and _CONSTRAINT_EVIDENCE.search(content)
    )


def _segment_section(item: SearchResult) -> str | None:
    """Return a non-generic financial section with numeric segment facts."""

    section = str(item.metadata.get("section", "") or "").strip()
    if not section or _NON_SEGMENT_SECTION.fullmatch(section):
        lines = [line.strip().strip("#* ") for line in (item.content or "").splitlines()]
        for index, candidate in enumerate(lines):
            words = candidate.split()
            if (
                not candidate
                or len(words) < 2
                or len(words) > 6
                or any(re.search(r"\d", word) for word in words)
                or _NON_SEGMENT_SECTION.fullmatch(candidate)
            ):
                continue
            is_title = all(word[:1].isupper() for word in words) or candidate.isupper()
            nearby = " ".join(lines[index + 1 : index + 4])
            if (
                is_title
                and _SEGMENT_FINANCIAL_VALUE.search(nearby)
                and extract_normalized_numbers(nearby)
            ):
                section = candidate
                break
    if (
        not section
        or _NON_SEGMENT_SECTION.fullmatch(section)
        or not _SEGMENT_FINANCIAL_VALUE.search(item.content or "")
        or not extract_normalized_numbers(item.content or "")
    ):
        content = item.content or ""
        # Some filings (notably 10-Q exports) expose product/service rows as
        # structured table chunks while the section metadata is only
        # ``Three Months Ended``. Use the filing-native label as the segment
        # identity so cross-company segment queries reserve it alongside
        # titled sections such as Data Center and Edge Computing.
        label = _SEGMENT_DISCLOSURE_LABEL.search(content)
        if label and (
            extract_normalized_numbers(content)
            or re.search(
                r"(?i)\b(?:increased|decreased|grew|growth|higher|lower|driven\s+by)\b|"
                r"增长|增加|上升|下降|提高|主要由",
                content,
            )
        ):
            return f"{label.group(1).casefold()} segment"
        if _SEGMENT_DISCLOSURE_TABLE.search(content) and extract_normalized_numbers(content):
            return "disaggregated revenue"
        return None
    return re.sub(r"\s+", " ", section).casefold()

# Enrichment supplies filing terminology, but a 2x lexical multiplier lets
# generic words overpower explicit period/table evidence.
_ENRICHED_QUERY_LEXICAL_WEIGHT_MULTIPLIER = 1.25

# =========================
# Data Classes
# =========================

@dataclass
class RetrievalResult:
    top_k: List
    scores: List
    chunks: List
    document_ids: List[str]
    companies: List[str]


@dataclass(frozen=True)
class HybridRetrievalConfig:
    """Configuration for deterministic reciprocal-rank fusion."""

    enabled: bool = True
    vector_weight: float = 1.0
    lexical_weight: float = 1.0
    rrf_k: int = 60
    candidate_multiplier: int = 4

    def __post_init__(self) -> None:
        if self.vector_weight < 0 or self.lexical_weight < 0:
            raise ValueError("hybrid retrieval weights cannot be negative")
        if self.vector_weight + self.lexical_weight <= 0:
            raise ValueError("at least one hybrid retrieval weight must be positive")
        if self.rrf_k < 1:
            raise ValueError("rrf_k must be at least 1")
        if self.candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be at least 1")


# =========================
# Helper Functions
# =========================

def extract_keyword(query: str) -> str:
    words = re.findall(r'\w+', query.lower())
    words = [w for w in words if len(w) > 3]
    if not words:
        return query.lower()
    return max(words, key=len)


def extract_local_context(chunk: str, query: str, window: int = 2) -> str:
    keyword = extract_keyword(query)
    sentences = re.split(r'(?<=[.!?])\s+', chunk)
    hit_index = -1
    for i, sentence in enumerate(sentences):
        if keyword in sentence.lower():
            hit_index = i
            break
    if hit_index == -1:
        return chunk
    start = max(0, hit_index - window)
    end = min(len(sentences), hit_index + window + 1)
    return " ".join(sentences[start:end])


# =========================
# HybridRetriever
# =========================

class HybridRetriever:
    """
    V4 Retrieval Orchestrator

    Responsibility:
    - Interpret RetrievalContext
    - Apply filters (metadata + document)
    - Delegate vector search to EmbeddingStore
    - Post-filter and return SearchResult[]
    """

    def __init__(
        self,
        model=None,
        *,
        config: HybridRetrievalConfig | None = None,
        lexical_retriever: BM25Retriever | None = None,
    ):
        self.model = model
        self._model_lock = Lock()
        self.metadata_filter = MetadataFilter()
        self.document_filter = DocumentFilter()
        self.config = config or HybridRetrievalConfig()
        self.lexical_retriever = lexical_retriever or BM25Retriever()

    # =========================
    # V4: New Primary Interface
    # =========================

    def retrieve(
        self,
        context: RetrievalContext,
        store: EmbeddingStore,
    ) -> List[SearchResult]:
        if context.top_k <= 0:
            return []

        doc_filter = self.document_filter.build(context.document_ids)
        meta_filter = self.metadata_filter.build(
            company=context.company,
            filters=context.filters,
        )

        retrieval_query = enrich_financial_query(
            context.question,
            context.company,
        )
        query_embedding = self._get_query_embedding(retrieval_query)
        query_scope = classify_query_scope(context.question)
        query_metric_ids = tuple(extract_metrics(context.question))
        requested_segment_metrics = set(canonical_metrics(context.question)) & _SEGMENT_REVENUE_METRICS
        segment_question = _is_segment_question(context.question)
        driver_question = _is_growth_driver_question(context.question)
        growth_narrative_question = is_growth_narrative_question(context.question)
        broad_summary_question = (
            query_scope == QueryScope.SUMMARY
            and not query_metric_ids
        )
        broad_compare_question = query_scope == QueryScope.COMPARE and any(
            marker in context.question.casefold()
            for marker in (
                "financial performance",
                "key metrics",
                "revenue performance",
                "财务表现",
                "主要指标",
                "营收表现",
                "收入表现",
                "营收对比",
                "收入对比",
                "growth narrative",
                "growth momentum",
                "增长势头",
                "增长叙事",
            )
        ) or (
            query_scope == QueryScope.COMPARE
            and "relevant prior user request for reference resolution:" in context.question.casefold()
            and re.search(
                r"\b(?:analy[sz]e|review|summari[sz]e)\b.{0,100}\b(?:report|filing|financial)\b"
                r"|分析.{0,24}(?:财报|报告)|报告分析",
                context.question,
                re.IGNORECASE,
            ) is not None
        )
        risk_question = _is_risk_question(context.question)
        audit_report_question = _is_audit_report_question(context.question)
        candidate_multiplier = self.config.candidate_multiplier
        # Summary/comparison questions need one authoritative table per
        # requested company. Those rows can sit below narrative matches in
        # both vector and lexical lists, so retain a wider candidate pool for
        # the coverage-aware selector while keeping the final top-k unchanged.
        if (
            query_scope in {QueryScope.SUMMARY, QueryScope.COMPARE}
            or len(query_metric_ids) > 1
            or requested_segment_metrics
        ):
            candidate_multiplier = max(candidate_multiplier, 8)
        candidate_k = context.top_k * candidate_multiplier
        tenant_scopes = [context.tenant_id]
        if context.include_public and context.tenant_id != 0:
            tenant_scopes.append(0)

        vector_results: list[SearchResult] = []
        for tenant_id in tenant_scopes:
            scoped_results = store.similarity_search(
                query_embedding=query_embedding,
                top_k=candidate_k,
                tenant_id=tenant_id,
            )
            scoped_results = self._apply_tenant_scope(scoped_results, tenant_id)
            vector_results.extend(
                self._apply_filters(scoped_results, doc_filter, meta_filter)
            )

        # Merge independently ranked tenant scopes only when the store exposes
        # score direction. Legacy stores without semantics retain their stable
        # best-first ordering.
        vector_results = self._deduplicate(
            self._globally_rank_vector_results(vector_results)
        )[:candidate_k]

        def vector_only_results() -> list[SearchResult]:
            # Keep legacy vector-only ordering for unconstrained questions,
            # but do not bypass period-aware selection when the lexical index
            # is disabled or unavailable. Explicitly quarantined table rows
            # are never exposed to the answer model: their column mapping is
            # known to be unreliable, even if their semantic score is high.
            safe_vector_results = [item for item in vector_results if not _is_unverified_table(item)]
            return self.coverage_aware_rerank(
                safe_vector_results,
                context.question,
                top_k=context.top_k,
                company=context.company,
            )

        if not self.config.enabled or self.config.lexical_weight == 0:
            return vector_only_results()

        lexical_corpus = self._load_lexical_corpus(
            store=store,
            tenant_scopes=tenant_scopes,
            doc_filter=doc_filter,
            meta_filter=meta_filter,
        )
        if not lexical_corpus:
            return vector_only_results()

        coverage_pool_k = (
            max(candidate_k, 256)
            if query_scope in {QueryScope.SUMMARY, QueryScope.COMPARE}
            or risk_question
            or len(query_metric_ids) > 1
            or requested_segment_metrics
            else candidate_k
        )
        lexical_results = self.lexical_retriever.search(
            query=retrieval_query,
            documents=lexical_corpus,
            top_k=coverage_pool_k,
        )
        # Long bilingual enrichment strings can dilute BM25 scores for dense
        # statement rows. Run short, company-partitioned structural queries
        # to augment candidate recall, but append their hits after the broad
        # lexical ranking so a targeted lookup does not falsify BM25 ranks.
        # RRF and the coverage selector still decide the final ranking. This is also
        # needed for fact/analysis questions whose requested table is several
        # pages away from the semantically closest narrative paragraph.
        requested_metrics = set(query_metric_ids)
        if query_scope in {
            QueryScope.SUMMARY,
            QueryScope.COMPARE,
            QueryScope.ANALYSIS,
            QueryScope.RISK,
        } or requested_metrics or segment_question or driver_question or risk_question or audit_report_question:
            companies = extract_companies(context.question)
            if not companies and context.company:
                companies = [context.company]
            targeted_lexical: list[SearchResult] = []
            priority_segment_driver_evidence: list[SearchResult] = []
            priority_audit_evidence: list[SearchResult] = []
            metrics = set(extract_metrics(context.question))
            suffixes: tuple[str, ...]
            if risk_question:
                suffixes = (
                    "risk factors",
                    "risks and uncertainties",
                    "factors that could cause actual results to differ",
                    "supply constraints",
                    "export restrictions",
                    "regulatory requirements",
                    "风险因素",
                    "供应限制",
                    "出口管制",
                )
            elif audit_report_question:
                suffixes = (
                    "auditor audit firm audit opinion unqualified opinion",
                    "independent auditor report opinion",
                    "会计师事务所 审计机构 审计意见 标准无保留意见",
                    "注册会计师签名 审计报告",
                )
            else:
                requested: list[str] = []
                if query_scope == QueryScope.COMPARE or "revenue" in metrics:
                    requested.extend(("total net sales", "total revenues"))
                if query_scope == QueryScope.COMPARE and any(
                    marker in context.question.casefold()
                    for marker in ("financial performance", "key metrics", "财务表现", "主要指标")
                ):
                    requested.extend(
                        (
                            "net income",
                            "gross margin",
                            "diluted earnings per share",
                            "cash generated by operating activities",
                        )
                    )
                if "gross_margin" in metrics:
                    requested.extend(("gross margin", "gross profit"))
                if "operating_margin" in metrics:
                    requested.extend(("operating margin", "operating profit margin"))
                if "services" in metrics:
                    requested.extend(("services net sales", "services gross margin"))
                if "data_center" in metrics:
                    requested.extend(("data center revenue", "data center compute"))
                if "net_income" in metrics:
                    requested.append("net income")
                if "operating_cash_flow" in metrics or "cash_flow" in metrics:
                    requested.append("cash generated by operating activities")
                if "free_cash_flow" in metrics:
                    requested.append("free cash flow")
                if segment_question:
                    requested.extend(
                        (
                            "business segment revenue",
                            "revenue by segment",
                            "reportable segment sales",
                        )
                    )
                if driver_question:
                    requested.extend(
                        (
                            "growth drivers",
                            "growth driven by",
                            "reasons for growth",
                            "demand accelerating rapidly",
                        )
                    )
                if growth_narrative_question:
                    # Narrative comparisons need both reported growth facts
                    # and explicit management commentary for every issuer.
                    # Do not turn this into the driver-only path: statement
                    # rows still establish the measured change being ranked.
                    requested.extend(
                        (
                            "revenue growth",
                            "net sales growth",
                            "growth momentum",
                            "growth narrative",
                            "growth driven by",
                            "reasons for growth",
                        )
                    )
                if not requested:
                    requested.extend(("financial summary", "statement of operations"))
                suffixes = tuple(dict.fromkeys(requested))
            target_companies = companies or [None]
            priority_financial_evidence: list[SearchResult] = []
            for company in target_companies:
                company_lexical_corpus = lexical_corpus
                if company:
                    company_key = company.casefold()
                    scoped_company_documents = [
                        item
                        for item in lexical_corpus
                        if (
                            company_key
                            in str(item.metadata.get("company", "")).casefold()
                            or company_key
                            in {
                                name.casefold()
                                for name in extract_companies(
                                    str(item.metadata.get("company", ""))
                                )
                            }
                        )
                    ]
                    # Table cells often omit the issuer name in their body.
                    # Searching every issuer for "Tesla net income" then
                    # ranks by the shared metric token and lets a large
                    # Apple filing crowd out Tesla rows before reranking.
                    # Use issuer metadata to augment the candidate pool only;
                    # final ranking remains cross-company and metadata is not
                    # used as an evidence hard-filter.
                    if scoped_company_documents:
                        company_lexical_corpus = scoped_company_documents
                if company and query_scope == QueryScope.FACT and metrics:
                    requested_periods = set(extract_periods(context.question)) | set(
                        extract_annual_periods(context.question)
                    )
                    statement_rows = [
                        item
                        for item in company_lexical_corpus
                        if any(
                            metric_id in metrics
                            and (not requested_periods or row_period in requested_periods)
                            for metric_id, row_period in _verified_statement_metric_periods(item)
                        )
                    ]
                    # A typed, period-matched statement row must reach RRF
                    # even when bilingual BM25 ranks a segment row higher.
                    priority_financial_evidence.extend(statement_rows[:16])
                    targeted_lexical.extend(statement_rows[:16])
                if audit_report_question:
                    # Audit summaries often sit near the front of an annual
                    # report and are semantically distant from the detailed
                    # auditor opinion. Promote only chunks that explicitly
                    # contain both the firm identity and opinion classification
                    # so the answer context can support both requested facts.
                    priority_audit_evidence.extend(
                        item
                        for item in company_lexical_corpus
                        if _AUDITOR_IDENTITY_EVIDENCE.search(item.content or "")
                        and _AUDIT_OPINION_EVIDENCE.search(item.content or "")
                    )
                for suffix in suffixes:
                    lexical_query = f"{company} {suffix}" if company else suffix
                    targeted_lexical.extend(
                        self.lexical_retriever.search(
                            query=lexical_query,
                            documents=company_lexical_corpus,
                            # Broad financial comparisons need cross-metric
                            # coverage (including net income rows that may be
                            # lexically weaker than revenue highlights). Keep
                            # the same expanded candidate pool used by the
                            # final selector; truncating each structural probe
                            # to the vector candidate size can drop a required
                            # issuer/metric pair before coverage-aware ranking.
                            top_k=(
                                coverage_pool_k
                                if risk_question or broad_compare_question
                                else candidate_k
                            ),
                        )
                    )
                if requested_segment_metrics:
                    # The plain PDF reading-order representation of a
                    # multi-period table is intentionally marked
                    # ``unverified_table``. Retrieve the matching structured
                    # row representation directly so it remains available
                    # even when the user's wording is an elliptical segment
                    # request ("How is Services doing?") rather than a formal
                    # "revenue by segment" query.
                    targeted_lexical.extend(
                        item
                        for item in company_lexical_corpus
                        if not _is_unverified_table(item)
                        and requested_segment_metrics.intersection(
                            canonical_metrics(item.content or "")
                        )
                    )
                    # Segment performance questions often use informal
                    # wording ("How is Services doing?") while the filing
                    # explains the result in adjacent MD&A prose rather than
                    # in another table row. Keep only driver passages that
                    # name one of the requested segments; the period-aware
                    # selector below still decides whether they belong in the
                    # final context.
                    priority_segment_driver_evidence.extend(
                        item
                        for item in company_lexical_corpus
                        if _has_growth_driver_evidence(item)
                        and requested_segment_metrics.intersection(
                            canonical_metrics(item.content or "")
                        )
                    )
                    targeted_lexical.extend(priority_segment_driver_evidence)
                elif segment_question:
                    # A broad segment-overview query has no explicit metric
                    # alias, so ``requested_segment_metrics`` is empty. Keep
                    # every verified segment row for each named issuer in the
                    # candidate pool; otherwise lexical wording (especially
                    # Chinese vs English) can retain Services for one
                    # language and Products for the other before the
                    # coverage selector sees the full segment set.
                    targeted_lexical.extend(
                        item
                        for item in company_lexical_corpus
                        if not _is_unverified_table(item)
                        and _SEGMENT_REVENUE_METRICS.intersection(
                            canonical_metrics(item.content or "")
                        )
                    )
                if broad_summary_question and company:
                    structured_rows = [
                        item
                        for item in company_lexical_corpus
                        if _has_verified_financial_table_evidence(item)
                    ]
                    priority_financial_evidence.extend(structured_rows)
                    targeted_lexical.extend(structured_rows)
            if segment_question:
                # Financial-report parsers often preserve segment labels as
                # section metadata while the body says only "First-quarter
                # revenue". Include those structured rows as candidates even
                # when their prose does not repeat the phrase "business
                # segment" (for example, "Data Center" / "Edge Computing").
                targeted_lexical.extend(
                    item
                    for item in lexical_corpus
                    if _segment_section(item) is not None
                )
            if driver_question:
                # Growth drivers are often stated in management commentary,
                # not in the income-statement rows that dominate vector
                # similarity for a financial filing. Exclude safe-harbor
                # boilerplate from the required evidence slot below.
                targeted_lexical.extend(
                    item
                    for item in lexical_corpus
                    if _has_growth_driver_evidence(item)
                )
            if broad_summary_question:
                # A general results summary should see the filing's compact
                # highlights and concrete growth commentary even when the
                # query does not contain their exact metric labels.
                targeted_lexical.extend(
                    item
                    for item in lexical_corpus
                    if _has_financial_summary_evidence(item)
                    or _has_growth_driver_evidence(item)
                )
            if broad_compare_question:
                # Some filings flatten a multi-metric financial summary into
                # one dense table chunk. Individual metric probes can rank
                # separate row chunks highly while omitting that summary row
                # (especially net income) from the bounded lexical pool. Add
                # verified summary blocks and issuer-scoped, numeric rows for
                # every comparison metric. A capped generic BM25 list can
                # otherwise omit one company's gross-margin/ cash-flow row,
                # making equivalent English and Chinese comparisons receive
                # different evidence solely due to query tokenization.
                summaries = [
                    item
                    for item in company_lexical_corpus
                    if _has_financial_summary_evidence(item)
                ]
                comparison_rows = [
                    item
                    for item in company_lexical_corpus
                    if _has_verified_financial_table_evidence(item)
                    and _BROAD_COMPARISON_METRIC_SET.intersection(
                        canonical_metrics(item.content or "")
                    )
                ]
                priority_financial_evidence.extend((*summaries, *comparison_rows))
                targeted_lexical.extend((*summaries, *comparison_rows))
            if query_scope == QueryScope.COMPARE and "revenue" in metrics:
                # Revenue comparisons need the issuer's period-mapped total
                # revenue row even when a bilingual BM25 query ranks a dense
                # narrative or an unheaded statement fragment higher.  This
                # is a candidate boost, not a hard filter: coverage-aware
                # reranking still decides the final context and may retain
                # additional evidence.  Keeping the boost tied to the
                # explicit total-revenue label avoids promoting segment or
                # outlook rows as if they were headline revenue.
                revenue_rows = [
                    item
                    for item in company_lexical_corpus
                    if _has_verified_financial_table_evidence(item)
                    and re.search(
                        r"\b(?:metric:\s*)?total\s+(?:net\s+sales|revenues?)\b"
                        r"(?=\s*[:|]|\s+\$?\d)",
                        item.content or "",
                        re.IGNORECASE,
                    )
                ]
                # Put the canonical total-revenue rows ahead of optional
                # comparison metrics; otherwise a large list of lower-risk
                # table rows can consume the priority prefix before this
                # headline fact is seen by RRF.
                priority_financial_evidence[0:0] = revenue_rows
                targeted_lexical.extend(revenue_rows)
            if growth_narrative_question:
                # The default comparison probes focus on statement metrics and
                # can omit issuer-specific MD&A growth passages. Put both
                # classes into the bounded RRF pool before coverage selection.
                narrative_rows = [
                    item
                    for item in company_lexical_corpus
                    if _has_growth_narrative_evidence(item)
                ]
                priority_financial_evidence.extend(narrative_rows)
                targeted_lexical.extend(narrative_rows)
            lexical_results = self._deduplicate([*lexical_results, *targeted_lexical])
            if priority_financial_evidence:
                # Keep each issuer's evidence-dense summary inside the bounded
                # RRF candidate pool. Appending these rows after a large
                # cross-document BM25 list is insufficient: RRF truncates
                # before the coverage selector sees them.
                lexical_results = self._deduplicate(
                    [*priority_financial_evidence, *lexical_results]
                )
            if priority_audit_evidence:
                lexical_results = self._deduplicate(
                    [*priority_audit_evidence, *lexical_results]
                )
            if priority_segment_driver_evidence:
                # The source prose may sit below the bounded generic BM25
                # window. Promote only issuer-scoped, requested-segment driver
                # passages into the RRF candidate pool; coverage-aware
                # selection must still satisfy the same issuer/period slot.
                lexical_results = self._deduplicate(
                    [*priority_segment_driver_evidence, *lexical_results]
                )
            if query_scope == QueryScope.COMPARE and "revenue" in metrics:
                # The issuer-scoped probes above can still leave a canonical
                # total-revenue row deep in the merged lexical list when the
                # Chinese wording has weaker BM25 overlap. Promote the rows
                # that are already present in the candidate pool immediately
                # before RRF; this keeps the operation deterministic without
                # treating metadata as an evidence hard filter.
                canonical_revenue_rows = [
                    item
                    for item in lexical_results
                    if _has_verified_financial_table_evidence(item)
                    and re.search(
                        r"\b(?:metric:\s*)?total\s+(?:net\s+sales|revenues?)\b"
                        r"(?=\s*[:|]|\s+\$?\d)",
                        item.content or "",
                        re.IGNORECASE,
                    )
                ]
                lexical_results = self._deduplicate(
                    [*canonical_revenue_rows, *lexical_results]
                )
        if not lexical_results:
            # A missing lexical channel is not permission to skip the shared
            # safety and selection stages. Keep the vector-only fallback on
            # the same path as fused candidates so quarantined table chunks
            # are isolated and coverage-aware reranking still runs.
            return vector_only_results()

        if risk_question:
            # Short issuer-scoped risk lists often omit the company/year in
            # their body and can score zero in generic BM25 probes. Admit
            # concrete disclosures from the already scoped corpus before RRF;
            # the shared period/safety/coverage pipeline still decides selection.
            risk_candidates = [item for item in lexical_corpus
                               if _has_specific_risk_evidence(item)]
            lexical_results = self._deduplicate([*risk_candidates, *lexical_results])
        fused = self._reciprocal_rank_fusion(
            vector_results,
            lexical_results,
            # Preserve the complete candidate pool until coverage-aware
            # reranking can select a period-matched table row.
            top_k=coverage_pool_k,
            lexical_weight=(
                self.config.lexical_weight
                * _ENRICHED_QUERY_LEXICAL_WEIGHT_MULTIPLIER
                if retrieval_query != context.question
                else self.config.lexical_weight
            ),
        )
        reranked = self.coverage_aware_rerank(
            fused,
            context.question,
            top_k=context.top_k,
            company=context.company,
        )
        if audit_report_question:
            # Keep the filing's compact auditor/opinion disclosure ahead of
            # the longer auditor's report body. The latter is semantically
            # similar but often states only the opinion's reasoning, causing
            # generation to omit the explicit firm suffix and opinion class.
            explicit_audit_facts = [
                item
                for item in reranked
                if _AUDITOR_IDENTITY_EVIDENCE.search(item.content or "")
                and _AUDIT_OPINION_EVIDENCE.search(item.content or "")
            ]
            reranked = self._deduplicate([*explicit_audit_facts, *reranked])[: context.top_k]
        return reranked

    @staticmethod
    def coverage_aware_rerank(
        results: List[SearchResult],
        question: str,
        *,
        top_k: int,
        company: str | None = None,
    ) -> List[SearchResult]:
        """Select a diverse evidence set without hard-filtering uncertain metadata.

        RRF remains the semantic baseline.  Small bounded boosts reward explicit
        company/period/metric/table matches, then coverage slots keep a matching
        item when one exists.  Missing metadata is therefore neutral rather than
        an exclusion, which is important for OCR and legacy chunks.
        """

        if top_k <= 0 or not results:
            return []
        # A parser explicitly labels these rows when its numeric values cannot
        # be bound safely to printed period columns. Do not leave them in
        # answer context as untrusted distractors; validated row-level table
        # chunks remain eligible and are preferred through coverage slots.
        results = [item for item in results if not _is_unverified_table(item)]
        if not results:
            return []
        has_comparable_vector_scores = any(
            HybridRetriever._vector_relevance(item) is not None
            for item in results
        )
        expected_companies = {item.casefold() for item in extract_companies(question)}
        if company and not expected_companies:
            expected_companies.add(company.casefold())
        company_period_targets = _extract_company_period_targets(question)
        filters = query_filters(question)
        expected_company_periods = dict(company_period_targets)
        if "metric" not in filters:
            lowered_question = question.casefold()
            if any(
                marker in lowered_question
                for marker in (
                    "operating cash flow",
                    "cash generated by operating activities",
                    "经营活动现金流",
                    "经营活动产生的现金流",
                )
            ):
                # Keep metric coverage deterministic even when the generic
                # period/metric parser has no explicit filter entry.
                filters["metric"] = "operating_cash_flow"
        query_scope = classify_query_scope(question)
        segment_question = _is_segment_question(question)
        driver_question = _is_growth_driver_question(question)
        growth_narrative_question = is_growth_narrative_question(question)
        query_metric_ids = tuple(extract_metrics(question))
        requested_segment_metrics = tuple(
            metric_id
            for metric_id in canonical_metrics(question)
            if metric_id in _SEGMENT_REVENUE_METRICS
        )
        broad_summary_question = (
            query_scope == QueryScope.SUMMARY
            and not query_metric_ids
        )
        broad_compare_question = query_scope == QueryScope.COMPARE and any(
            marker in question.casefold()
            for marker in (
                "financial performance",
                "key metrics",
                "revenue performance",
                "财务表现",
                "主要指标",
                "营收表现",
                "收入表现",
                "营收对比",
                "收入对比",
                "growth narrative",
                "growth momentum",
                "增长势头",
                "增长叙事",
            )
        ) or (
            query_scope == QueryScope.COMPARE
            and "relevant prior user request for reference resolution:" in question.casefold()
            and re.search(
                r"\b(?:analy[sz]e|review|summari[sz]e)\b.{0,100}\b(?:report|filing|financial)\b"
                r"|分析.{0,24}(?:财报|报告)|报告分析",
                question,
                re.IGNORECASE,
            ) is not None
        )
        risk_question = _is_risk_question(question)
        risk_factor_question = bool(_RISK_FACTOR_QUESTION.search(question or ""))
        constraint_question = bool(_CONSTRAINT_QUESTION.search(question or ""))
        period_metric_scope = query_scope == QueryScope.FACT or (
            query_scope == QueryScope.COMPARE and bool(query_metric_ids)
        )
        if period_metric_scope and filters.get("period"):
            for expected_company in expected_companies:
                expected_company_periods.setdefault(
                    expected_company,
                    filters["period"],
                )

        # Preserve exact query intent when two candidates have nearly equal
        # fused scores.  RRF intentionally combines independent rankings, but
        # a broad narrative can otherwise edge out the sentence containing a
        # distinctive requested term (for example ``accelerated``).  This is
        # a small lexical tie-breaker, not a replacement for vector/BM25
        # ranking and it does not introduce hard filters.
        query_terms = {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u3400-\u9fff]{2,}", question)
        }

        def dimensions(item: SearchResult) -> set[str]:
            content = item.content or ""
            company = str(item.metadata.get("company", "")).casefold()
            dims: set[str] = set()
            if expected_companies and company in expected_companies:
                dims.add("company")
                dims.add(f"company:{company}")
            expected_company_period = expected_company_periods.get(company)
            if expected_company_period and matches_filter(
                content,
                item.metadata,
                "period",
                expected_company_period,
            ):
                dims.add("period")
                dims.add(f"company_period:{company}:{expected_company_period}")
            for key, value in filters.items():
                if matches_filter(content, item.metadata, key, value):
                    dims.add(key)
                    if key == "metric" and value in {"cash_flow", "operating_cash_flow"}:
                        markers = (
                            "cash generated by operating activities",
                            "operating cash flow",
                            "经营活动产生的现金流",
                            "经营活动现金流",
                        )
                        for line in content.splitlines():
                            lowered_line = line.casefold()
                            # A narrative reconciliation line can mention
                            # the metric before the actual statement row.
                            # Reserve metric_value only for a row whose label
                            # starts the line and whose numbers are on that
                            # same row.
                            row_label = re.match(
                                r"(?:^|\|)\s*(?:\|\s*)*(?:cash\s+generated\s+by\s+operating\s+activities|"
                                r"operating\s+cash\s+flow|经营活动产生的现金流|经营活动现金流)\b",
                                lowered_line,
                            )
                            if (
                                row_label
                                and any(marker in lowered_line for marker in markers)
                                and extract_normalized_numbers(line)
                            ):
                                dims.add("metric_value")
                                break
            table_context = str(item.metadata.get("table_context", "") or "")
            lowered = f"{table_context}\n{content}".casefold()
            annual_periods = extract_annual_periods(f"{table_context}\n{content}")
            mapped_periods = tuple(
                dict.fromkeys(
                    (*extract_periods(f"{table_context}\n{content}"), *annual_periods)
                )
            )
            quarter_table = "three months ended" in table_context.casefold()
            if quarter_table:
                dims.add("quarter_table")
            typed_statement_rows = _verified_statement_metric_periods(item)
            financial_table = bool(typed_statement_rows) or any(
                marker in lowered
                for marker in (
                    "structured financial table row",
                    "financial summary",
                    "statement of operations",
                    "condensed consolidated",
                    "three months ended",
                    "six months ended",
                    "total revenues",
                    "total net sales",
                    "net income attributable",
                )
            )
            if financial_table or "table" in question.casefold() or "financial statement" in question.casefold():
                if financial_table or any(marker in lowered for marker in ("table", "statement", "unaudited")):
                    dims.add("table")
            verified_row_metadata = (
                str(item.metadata.get("content_type", "")).casefold()
                != "unverified_table"
            )
            if "metric" in dims and extract_normalized_numbers(content):
                dims.add("metric_value")
                if financial_table and verified_row_metadata:
                    dims.add("table_metric_value")
                    if company:
                        dims.add(f"table_metric_value:{company}")
            elif (
                query_scope == QueryScope.SUMMARY
                and financial_table
                and verified_row_metadata
                and extract_normalized_numbers(content)
            ):
                dims.add("table_metric_value")
                if company:
                    dims.add(f"table_metric_value:{company}")
            if financial_table and verified_row_metadata and extract_normalized_numbers(content):
                for row_metric, row_period in typed_statement_rows:
                    dims.add(f"table_metric_value:{row_metric}")
                    if company:
                        dims.add(f"table_metric_value:{company}:{row_metric}")
                        dims.add(f"table_metric_value:{company}:{row_period}:{row_metric}")
                if annual_periods:
                    for annual_period in annual_periods:
                        if company:
                            dims.add(f"annual_period:{company}:{annual_period}")
                structured_row_prefix = r"(?:row\s+\d+\s*:\s*)?(?:metric\s*:\s*)?"
                strict_rows = {
                    "revenue": re.compile(
                        rf"(?:\btotal\s+net\s+sales\b|\btotal\s+revenues?\b|(?:^|\|)\s*(?:\|\s*)*{structured_row_prefix}revenue\b)",
                        re.IGNORECASE,
                    ),
                    "net_income": re.compile(
                        rf"(?:^|\|)\s*(?:\|\s*)*{structured_row_prefix}net\s+income\b",
                        re.IGNORECASE,
                    ),
                    "operating_cash_flow": re.compile(
                        rf"(?:^|\|)\s*(?:\|\s*)*{structured_row_prefix}cash\s+(?:generated\s+by\s+operating\s+activities|flow\s+from\s+operating\s+activities|provided\s+by\s+operating\s+activities)\b",
                        re.IGNORECASE,
                    ),
                    "free_cash_flow": re.compile(
                        # PDF table extraction can flatten several adjacent
                        # rows onto one physical line (the Tesla summary is a
                        # real example: the FCF row follows operating cash
                        # flow and capex on the same line).  The chunk is
                        # already restricted to a verified table with a
                        # reliable column map, so match the labelled row
                        # anywhere in that line instead of requiring a line
                        # or pipe boundary.  This preserves period binding
                        # from ``table_context`` without treating narrative
                        # mentions as authoritative table values.
                        r"\bfree\s+cash\s+flow\b",
                        re.IGNORECASE,
                    ),
                    "gross_profit": re.compile(
                        rf"(?:^|\|)\s*(?:\|\s*)*{structured_row_prefix}"
                        rf"(?:total\s+)?(?:gaap\s+)?gross\s+(?:profit|margin)\b",
                        re.IGNORECASE,
                    ),
                    "operating_margin": re.compile(
                        rf"(?:\bmetric\s*:\s*operating\s+(?:profit\s+)?margin\b|"
                        rf"(?:^|\|)\s*(?:\|\s*)*{structured_row_prefix}operating\s+(?:profit\s+)?margin\b)",
                        re.IGNORECASE,
                    ),
                    "eps": re.compile(
                        rf"(?:^|\|)\s*(?:\|\s*)*{structured_row_prefix}(?:diluted\s+)?(?:earnings\s+per\s+share|eps)\b",
                        re.IGNORECASE,
                    ),
                }
                for row in content.splitlines():
                    if not extract_normalized_numbers(row):
                        continue
                    if query_scope == QueryScope.FACT:
                        category_match = re.search(
                            r"\bDimension\s*:\s*[^;|]+;\s*Category\s*:\s*([^|\n]+)",
                            row,
                            re.IGNORECASE,
                        )
                        if category_match and category_match.group(1).strip().casefold() not in question.casefold():
                            continue
                    metric_row = re.sub(
                        r"^\s*(?:structured\s+)?financial\s+table\s+row\b.*?\bmetric\s*:\s*",
                        "",
                        row,
                        flags=re.IGNORECASE,
                    )
                    value_fields = [
                        field
                        for field in metric_row.split("|")[1:]
                        if not re.match(r"\s*yoy\s*:", field, re.IGNORECASE)
                    ]
                    row_numbers = (
                        [
                            number
                            for field in value_fields
                            for number in extract_normalized_numbers(field)
                        ]
                        if value_fields
                        else extract_normalized_numbers(row)
                    )
                    for row_metric, pattern in strict_rows.items():
                        if not pattern.search(metric_row):
                            continue
                        if row_metric == "gross_profit" and any(
                            number.kind in {"percent", "basis_points"}
                            for number in row_numbers
                        ):
                            row_metric = "gross_margin"
                        dims.add(f"table_metric_value:{row_metric}")
                        if company:
                            dims.add(f"table_metric_value:{company}:{row_metric}")
                            for mapped_period in mapped_periods:
                                dims.add(
                                    f"table_metric_value:{company}:{mapped_period}:{row_metric}"
                                )
                            requested_table_period = filters.get("period")
                            if requested_table_period and matches_filter(
                                content,
                                item.metadata,
                                "period",
                                requested_table_period,
                            ):
                                dims.add(
                                    f"table_metric_value:{company}:{requested_table_period}:{row_metric}"
                                )
                            for annual_period in annual_periods:
                                dims.add(
                                    f"table_metric_value:{company}:{annual_period}:{row_metric}"
                                )
                            if expected_company_period and matches_filter(
                                content,
                                item.metadata,
                                "period",
                                expected_company_period,
                            ):
                                dims.add(
                                    f"table_metric_value:{company}:{expected_company_period}:{row_metric}"
                                )
                        if row_metric == "operating_cash_flow":
                            # This is the authoritative numeric row even
                            # when the broader metric metadata is absent.
                            dims.add("metric_value")
                            if company:
                                dims.add(f"metric_value:{company}")
                # Some 10-Q parsers keep the statement heading in the chunk,
                # then label the EPS values simply "Basic" / "Diluted".
                # Interpret those rows as EPS only when their local table text
                # explicitly says earnings per share.
                eps_statement_row = bool(
                    re.search(
                        r"\bverified statement group:\s*earnings\s+per\s+share\b",
                        content,
                        re.IGNORECASE,
                    )
                    and not re.search(r"\bshares used in computing\b", content, re.IGNORECASE)
                )
                if eps_statement_row:
                    if any(
                        re.search(r"\b(?:metric\s*:\s*)?diluted\b", row, re.IGNORECASE)
                        and extract_normalized_numbers(row)
                        for row in content.splitlines()
                    ):
                        dims.add("table_metric_value:eps")
                        if company:
                            dims.add(f"table_metric_value:{company}:eps")
                            for mapped_period in mapped_periods:
                                dims.add(
                                    f"table_metric_value:{company}:{mapped_period}:eps"
                                )
                            requested_table_period = filters.get("period")
                            if requested_table_period and matches_filter(
                                content,
                                item.metadata,
                                "period",
                                requested_table_period,
                            ):
                                dims.add(
                                    f"table_metric_value:{company}:{requested_table_period}:eps"
                                )
                            if expected_company_period and matches_filter(
                                content,
                                item.metadata,
                                "period",
                                expected_company_period,
                            ):
                                dims.add(
                                    f"table_metric_value:{company}:{expected_company_period}:eps"
                                )
                for segment_metric in (
                    _SEGMENT_REVENUE_METRICS
                    & set(canonical_metrics(f"{table_context}\n{content}"))
                ):
                    dims.add(f"table_metric_value:{segment_metric}")
                    if company:
                        dims.add(f"table_metric_value:{company}:{segment_metric}")
                        if expected_company_period and matches_filter(
                            content,
                            item.metadata,
                            "period",
                            expected_company_period,
                        ):
                            dims.add(
                                f"table_metric_value:{company}:{expected_company_period}:{segment_metric}"
                            )
            if extract_normalized_numbers(content):
                for segment_metric in (
                    set(requested_segment_metrics) & set(canonical_metrics(content))
                ):
                    dims.add(f"requested_segment_metric:{segment_metric}")
                    if company:
                        dims.add(f"requested_segment_metric:{company}:{segment_metric}")
            if requested_segment_metrics and _has_growth_driver_evidence(item):
                for segment_metric in (
                    set(requested_segment_metrics) & set(canonical_metrics(content))
                ):
                    if company:
                        dims.add(f"segment_driver_evidence:{company}:{segment_metric}")
                        if expected_company_period and matches_filter(
                            content,
                            item.metadata,
                            "period",
                            expected_company_period,
                        ):
                            dims.add(
                                f"segment_driver_evidence:{company}:{expected_company_period}:{segment_metric}"
                            )
                    else:
                        dims.add(f"segment_driver_evidence:{segment_metric}")
            if item.metadata.get("section"):
                dims.add("section")
            segment_section = _segment_section(item) if segment_question else None
            if segment_section is not None:
                section_company = company or "unknown-company"
                dims.add("segment_value")
                dims.add(f"segment_section:{section_company}:{segment_section}")
            if driver_question and _has_growth_driver_evidence(item):
                dims.add("driver_evidence")
                if company:
                    dims.add(f"driver_evidence:{company}")
            if growth_narrative_question and _has_growth_narrative_evidence(item):
                dims.add("growth_narrative_evidence")
                if company:
                    dims.add(f"growth_narrative_evidence:{company}")
                if (
                    has_explicit_financial_growth_driver_evidence(item.content or "")
                    or _AI_GROWTH_DRIVER_NARRATIVE.search(item.content or "")
                ):
                    dims.add("growth_narrative_driver_evidence")
                    if company:
                        dims.add(f"growth_narrative_driver_evidence:{company}")
            if broad_summary_question and _has_financial_summary_evidence(item):
                dims.add("summary_highlight_evidence")
                if company:
                    dims.add(f"summary_highlight_evidence:{company}")
            if broad_summary_question and _has_growth_driver_evidence(item):
                dims.add("summary_driver_evidence")
                if company:
                    dims.add(f"summary_driver_evidence:{company}")
            if risk_question and _has_specific_risk_evidence(item):
                dims.add("risk_evidence")
                if company:
                    dims.add(f"risk_evidence:{company}")
            if risk_factor_question and _has_risk_factor_evidence(item):
                dims.add("risk_factor_evidence")
                if company:
                    dims.add(f"risk_factor_evidence:{company}")
            if constraint_question and _has_constraint_evidence(item):
                dims.add("constraint_evidence")
                if company:
                    dims.add(f"constraint_evidence:{company}")
            if (
                filters.get("period")
                and "period" in dims
                and HybridRetriever._source_authority(item) == "public_filing"
            ):
                dims.add("authoritative_period")
            return dims

        scored: list[tuple[float, int, SearchResult, set[str]]] = []
        for index, item in enumerate(results):
            requested_period = filters.get("period")
            explicit_period_conflict = requested_period and has_explicit_period_conflict(
                item.content or "",
                item.metadata,
                requested_period,
            )
            if explicit_period_conflict:
                # Qualitative risk disclosures describe the filing, not the
                # incidental guidance period named inside a safe-harbor
                # paragraph. For example, NVIDIA's Q1 FY2027 filing's risk
                # section mentions its Q2 FY2027 outlook. Keep that passage
                # only when the independently extracted document period
                # matches the requested filing period; never infer this from
                # the filename or from the passage's outlook period.
                filing_scoped_risk_matches = (
                    risk_question
                    and _has_specific_risk_evidence(item)
                    and matches_filter(
                        "",
                        {"quarter": item.metadata.get("quarter")},
                        "period",
                        requested_period,
                    )
                )
                if not filing_scoped_risk_matches:
                    # A single explicit period in a financial fact chunk is
                    # a claim-level constraint. Do not let an adjacent-quarter
                    # value occupy the final context because its parent filing
                    # metadata happens to match the requested period.
                    continue
            if (risk_question or query_scope == QueryScope.COMPARE) and expected_companies:
                item_company = str(item.metadata.get("company", "")).strip()
                known_companies = {
                    name.casefold() for name in extract_companies(item_company)
                } if item_company else set()
                if known_companies and not (known_companies & expected_companies):
                    # A resolved issuer mismatch is contradictory evidence for
                    # an explicit company comparison. Unknown or incomplete
                    # company metadata stays eligible; only known third-party
                    # facts are excluded from this question's final context.
                    continue
            dims = dimensions(item)
            # Vector-only fallback candidates may expose a distance score
            # (lower is better), while fused candidates expose relevance
            # (higher is better). Normalize before the shared reranker so
            # taking the unified path does not invert vector ranking.
            score = HybridRetriever._vector_relevance(item)
            if score is None:
                # Legacy stores with no score semantics are already ordered
                # best-first, but scores across tenant scopes are not
                # comparable. Use a stable tie baseline rather than letting
                # raw cross-scope values reorder that established ordering.
                score = float(item.score) if has_comparable_vector_scores else 0.0
            if query_terms:
                content_terms = {
                    token.casefold()
                    for token in re.findall(
                        r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u3400-\u9fff]{2,}",
                        item.content or "",
                    )
                }
                overlap = len(query_terms & content_terms)
                score += min(0.02, 0.005 * overlap)
            score += 0.02 * len(dims & {"company", "period", "year", "quarter", "metric"})
            score += 0.01 * len(dims & {"table", "section"})
            table_context = str(item.metadata.get("table_context", "") or "")
            if broad_compare_question and "financial summary" in table_context.casefold():
                # Prefer the filing's explicitly period-mapped summary row
                # over a later reconciliation table when a broad comparison
                # asks for the same issuer/period fact.
                score += 0.08
            if growth_narrative_question:
                if _has_growth_driver_evidence(item):
                    score += 0.05
                elif _has_financial_summary_evidence(item):
                    score += 0.03
            if "quarter_table" in dims:
                # For an unqualified "latest quarter" summary, prefer the
                # three-month column over a six-month roll-up when both are
                # present in the filing.
                score += 0.08
            if "authoritative_period" in dims:
                score += 0.06
            elif filters.get("period") and HybridRetriever._source_authority(item) == "tenant_upload":
                score -= 0.015
            if any(dimension.startswith("company_period:") for dimension in dims):
                # In a multi-company comparison each issuer can have a
                # different requested quarter. Reward the matching column
                # without treating filenames or document-level quarters as
                # authoritative period evidence.
                score += 0.06
            if risk_question:
                if _has_specific_risk_evidence(item):
                    score += 0.06
                elif _FORWARD_LOOKING_BOILERPLATE.search(item.content or ""):
                    # A safe-harbor heading is not a concrete risk factor.
                    # Keep it eligible, but let explicit limitations and risk
                    # disclosures win the small risk-intent ranking tie.
                    score -= 0.06
            scored.append((score, index, item, dims))
        scored.sort(key=lambda row: (-row[0], row[1], row[2].chunk_id))
        detailed_statement_companies = {
            str(row[2].metadata.get("company", "")).casefold()
            for row in scored
            if _has_detailed_income_statement(row[2])
            and (not expected_companies or str(row[2].metadata.get("company", "")).casefold() in expected_companies)
        }
        if broad_summary_question:
            summary_metric_ids = {
                "revenue",
                "net_income",
                "gross_profit",
                "gross_margin",
                "eps",
                "operating_cash_flow",
                "free_cash_flow",
            }
            for expected_company in expected_companies:
                has_verified_compact_highlight = any(
                    f"summary_highlight_evidence:{expected_company}" in item_dimensions
                    and str(item.metadata.get("content_type", "")).casefold()
                    != "unverified_table"
                    and sum(
                        number.kind in {"percent", "basis_points"}
                        for number in extract_normalized_numbers(item.content or "")
                    )
                    >= 2
                    and (
                        not filters.get("period")
                        or matches_filter(
                            item.content or "",
                            item.metadata,
                            "period",
                            filters["period"],
                        )
                    )
                    for _, _, item, item_dimensions in scored
                )
                if has_verified_compact_highlight:
                    # A single verified highlight can carry several reported
                    # growth rates together with the headline metric. Prefer
                    # that compact evidence over assembling separate rows;
                    # when no such highlight exists, reserve the complete
                    # period-mapped statement set rather than unverified table
                    # fragments or unrelated prose.
                    continue
                requested_summary_period = filters.get("period")
                mapped_summary_metrics = {
                    metric_id
                    for _, _, _, item_dimensions in scored
                    for metric_id in summary_metric_ids
                    if any(
                        (
                            dimension.startswith(
                                f"table_metric_value:{expected_company}:{requested_summary_period}:"
                            )
                            if requested_summary_period
                            else dimension.startswith(
                                f"table_metric_value:{expected_company}:"
                            )
                        )
                        and dimension.endswith(f":{metric_id}")
                        for dimension in item_dimensions
                    )
                }
                if {"revenue", "net_income", "gross_profit", "eps"} <= mapped_summary_metrics:
                    # Some 10-Q PDFs expose verified statement rows separately
                    # without keeping the statement title in each chunk.
                    # Multiple metric rows with explicit table provenance are
                    # sufficient to use the detailed-summary coverage plan.
                    detailed_statement_companies.add(expected_company)
        if risk_question:
            substantive_risk_rows = [
                row for row in scored if "risk_evidence" in row[3]
            ]
            # Do not pad a financial-risk answer with cover pages, statement
            # rows, routine deal conditions, or generic safe-harbor text. If
            # no concrete risk disclosure is available, return no evidence so
            # the answer policy can state that the requested disclosure was
            # not found instead of improvising from unrelated prose.
            scored = substantive_risk_rows
        elif driver_question:
            substantive_driver_rows = [
                row for row in scored if "driver_evidence" in row[3]
            ]
            # Filing covers and generic statement rows can score highly for a
            # company/period query while saying nothing about the requested
            # business drivers. Once the report contains verified driver
            # commentary, keep the final context focused on that evidence.
            if substantive_driver_rows:
                requested_segment_rows = [
                    row
                    for row in scored
                    if any(
                        f"requested_segment_metric:{company}:{metric_id}" in row[3]
                        for company in expected_companies
                        for metric_id in requested_segment_metrics
                    )
                    or (
                        not expected_companies
                        and any(
                            f"requested_segment_metric:{metric_id}" in row[3]
                            for metric_id in requested_segment_metrics
                        )
                    )
                ]
                retained_keys = {
                    HybridRetriever._result_key(row[2])
                    for row in (*substantive_driver_rows, *requested_segment_rows)
                }
                scored = [
                    row for row in scored
                    if HybridRetriever._result_key(row[2]) in retained_keys
                ]

        # For cash-flow questions, a narrative line can contain the metric
        # phrase without the numeric row.  Select a metric-bearing value
        # before the generic company slot in that case.
        required: list[str] = []
        metric = filters.get("metric")
        if query_scope == QueryScope.FACT and requested_segment_metrics:
            if expected_companies:
                required.extend(
                    f"table_metric_value:{company}:{metric_id}"
                    for metric_id in requested_segment_metrics
                    for company in sorted(expected_companies)
                )
            else:
                required.extend(
                    f"table_metric_value:{metric_id}"
                    for metric_id in requested_segment_metrics
                )
        if risk_question:
            requested_risk_dimensions = []
            if risk_factor_question:
                requested_risk_dimensions.append("risk_factor_evidence")
            if constraint_question:
                requested_risk_dimensions.append("constraint_evidence")
            if not requested_risk_dimensions:
                requested_risk_dimensions.append("risk_evidence")
            if expected_companies:
                for dimension in requested_risk_dimensions:
                    required.extend(
                        f"{dimension}:{company}"
                        for company in sorted(expected_companies)
                    )
            else:
                required.extend(requested_risk_dimensions)
        elif segment_question:
            # Do not spend the limited context slots on consolidated income
            # statement rows when the user explicitly asks for segment
            # coverage. Reserve one numeric revenue/profit-bearing chunk per
            # distinct structured section, then let the semantic ranking fill
            # any remaining slots.
            if expected_companies:
                required.extend(f"company:{company}" for company in sorted(expected_companies))
            segment_dimensions = []
            for _, _, _, dims in scored:
                segment_dimension = next(
                    (dimension for dimension in sorted(dims) if dimension.startswith("segment_section:")),
                    None,
                )
                if segment_dimension and segment_dimension not in segment_dimensions:
                    segment_dimensions.append(segment_dimension)
            required.extend(segment_dimensions[: max(0, top_k - len(required))])
        elif driver_question:
            # A known issuer's actual management commentary is more useful
            # than generic issuer-matching boilerplate. Reserve substantive
            # growth-driver evidence first, separately for each requested
            # company; then use the generic evidence slot as a fallback for
            # older chunks whose company metadata is missing.
            if expected_companies:
                required.extend(
                    f"requested_segment_metric:{company}:{metric_id}"
                    for metric_id in requested_segment_metrics
                    for company in sorted(expected_companies)
                )
            if expected_companies:
                required.extend(
                    f"driver_evidence:{company}"
                    for company in sorted(expected_companies)
                )
            required.append("driver_evidence")
        elif len(query_metric_ids) > 1:
            if expected_companies:
                required.extend(
                    f"table_metric_value:{company}:{metric_id}"
                    for metric_id in query_metric_ids
                    for company in sorted(expected_companies)
                )
            else:
                required.extend(
                    f"table_metric_value:{metric_id}"
                    for metric_id in query_metric_ids
                )
        elif (
            query_scope == QueryScope.FACT
            and len(query_metric_ids) == 1
            and not requested_segment_metrics
            and not segment_question
        ):
            # A single issuer-level metric question still needs a bound
            # statement row before a generic same-company hit. Otherwise a
            # region/product row can consume the entire one-result budget.
            metric_id = query_metric_ids[0]
            required.extend(
                f"table_metric_value:{company}:{metric_id}"
                for company in sorted(expected_companies)
            )
        elif query_scope in {QueryScope.COMPARE, QueryScope.SUMMARY}:
            if broad_summary_question and not detailed_statement_companies:
                if expected_companies:
                    required.extend(
                        f"summary_highlight_evidence:{company}"
                        for company in sorted(expected_companies)
                    )
                required.append("summary_highlight_evidence")
                if expected_companies:
                    required.extend(
                        f"summary_driver_evidence:{company}"
                        for company in sorted(expected_companies)
                    )
                required.append("summary_driver_evidence")
            if expected_companies:
                if growth_narrative_question:
                    # Reserve one reported growth passage per issuer before
                    # optional comparison metrics. Without this coverage slot
                    # a high-scoring statement row from the first issuer can
                    # crowd out another issuer's narrative evidence.
                    required.extend(
                        f"growth_narrative_driver_evidence:{company}"
                        for company in sorted(expected_companies)
                    )
                    required.extend(
                        f"growth_narrative_evidence:{company}"
                        for company in sorted(expected_companies)
                    )
                    required.extend(
                        ("growth_narrative_driver_evidence", "growth_narrative_evidence")
                    )
                broad_compare = query_scope == QueryScope.COMPARE and any(
                    marker in question.casefold()
                    for marker in (
                        "financial performance",
                        "key metrics",
                        "财务表现",
                        "主要指标",
                        "growth narrative",
                        "growth momentum",
                        "增长势头",
                        "增长叙事",
                    )
                ) or (
                    query_scope == QueryScope.COMPARE
                    and "relevant prior user request for reference resolution:" in question.casefold()
                    and re.search(
                        r"\b(?:analy[sz]e|review|summari[sz]e)\b.{0,100}\b(?:report|filing|financial)\b"
                        r"|分析.{0,24}(?:财报|报告)|报告分析",
                        question,
                        re.IGNORECASE,
                    ) is not None
                )
                metrics = (
                    query_metric_ids
                    or (
                        (
                            "revenue",
                            "net_income",
                            "gross_profit"
                            if any("table_metric_value:gross_profit" in row[3] for row in scored)
                            else "gross_margin",
                            "eps",
                        )
                        if broad_summary_question and detailed_statement_companies
                        else ("revenue", "net_income", "operating_cash_flow")
                    )
                    if query_scope == QueryScope.SUMMARY
                    else (
                        (
                            *_BROAD_COMPARISON_METRICS,
                        )
                        if broad_compare
                        else ("revenue",)
                    )
                )
                if broad_compare:
                    # A broad comparison has a fixed context budget. Prioritize
                    # the same core metric across all issuers before filling
                    # optional statement metrics, so the first company cannot
                    # consume the entire budget ahead of the second company's
                    # margin evidence.
                    for metric_id in metrics:
                        for company in sorted(expected_companies):
                            expected_period = expected_company_periods.get(company)
                            if expected_period:
                                required.append(
                                    f"table_metric_value:{company}:{expected_period}:{metric_id}"
                                )
                            elif not extract_periods(question):
                                available_annual_periods = sorted(
                                    {
                                        dimension.rsplit(":", maxsplit=1)[-1]
                                        for _, _, _, item_dimensions in scored
                                        for dimension in item_dimensions
                                        if dimension.startswith(f"annual_period:{company}:")
                                    }
                                )
                                annual_metric_slot = (
                                    f"table_metric_value:{company}:{available_annual_periods[-1]}:{metric_id}"
                                    if available_annual_periods
                                    else ""
                                )
                                if annual_metric_slot and any(
                                    annual_metric_slot in item_dimensions
                                    for _, _, _, item_dimensions in scored
                                ):
                                    # For an unqualified performance
                                    # comparison, prefer a filing's explicit
                                    # latest annual column when it exists.
                                    # Quarterly-only filings continue to use
                                    # their ranked quarterly summary evidence.
                                    required.append(annual_metric_slot)
                                else:
                                    required.append(
                                        f"table_metric_value:{company}:{metric_id}"
                                    )
                            else:
                                required.append(
                                    f"table_metric_value:{company}:{metric_id}"
                                )
                else:
                    for company in sorted(expected_companies):
                        expected_period = expected_company_periods.get(company)
                        if (
                            expected_period is None
                            and broad_summary_question
                            and filters.get("period")
                        ):
                            expected_period = filters["period"]
                        if expected_period:
                            for metric_id in metrics:
                                exact_dimension = (
                                    f"table_metric_value:{company}:{expected_period}:{metric_id}"
                                )
                                if any(
                                    exact_dimension in item_dimensions
                                    for _, _, _, item_dimensions in scored
                                ):
                                    required.append(exact_dimension)
                                else:
                                    required.append(
                                        f"table_metric_value:{company}:{metric_id}"
                                    )
                        else:
                            required.extend(
                                f"table_metric_value:{company}:{metric_id}"
                                for metric_id in metrics
                            )
                if broad_summary_question and detailed_statement_companies:
                    # In 10-Q-style layouts the headline figures are spread
                    # across adjacent rows. Reserve those rows before spending
                    # the small context budget on narrative/highlights.
                    required.extend(
                        f"summary_highlight_evidence:{company}"
                        for company in sorted(detailed_statement_companies)
                    )
                    required.append("summary_highlight_evidence")
            else:
                required.append("table_metric_value")
        if requested_segment_metrics and not driver_question:
            # For a segment-performance question, preserve one period-matched
            # causal MD&A passage alongside its numeric table row when the
            # filing provides one. This prevents dense statement rows or
            # boilerplate from crowding out the explanation the user asked
            # for, while still avoiding cross-period and cross-company picks.
            for company in sorted(expected_companies):
                expected_period = expected_company_periods.get(company)
                for metric_id in sorted(requested_segment_metrics):
                    exact = (
                        f"segment_driver_evidence:{company}:{expected_period}:{metric_id}"
                        if expected_period
                        else ""
                    )
                    if exact and any(exact in item_dimensions for _, _, _, item_dimensions in scored):
                        required.append(exact)
                    else:
                        required.append(f"segment_driver_evidence:{company}:{metric_id}")
            if not expected_companies:
                required.extend(
                    f"segment_driver_evidence:{metric_id}"
                    for metric_id in sorted(requested_segment_metrics)
                )
        # Bind metric-value selection to an explicit company before choosing
        # a generic metric slot.  Otherwise an Apple cash-flow question can
        # reserve a high-ranked NVIDIA row simply because both rows mention
        # the same metric.
        if not risk_question:
            required.extend(f"company:{name}" for name in sorted(expected_companies))
        if metric in {"cash_flow", "operating_cash_flow"}:
            if expected_companies:
                required.extend(f"metric_value:{name}" for name in sorted(expected_companies))
            else:
                required.append("metric_value")
            required.append("metric")
        required.extend(key for key in filters if key != "metric")
        if metric and metric not in {"cash_flow", "operating_cash_flow"}:
            required.extend(("metric_value", "metric"))
        # For a company-period query, an exact issuer/period candidate must be
        # reserved before broader company or metric slots. Otherwise the first
        # same-company hit (often outlook language from an adjacent quarter)
        # can consume the final top-k slot before the matching table row.
        available_dimensions = {
            dimension
            for _, _, _, dimensions_for_item in scored
            for dimension in dimensions_for_item
        }
        company_period_slots = [
            dimension
            for company, period in sorted(expected_company_periods.items())
            if (dimension := f"company_period:{company}:{period}")
            in available_dimensions
        ]
        prioritize_period = period_metric_scope
        if prioritize_period and filters.get("period") and not company_period_slots and expected_companies:
            # A single explicit (or conversation-inherited) issuer/period
            # request must reserve the matching period before generic issuer
            # and metric coverage slots can consume a small top-k budget.
            company_period_slots = ["period"]
        if prioritize_period:
            # When the user asks for a specific metric, a same-company,
            # same-period row for a different metric is not useful coverage.
            # Reserve exact metric rows before the generic period/company
            # slots, which can otherwise consume the small final context with
            # a cash-flow or revenue row and truncate the requested margin,
            # EPS, or income row.
            period_metric_slots = []
            requested_period_metrics = tuple(
                dict.fromkeys(
                    query_metric_ids
                    or ((metric,) if metric else ())
                )
            )
            for expected_company in sorted(expected_companies):
                expected_period = expected_company_periods.get(expected_company)
                if not expected_period:
                    continue
                period_metric_slots.extend(
                    dimension
                    for metric_id in requested_period_metrics
                    if (
                        dimension := f"table_metric_value:{expected_company}:{expected_period}:{metric_id}"
                    )
                    in available_dimensions
                )
            required = period_metric_slots + company_period_slots + required
        selected: list[tuple[float, int, SearchResult, set[str]]] = []
        selected_keys: set[tuple[str, str]] = set()
        for dimension in required:
            match = next(
                (
                    row
                    for row in scored
                    if dimension in row[3]
                    and HybridRetriever._result_key(row[2]) not in selected_keys
                ),
                None,
            )
            if match is not None:
                selected.append(match)
                selected_keys.add(HybridRetriever._result_key(match[2]))
        for row in scored:
            key = HybridRetriever._result_key(row[2])
            if key in selected_keys:
                continue
            selected.append(row)
            selected_keys.add(key)
            if len(selected) >= top_k:
                break
        return [row[2] for row in selected[:top_k]]

    @staticmethod
    def _merge_ranked_results(
        primary: List[SearchResult],
        secondary: List[SearchResult],
        top_k: int,
    ) -> List[SearchResult]:
        """Merge tenant and public results without duplicate chunks."""
        return HybridRetriever._deduplicate([*primary, *secondary])[:top_k]

    def _load_lexical_corpus(
        self,
        *,
        store: EmbeddingStore,
        tenant_scopes: list[int],
        doc_filter: Dict,
        meta_filter: Dict,
    ) -> list[SearchResult] | None:
        corpus_loader = getattr(store, "lexical_corpus", None)
        if not callable(corpus_loader):
            return None

        corpus: list[SearchResult] = []
        try:
            for tenant_id in tenant_scopes:
                scoped_documents = corpus_loader(tenant_id=tenant_id)
                scoped_documents = self._apply_tenant_scope(
                    scoped_documents,
                    tenant_id,
                )
                corpus.extend(
                    self._apply_filters(
                        scoped_documents,
                        doc_filter,
                        meta_filter,
                    )
                )
        except Exception:
            logger.warning(
                "Lexical corpus unavailable; using vector-only retrieval",
                exc_info=True,
            )
            return None

        return self._deduplicate(
            sorted(
                corpus,
                key=lambda item: (item.document_id, item.chunk_id),
            )
        )

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[SearchResult],
        lexical_results: list[SearchResult],
        *,
        top_k: int,
        lexical_weight: float | None = None,
    ) -> list[SearchResult]:
        effective_lexical_weight = (
            self.config.lexical_weight
            if lexical_weight is None
            else lexical_weight
        )
        records: dict[tuple[str, str], SearchResult] = {}
        fused_scores: dict[tuple[str, str], float] = {}
        vector_ranks: dict[tuple[str, str], int] = {}
        lexical_ranks: dict[tuple[str, str], int] = {}

        for rank, result in enumerate(vector_results, start=1):
            key = self._result_key(result)
            records.setdefault(key, result)
            vector_ranks.setdefault(key, rank)
            fused_scores[key] = fused_scores.get(key, 0.0) + (
                self.config.vector_weight / (self.config.rrf_k + rank)
            )

        for rank, result in enumerate(lexical_results, start=1):
            key = self._result_key(result)
            records.setdefault(key, result)
            lexical_ranks.setdefault(key, rank)
            fused_scores[key] = fused_scores.get(key, 0.0) + (
                effective_lexical_weight / (self.config.rrf_k + rank)
            )

        missing_rank = len(records) + 1
        ordered_keys = sorted(
            records,
            key=lambda key: (
                -fused_scores[key],
                vector_ranks.get(key, missing_rank),
                lexical_ranks.get(key, missing_rank),
                key,
            ),
        )
        maximum_score = (
            self.config.vector_weight + effective_lexical_weight
        ) / (self.config.rrf_k + 1)
        lexical_by_key = {
            self._result_key(result): result
            for result in lexical_results
        }

        fused: list[SearchResult] = []
        for key in ordered_keys[:top_k]:
            result = records[key]
            metadata = dict(result.metadata)
            lexical_result = lexical_by_key.get(key)
            metadata.update(
                {
                    "retrieval_strategy": "hybrid_rrf",
                    "score_semantics": "relevance",
                    "rrf_score": fused_scores[key],
                    "vector_rank": vector_ranks.get(key),
                    "bm25_rank": lexical_ranks.get(key),
                    "bm25_score": (
                        lexical_result.metadata.get("bm25_score")
                        if lexical_result is not None
                        else None
                    ),
                    "lexical_weight": effective_lexical_weight,
                }
            )
            fused.append(
                SearchResult(
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                    score=round(fused_scores[key] / maximum_score, 6),
                    content=result.content,
                    metadata=metadata,
                )
            )
        return fused

    @staticmethod
    def _result_key(result: SearchResult) -> tuple[str, str]:
        normalized_content = re.sub(
            r"\s+",
            " ",
            unicodedata.normalize("NFKC", result.content),
        ).strip().casefold()
        return (
            result.document_id,
            normalized_content or result.chunk_id,
        )

    @staticmethod
    def _deduplicate(results: List[SearchResult]) -> List[SearchResult]:
        deduplicated: List[SearchResult] = []
        seen: set[tuple[str, str]] = set()
        for result in results:
            key = HybridRetriever._result_key(result)
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(result)
        return deduplicated

    @staticmethod
    def _globally_rank_vector_results(
        results: List[SearchResult],
    ) -> List[SearchResult]:
        """Merge private/public candidates using explicit score semantics.

        Chroma returns each tenant scope in best-first distance order. Merely
        concatenating those lists permanently favored the private scope even
        when a public candidate was substantially closer. Explicit distance,
        similarity, and relevance scores are converted to one relevance
        direction. Legacy results without score semantics keep their original
        stable ordering because their numeric direction is unknowable.
        """

        ranked: list[tuple[int, SearchResult, float | None]] = [
            (
                index,
                result,
                HybridRetriever._vector_relevance(result),
            )
            for index, result in enumerate(results)
        ]
        if not any(relevance is not None for _, _, relevance in ranked):
            return list(results)

        ranked.sort(
            key=lambda item: (
                item[2] is None,
                -(item[2] if item[2] is not None else 0.0),
                item[0],
            )
        )
        return [result for _, result, _ in ranked]

    @staticmethod
    def _vector_relevance(result: SearchResult) -> float | None:
        for field in ("similarity_score", "confidence"):
            value = result.metadata.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)

        semantics = result.metadata.get("score_semantics")
        score = float(result.score)
        if semantics == "distance":
            return 1.0 / (1.0 + max(score, 0.0))
        if semantics in {"similarity", "relevance"}:
            return score
        return None

    @staticmethod
    def _source_authority(result: SearchResult) -> str:
        authority = str(result.metadata.get("source_authority", "")).casefold()
        if authority:
            return authority
        # Backward-compatible inference for indexes created before the field
        # was introduced.
        return "public_filing" if result.metadata.get("tenant_id") == 0 else "tenant_upload"

    @staticmethod
    def _apply_tenant_scope(
        results: List[SearchResult],
        tenant_id: int,
    ) -> List[SearchResult]:
        """Reject a result if its explicit tenant metadata crosses scope."""
        scoped: list[SearchResult] = []
        for result in results:
            result_tenant = result.metadata.get("tenant_id")
            if result_tenant is not None and result_tenant != tenant_id:
                continue
            scoped.append(result)
        return scoped

    # =========================
    # V4: Evidence (for Agent pipeline)
    # =========================

    def retrieve_evidence(
        self,
        context: RetrievalContext,
        store: EmbeddingStore,
    ) -> List[Evidence]:
        results = self.retrieve(context, store)

        evidences = []
        for rank, r in enumerate(results):
            local_context = extract_local_context(r.content, context.question)
            evidence_metadata = {
                "rank": rank + 1,
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
            }
            for field in (
                "retrieval_strategy",
                "rrf_score",
                "vector_rank",
                "bm25_rank",
                "bm25_score",
                "page",
                "section",
                "ocr_used",
                "parser_version",
                "chunker_version",
                "embedding_model",
                "embedding_revision",
            "content_sha256",
            "quarter",
            "periods",
            "metrics",
                "table_context",
                "source_locator",
                "page_label",
                "content_type",
                "source_format",
                "filename_company_hint",
                "filename_period_hint",
                "source_authority",
        ):
                value = r.metadata.get(field)
                if value is not None:
                    evidence_metadata[field] = value
            evidences.append(Evidence(
                content=local_context,
                source=r.metadata.get("source", ""),
                company=r.metadata.get("company", context.company or ""),
                confidence=self._evidence_confidence(r),
                metadata=evidence_metadata,
            ))
        return evidences

    @staticmethod
    def _evidence_confidence(result: SearchResult) -> float:
        """Normalize explicit distance/similarity fields to relevance."""
        for field in ("similarity_score", "confidence"):
            value = result.metadata.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return round(min(max(float(value), 0.0), 1.0), 4)

        score = float(result.score)
        semantics = result.metadata.get("score_semantics")
        if semantics == "distance":
            relevance = 1.0 / (1.0 + max(score, 0.0))
        elif semantics in {"relevance", "similarity"}:
            relevance = score
        else:
            # Backward compatibility: historical in-memory stores used score
            # as confidence and did not attach a semantics marker.
            relevance = score
        return round(min(max(relevance, 0.0), 1.0), 4)

    # =========================
    # Internal
    # =========================

    def _get_query_embedding(self, question: str) -> List[float]:
        # A single embedding model is shared across API requests and across
        # the bounded parallel retrieval workers. Model inference is guarded;
        # vector-store requests can still run concurrently after encoding.
        with self._model_lock:
            return embed_query(
                self.model,
                question,
                convert_to_tensor=False,
            ).tolist()

    def _apply_filters(
        self,
        results: List[SearchResult],
        doc_filter: Dict,
        meta_filter: Dict,
    ) -> List[SearchResult]:
        filtered = []

        for r in results:
            if doc_filter["document_ids"]:
                if r.document_id not in doc_filter["document_ids"]:
                    continue

            if meta_filter["company"]:
                if r.metadata.get("company") != meta_filter["company"]:
                    continue

            skip = False
            for k, v in meta_filter["filters"].items():
                if not matches_filter(r.content, r.metadata, k, str(v)):
                    skip = True
                    break
            if skip:
                continue

            filtered.append(r)

        return filtered

    # =========================
    # V3: Legacy (backward compat)
    # =========================

    def retrieve_legacy(
        self,
        chunks,
        embeddings,
        question,
        company=None,
        document_ids=None,
        top_k=4,
    ) -> RetrievalResult:
        from sentence_transformers import util

        filtered_chunks = chunks
        if company:
            filtered_chunks = [
                c for c in filtered_chunks
                if c.get("company") == company
            ]
        if document_ids:
            filtered_chunks = [
                c for c in filtered_chunks
                if c.get("document_id") in document_ids
            ]

        question_embedding = embed_query(
            self.model,
            question,
            convert_to_tensor=True,
        )
        scores = util.cos_sim(question_embedding, embeddings)[0]
        indexes = scores.argsort(descending=True)[:top_k]

        return RetrievalResult(
            top_k=indexes,
            scores=scores,
            chunks=chunks,
            document_ids=[
                filtered_chunks[i].get("document_id", "unknown")
                for i in indexes
                if i < len(filtered_chunks)
            ],
            companies=[company] if company else [],
        )

    def retrieve_evidence_legacy(
        self,
        chunks,
        embeddings,
        question,
        company=None,
        document_ids=None,
        top_k=4,
    ) -> List[Evidence]:
        result = self.retrieve_legacy(
            chunks=chunks,
            embeddings=embeddings,
            question=question,
            company=company,
            document_ids=document_ids,
            top_k=top_k,
        )

        evidences = []
        for rank, idx in enumerate(result.top_k):
            if idx >= len(result.chunks):
                continue
            chunk = result.chunks[idx]
            score = result.scores[idx].item() if idx < len(result.scores) else 0.0
            local_context = extract_local_context(chunk["text"], question)
            evidences.append(Evidence(
                content=local_context,
                source=chunk.get("source", ""),
                company=company or chunk.get("company", ""),
                confidence=round(score, 4),
                metadata={
                    "rank": rank + 1,
                    "chunk_id": chunk.get("chunk_id", ""),
                    "document_id": chunk.get("document_id", "unknown"),
                },
            ))
        return evidences
