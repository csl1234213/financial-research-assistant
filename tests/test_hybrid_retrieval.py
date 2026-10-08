from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from agent.execution_plan import StepType
from agent.planning import PlanningContext
from agent.planning.entity_extractor import extract_companies, prior_user_context_for_followup
from agent.query_planner import QueryPlanner
from agent.reasoning_models import Evidence
from core.fact_ledger import FactLedger
from core.financial_table_rows import FinancialTableRow, VerificationStatus, financial_table_rows_json
from core.required_fact_plan import infer_required_fact_plan
from core.retrieval_tool_adapter import TenantRetrievalToolExecutor
from document_loader import (
    chunk_document,
    get_company,
    get_document_period,
    load_pdf_chunks,
    parse_pdf,
)
from evaluation.metrics import ranked_retrieval_metrics
from retrieval.hybrid_retriever import (
    HybridRetrievalConfig,
    HybridRetriever,
    _verified_statement_metric_periods,
)
from retrieval.periods import extract_metrics, extract_periods
from retrieval.retrieval_context import RetrievalContext
from storage.chroma_store import ChromaEmbeddingStore
from storage.vector_models import SearchResult, VectorDocument


class _Embedding(list):
    def tolist(self):
        return list(self)


def test_chinese_company_revenue_prefers_verified_statement_over_region_row():
    from decimal import Decimal

    statement_row = FinancialTableRow(
        document_id="tenant_7_document_61",
        company="贵州茅台",
        statement_type="income_statement",
        table_title="合并利润表",
        scope="consolidated",
        row_label="其中：营业收入",
        canonical_metric=None,
        column_label="2025 年度",
        fiscal_year=2025,
        period="FY2025",
        value=Decimal("168838102514.79"),
        raw_value="168,838,102,514.79",
        unit="元",
        currency="CNY",
        source="贵州茅台_2025年度报告.pdf",
        source_locator="PDF page 61, table 2, row 3, column 3",
        page=61,
        source_text="其中：营业收入 | 168,838,102,514.79 | 170,899,152,276.34",
        verification_status=VerificationStatus.VERIFIED,
        column_binding_proven=True,
    )
    foreign_region = _result(
        "moutai-2025", "overseas", 0.01,
        "Structured financial table row — Dimension: region; Category: 国外 | "
        "Metric: Revenue | FY2025: 4850142322.68 CNY",
        company="贵州茅台", content_type="mixed",
    )
    consolidated = _result(
        "moutai-2025", "income-statement", 0.90,
        "Financial table row — Metric: 一、营业总收入 | FY2025: 172,054,171,890.91 CNY\n"
        "Financial table row — Metric: 其中：营业收入 | FY2025: 168,838,102,514.79 CNY",
        company="贵州茅台", content_type="table",
        table_context="合并利润表; Scope: consolidated; Unit: 元; Currency: CNY",
        financial_table_rows_json=financial_table_rows_json([statement_row]),
    )
    assert ("revenue", "FY2025") in _verified_statement_metric_periods(consolidated)
    assert not _verified_statement_metric_periods(replace(
        consolidated,
        metadata={
            **consolidated.metadata,
            "financial_table_rows_json": financial_table_rows_json([
                replace(statement_row, verification_status=VerificationStatus.PARTIAL,
                        column_binding_proven=False)
            ]),
        },
    ))
    assert not _verified_statement_metric_periods(replace(
        consolidated,
        metadata={
            **consolidated.metadata,
            "financial_table_rows_json": financial_table_rows_json([
                replace(statement_row, scope="parent")
            ]),
        },
    ))
    store = _HybridStore(
        vectors={7: [foreign_region]},
        corpora={7: [foreign_region, consolidated]},
    )
    assert [item.chunk_id for item in HybridRetriever.coverage_aware_rerank(
        [foreign_region, consolidated],
        "贵州茅台 2025 年报的营业收入是多少？",
        top_k=1,
        company="贵州茅台",
    )] == ["income-statement"]

    result = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="贵州茅台 2025 年报的营业收入是多少？",
            company="贵州茅台", top_k=1, tenant_id=7,
        ),
        store,
    )

    assert [item.chunk_id for item in result] == ["income-statement"]


class _EmbeddingModel:
    def encode(
        self,
        _question,
        convert_to_tensor=False,
        normalize_embeddings=False,
    ):
        del convert_to_tensor, normalize_embeddings
        return _Embedding([0.1, 0.2])


class _HybridStore:
    def __init__(
        self,
        *,
        vectors: dict[int, Sequence[SearchResult]],
        corpora: dict[int, Sequence[SearchResult]],
        lexical_error: bool = False,
    ):
        self.vectors = vectors
        self.corpora = corpora
        self.lexical_error = lexical_error
        self.vector_calls: list[tuple[int | None, int]] = []
        self.lexical_calls: list[int | None] = []

    def similarity_search(self, *, query_embedding, top_k, tenant_id):
        self.vector_calls.append((tenant_id, top_k))
        return list(self.vectors.get(tenant_id, ()))[:top_k]

    def lexical_corpus(self, tenant_id=None):
        self.lexical_calls.append(tenant_id)
        if self.lexical_error:
            raise RuntimeError("lexical index unavailable")
        return list(self.corpora.get(tenant_id, ()))


class _VectorOnlyStore:
    def __init__(self, results: Sequence[SearchResult]):
        self.results = list(results)

    def similarity_search(self, *, query_embedding, top_k, tenant_id):
        return self.results[:top_k]


def _result(
    document_id: str,
    chunk_id: str,
    score: float,
    content: str,
    *,
    tenant_id: int = 7,
    company: str = "Tesla",
    **metadata,
) -> SearchResult:
    return SearchResult(
        document_id=document_id,
        chunk_id=chunk_id,
        score=score,
        content=content,
        metadata={
            "tenant_id": tenant_id,
            "company": company,
            "source": f"{document_id}.pdf",
            **metadata,
        },
    )


def test_hybrid_rrf_combines_vector_and_bm25_ranks():
    generic = _result("generic", "generic-1", 0.01, "General business outlook.")
    revenue = _result(
        "tesla-q2",
        "tesla-revenue",
        0.20,
        "Tesla automotive revenue growth accelerated in the quarter.",
    )
    margins = _result(
        "tesla-q2",
        "tesla-margin",
        0.30,
        "Tesla revenue growth supported automotive margins.",
    )
    store = _HybridStore(
        vectors={7: [generic, revenue, margins]},
        corpora={7: [generic, revenue, margins]},
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Tesla revenue growth accelerated",
            tenant_id=7,
            top_k=3,
        ),
        store,
    )

    assert [result.chunk_id for result in results] == [
        "tesla-revenue",
        "tesla-margin",
        "generic-1",
    ]
    assert results[0].metadata["retrieval_strategy"] == "hybrid_rrf"
    assert results[0].metadata["vector_rank"] == 2
    assert results[0].metadata["bm25_rank"] == 1
    assert store.vector_calls == [(7, 12)]
    assert store.lexical_calls == [7]


def test_auditor_question_adds_targeted_lexical_evidence_queries():
    auditor = _result(
        "moutai-annual-report",
        "auditor-page-2",
        0.2,
        "贵州茅台2025年度财务报表由天健会计师事务所（特殊普通合伙）审计；审计意见为标准无保留意见。",
        company="贵州茅台",
        page=2,
    )
    opinion = _result(
        "moutai-annual-report",
        "opinion-page-53",
        0.99,
        "审计报告认为财务报表在所有重大方面按照企业会计准则编制并公允反映。",
        company="贵州茅台",
        page=53,
    )
    non_unqualified = _result(
        "moutai-annual-report",
        "non-unqualified-page-56",
        1.0,
        "天健会计师事务所可能发表非无保留意见。",
        company="贵州茅台",
        page=56,
    )
    store = _HybridStore(
        vectors={7: [non_unqualified, opinion, auditor]},
        corpora={7: [non_unqualified, opinion, auditor]},
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="贵州茅台2025年度财务报表由哪家会计师事务所审计？审计意见是什么？",
            company="贵州茅台",
            tenant_id=7,
            top_k=3,
        ),
        store,
    )

    assert {result.chunk_id for result in results} == {
        "auditor-page-2", "opinion-page-53", "non-unqualified-page-56"
    }
    assert results[0].chunk_id == "auditor-page-2"
    assert any("特殊普通合伙" in result.content for result in results)


def test_tesla_margin_followup_inherits_period_and_excludes_other_issuers():
    followup = "What did it say about margins?"
    history = [
        {"role": "user", "content": "Tell me about Tesla's Q2 2025 performance."},
        {"role": "assistant", "content": "Apple and NVIDIA also report margins."},
    ]
    prior = prior_user_context_for_followup(followup, history)
    assert prior == ("Tell me about Tesla's Q2 2025 performance.", ["Tesla"])
    resolved = (
        f"{followup}\nRelevant prior user request for reference resolution: {prior[0]}"
    )

    plan, task_result, _ = QueryPlanner().plan(
        PlanningContext(question=resolved, companies=prior[1])
    )
    retrieval_step = next(step for step in plan.tasks if step.step_type is StepType.RETRIEVE)
    assert "Tesla" in task_result.extracted_entities
    assert retrieval_step.company == "Tesla"
    assert retrieval_step.parameters["filters"] == {"period": "Q2_2025"}

    apple = _result(
        "apple-q2-2026", "apple-margin", 0.99,
        "Apple Q2 FY2026 Services gross margin percentage was 76.7%.",
        tenant_id=0, company="Apple", periods="Q2_FY2026", metrics="gross_margin",
        source_authority="public_filing",
    )
    nvidia = _result(
        "nvidia-q1-fy2027", "nvidia-margin", 0.98,
        "NVIDIA Q1 FY2027 gross margin was 74.9%.",
        tenant_id=0, company="NVIDIA", periods="Q1_FY2027", metrics="gross_margin",
        source_authority="public_filing",
    )
    tesla = _result(
        "tesla-fy2025", "tesla-q2-margin", 0.10,
        "Tesla Q2 2025 total gross margin was 17.2%; operating margin was 4.1%.",
        tenant_id=0, company="Tesla",
        periods="Q2_2025",
        metrics="gross_margin", source_authority="public_filing",
    )
    store = _HybridStore(
        vectors={0: [apple, nvidia, tesla]},
        corpora={0: [apple, nvidia, tesla]},
    )
    retrieved = HybridRetriever(_EmbeddingModel()).retrieve_evidence(
        RetrievalContext(
            question=retrieval_step.query,
            company=retrieval_step.company,
            filters=retrieval_step.parameters["filters"],
            tenant_id=7,
            include_public=True,
            top_k=3,
        ),
        store,
    )

    assert [item.metadata["chunk_id"] for item in retrieved] == ["tesla-q2-margin"]
    assert "17.2%" in retrieved[0].content

    from core.answer_policy import finalize_grounded_answer

    english = finalize_grounded_answer(
        "Tell me about Tesla's Q2 2025 performance.\nWhat did it say about margins?",
        "The evidence is from Apple's report; no Tesla margin percentage is available.",
        retrieved,
    )
    chinese = finalize_grounded_answer(
        "介绍一下特斯拉2025年第二季度的表现。\n那它的利润率表现呢？",
        "该证据讨论的是英伟达营收，未提供特斯拉利润率。",
        retrieved,
    )
    assert "17.2%" in english.answer and "4.1%" in english.answer
    assert "17.2%" in chinese.answer and "4.1%" in chinese.answer
    assert "Apple" not in english.answer and "NVIDIA" not in chinese.answer

    def required_signature(result):
        return [
            (row["company"], row["metric_id"], row["period"], row["available"], row["answer_present"])
            for row in result.plan.as_dict(result.ledger, result.answer)["required"]
        ]

    assert required_signature(english) == required_signature(chinese)


def test_evidence_normalizes_explicit_distance_and_similarity_scores():
    distance = _result(
        "distance",
        "distance-1",
        0.25,
        "Distance-based revenue evidence.",
        score_semantics="distance",
    )
    similarity = _result(
        "similarity",
        "similarity-1",
        0.10,
        "Similarity-based revenue evidence.",
        similarity_score=0.91,
    )
    retriever = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(enabled=False),
    )

    distance_evidence = retriever.retrieve_evidence(
        RetrievalContext(question="revenue", tenant_id=7),
        _VectorOnlyStore([distance]),
    )
    similarity_evidence = retriever.retrieve_evidence(
        RetrievalContext(question="revenue", tenant_id=7),
        _VectorOnlyStore([similarity]),
    )

    assert distance_evidence[0].confidence == 0.8
    assert similarity_evidence[0].confidence == 0.91


def test_hybrid_deduplicates_stably_across_channels():
    duplicate = _result(
        "tesla-q2",
        "tesla-revenue",
        0.10,
        "Tesla revenue growth was 20 percent.",
    )
    other = _result(
        "tesla-q2",
        "tesla-cash",
        0.20,
        "Tesla cash flow improved.",
    )
    store = _HybridStore(
        vectors={7: [duplicate, duplicate, other]},
        corpora={7: [duplicate, duplicate, other]},
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Tesla revenue growth",
            tenant_id=7,
            top_k=3,
        ),
        store,
    )

    assert [result.chunk_id for result in results] == [
        "tesla-revenue",
        "tesla-cash",
    ]


def test_hybrid_deduplicates_same_document_normalized_content():
    first = _result(
        "tesla-q2",
        "tesla-revenue-1",
        0.10,
        "Tesla revenue increased year over year.",
    )
    repeated = _result(
        "tesla-q2",
        "tesla-revenue-2",
        0.11,
        "  TESLA   REVENUE increased year over year. ",
    )
    store = _HybridStore(
        vectors={7: [first, repeated]},
        corpora={7: []},
    )

    results = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(enabled=False),
    ).retrieve(
        RetrievalContext(
            question="Tesla revenue",
            tenant_id=7,
            top_k=5,
        ),
        store,
    )

    assert [result.chunk_id for result in results] == [
        "tesla-revenue-1",
    ]


def test_hybrid_applies_tenant_company_document_and_metadata_filters():
    allowed = _result(
        "allowed",
        "allowed-1",
        0.20,
        "Tesla revenue growth in fiscal 2025.",
        year="2025",
    )
    wrong_tenant = _result(
        "foreign",
        "foreign-1",
        0.01,
        "Tesla revenue growth in fiscal 2025.",
        tenant_id=99,
        year="2025",
    )
    wrong_company = _result(
        "apple",
        "apple-1",
        0.02,
        "Apple revenue growth in fiscal 2025.",
        company="Apple",
        year="2025",
    )
    wrong_year = _result(
        "legacy",
        "legacy-1",
        0.03,
        "Tesla revenue growth in fiscal 2024.",
        year="2024",
    )
    candidates = [wrong_tenant, wrong_company, wrong_year, allowed]
    store = _HybridStore(
        vectors={7: candidates},
        corpora={7: candidates},
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Tesla revenue growth",
            tenant_id=7,
            company="Tesla",
            document_ids=["allowed"],
            filters={"year": "2025"},
        ),
        store,
    )

    assert [result.chunk_id for result in results] == ["allowed-1"]
    assert store.vector_calls[0][0] == 7
    assert store.lexical_calls == [7]


def test_hybrid_queries_only_private_and_explicit_public_lexical_scopes():
    private = _result(
        "private",
        "private-1",
        0.10,
        "Tesla revenue growth from private evidence.",
    )
    public = _result(
        "public",
        "public-1",
        0.20,
        "Tesla revenue growth from public evidence.",
        tenant_id=0,
    )
    foreign = _result(
        "foreign",
        "foreign-1",
        0.01,
        "Tesla revenue growth from another tenant.",
        tenant_id=99,
    )
    store = _HybridStore(
        vectors={7: [private], 0: [public], 99: [foreign]},
        corpora={7: [private], 0: [public], 99: [foreign]},
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Tesla revenue growth",
            tenant_id=7,
            include_public=True,
        ),
        store,
    )

    assert {result.chunk_id for result in results} == {"private-1", "public-1"}
    assert [tenant_id for tenant_id, _ in store.vector_calls] == [7, 0]
    assert store.lexical_calls == [7, 0]


def test_vector_candidates_are_globally_ranked_across_private_and_public_scopes():
    private = _result(
        "private",
        "private-unrelated",
        0.95,
        "Unrelated private evidence.",
        score_semantics="distance",
    )
    public = _result(
        "public",
        "public-relevant",
        0.08,
        "Relevant public Tesla revenue evidence.",
        tenant_id=0,
        score_semantics="distance",
    )
    store = _HybridStore(
        vectors={7: [private], 0: [public]},
        corpora={7: [], 0: []},
    )
    retriever = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(enabled=False),
    )

    results = retriever.retrieve(
        RetrievalContext(
            question="特斯拉营收增长",
            tenant_id=7,
            include_public=True,
            top_k=2,
        ),
        store,
    )

    assert [result.chunk_id for result in results] == [
        "public-relevant",
        "private-unrelated",
    ]


def test_vector_global_ranking_stably_normalizes_mixed_score_semantics():
    distance = _result(
        "distance",
        "distance-result",
        0.25,
        "Distance result.",
        score_semantics="distance",
    )
    similarity = _result(
        "similarity",
        "similarity-result",
        0.90,
        "Similarity result.",
        tenant_id=0,
        score_semantics="similarity",
    )
    store = _HybridStore(
        vectors={7: [distance], 0: [similarity]},
        corpora={7: [], 0: []},
    )

    results = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(enabled=False),
    ).retrieve(
        RetrievalContext(
            question="Tesla",
            tenant_id=7,
            include_public=True,
            top_k=2,
        ),
        store,
    )

    assert [result.chunk_id for result in results] == [
        "similarity-result",
        "distance-result",
    ]


def test_missing_lexical_capability_preserves_vector_only_result():
    vector_result = _result(
        "vector",
        "vector-1",
        0.17,
        "Semantic evidence without a lexical provider.",
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(question="revenue", tenant_id=7),
        _VectorOnlyStore([vector_result]),
    )

    assert results == [vector_result]
    assert results[0].score == 0.17
    assert "retrieval_strategy" not in results[0].metadata


def test_lexical_failure_preserves_vector_only_result():
    vector_result = _result(
        "vector",
        "vector-1",
        0.17,
        "Semantic revenue evidence.",
    )
    store = _HybridStore(
        vectors={7: [vector_result]},
        corpora={},
        lexical_error=True,
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(question="revenue", tenant_id=7),
        store,
    )

    assert results == [vector_result]


def test_hybrid_weights_are_configurable():
    vector_first = _result(
        "semantic",
        "semantic-1",
        0.01,
        "General performance discussion.",
    )
    lexical_only = _result(
        "lexical",
        "lexical-1",
        0.20,
        "Rareterm exact identifier match.",
    )
    store = _HybridStore(
        vectors={7: [vector_first]},
        corpora={7: [vector_first, lexical_only]},
    )
    retriever = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(
            vector_weight=2.0,
            lexical_weight=1.0,
        ),
    )

    results = retriever.retrieve(
        RetrievalContext(question="rareterm", tenant_id=7, top_k=2),
        store,
    )

    assert [result.chunk_id for result in results] == [
        "semantic-1",
        "lexical-1",
    ]


def test_hybrid_golden_sample_reports_ranked_retrieval_metrics():
    generic = _result("generic", "generic-1", 0.01, "General outlook.")
    revenue = _result(
        "tesla-q2",
        "gold-revenue",
        0.20,
        "Tesla revenue growth accelerated.",
    )
    margin = _result(
        "tesla-q2",
        "gold-margin",
        0.30,
        "Tesla revenue growth improved margins.",
    )
    store = _HybridStore(
        vectors={7: [generic, revenue, margin]},
        corpora={7: [generic, revenue, margin]},
    )

    results = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Tesla revenue growth",
            tenant_id=7,
            top_k=3,
        ),
        store,
    )
    metrics = ranked_retrieval_metrics(
        [result.chunk_id for result in results],
        ["gold-revenue", "gold-margin"],
        k=3,
    )

    assert metrics == {
        "precision_at_k": 66.7,
        "recall_at_k": 100.0,
        "mrr": 100.0,
        "ndcg": 100.0,
    }


def test_comparison_rerank_reserves_slot_for_authoritative_revenue_table():
    narrative = _result(
        "tesla-update",
        "tesla-narrative",
        0.90,
        "Tesla quarterly revenue decreased 3% YoY to $24.9B.",
    )
    table = _result(
        "tesla-update",
        "tesla-financial-summary",
        0.10,
        "FINANCIAL SUMMARY (Unaudited) Q1-2025 Q2-2025 Total revenues 19,335 22,496",
    )
    nvidia = _result(
        "nvidia-q1",
        "nvidia-revenue",
        0.80,
        "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
    )
    for item, company in ((narrative, "Tesla"), (table, "Tesla"), (nvidia, "NVIDIA")):
        item.metadata["company"] = company

    results = HybridRetriever.coverage_aware_rerank(
        [narrative, nvidia, table],
        "Compare Tesla and NVIDIA revenue performance.",
        top_k=2,
    )

    assert table in results
    assert nvidia in results


def test_bilingual_revenue_comparison_promotes_period_mapped_table_rows():
    """Chinese and English revenue comparisons must share table coverage."""

    tesla_narrative = _result(
        "tesla-q2",
        "tesla-narrative",
        0.01,
        "Tesla quarterly revenue performance and outlook discussion.",
        company="Tesla",
        tenant_id=0,
    )
    tesla_table = _result(
        "tesla_q2_2025",
        "tesla-q2-revenue-table",
        0.90,
        (
            "Structured financial table row | Metric: Total revenues | "
            "Q4-2024: 25,707 | Q1-2025: 19,335 | Q2-2025: 22,496 | Q4-2025: 24,901"
        ),
        company="Tesla",
        tenant_id=0,
        quarter="Q4_2025",
        periods="Q4_2024|Q1_2025|Q2_2025|Q4_2025",
        table_context="Comparative columns: Q4-2024 | Q1-2025 | Q2-2025 | Q4-2025",
        content_type="table",
    )
    nvidia = _result(
        "nvidia_q1_fy2027",
        "nvidia-revenue",
        0.02,
        "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        periods="Q1_FY2027",
        metrics="revenue",
    )
    distractors = [
        _result(
            "tesla-q2",
            f"tesla-distractor-{index}",
            0.01 + index * 0.001,
            f"Tesla quarterly business discussion and outlook note {index}.",
            company="Tesla",
            tenant_id=0,
        )
        for index in range(12)
    ]
    corpus = [tesla_narrative, *distractors, tesla_table, nvidia]
    store = _HybridStore(vectors={0: corpus}, corpora={0: corpus})
    retriever = HybridRetriever(_EmbeddingModel())

    for question in (
        "Compare Tesla and NVIDIA revenue performance.",
        "\u6bd4\u8f83\u7279\u65af\u62c9\u548c\u82f1\u4f1f\u8fbe\u7684\u8425\u6536\u8868\u73b0\u3002",
    ):
        ranked = retriever.retrieve(
            RetrievalContext(question=question, tenant_id=0, top_k=2),
            store,
        )
        assert {item.chunk_id for item in ranked} == {
            "tesla-q2-revenue-table",
            "nvidia-revenue",
        }
        evidence = [
            Evidence(
                content=item.content,
                source=str(item.metadata.get("source", "")),
                company=str(item.metadata.get("company", "")),
                confidence=item.score,
                metadata={**item.metadata, "document_id": item.document_id, "chunk_id": item.chunk_id},
            )
            for item in ranked
        ]
        ledger = FactLedger.from_evidence(evidence)
        plan = infer_required_fact_plan(question, evidence, ledger)
        assert [(spec.company, spec.period) for spec in plan.required] == [
            ("tesla", "Q2_2025"),
            ("nvidia", "Q1_FY2027"),
        ]


def test_segment_summary_retrieval_keeps_distinct_segment_evidence():
    generic = [
        _result(
            "nvidia-q1",
            f"generic-{index}",
            0.99 - index * 0.01,
            f"NVIDIA Q1 FY2027 financial statement discussion {index}.",
            company="NVIDIA",
            tenant_id=0,
            quarter="Q1_FY2027",
        )
        for index in range(4)
    ]
    data_center = _result(
        "nvidia-q1",
        "data-center-segment",
        0.10,
        "Data Center\n\nFirst-quarter revenue was a record $75.2 billion, up 92% from a year ago.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Page 1",
    )
    edge = _result(
        "nvidia-q1",
        "edge-segment",
        0.09,
        "Edge Computing\n\nFirst-quarter Edge Computing revenue was $6.4 billion, up 29% from a year ago.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Page 1",
    )
    corpus = [*generic, data_center, edge]
    store = _HybridStore(vectors={0: generic}, corpora={0: corpus})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Summarize the major business segments discussed in NVIDIA Q1 FY2027.",
            company="NVIDIA",
            top_k=4,
            tenant_id=0,
        ),
        store,
    )

    assert {"data-center-segment", "edge-segment"} <= {
        item.chunk_id for item in ranked
    }


def test_segment_comparison_recovers_product_service_rows_with_generic_pdf_sections():
    """Apple-style disaggregated rows must not be lost to generic section labels."""

    apple_products = _result(
        "apple-q2",
        "apple-products",
        0.01,
        "Structured financial table row | Resolved financial label: Products net sales | "
        "Q2 FY2026: 80,208 million USD",
        company="Apple",
        tenant_id=0,
        quarter="Q2_FY2026",
        section="Three Months Ended Six Months Ended",
    )
    apple_services = _result(
        "apple-q2",
        "apple-services",
        0.01,
        "Structured financial table row | Resolved financial label: Services net sales | "
        "Q2 FY2026: 30,976 million USD",
        company="Apple",
        tenant_id=0,
        quarter="Q2_FY2026",
        section="Three Months Ended Six Months Ended",
    )
    data_center = _result(
        "nvidia-q1",
        "nvidia-data-center",
        0.01,
        "Data Center\n\nFirst-quarter revenue was a record $75.2 billion.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Data Center",
    )
    edge = _result(
        "nvidia-q1",
        "nvidia-edge",
        0.01,
        "Edge Computing\n\nFirst-quarter revenue was $6.4 billion.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Edge Computing",
    )
    generic = _result(
        "nvidia-q1",
        "nvidia-generic",
        0.99,
        "NVIDIA consolidated financial statement discussion.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
    )
    corpus = [generic, apple_products, apple_services, data_center, edge]
    store = _HybridStore(vectors={0: [generic]}, corpora={0: corpus})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="比较苹果和英伟达财报中涉及的主要业务板块。",
            top_k=6,
            tenant_id=0,
        ),
        store,
    )

    assert {"apple-products", "apple-services", "nvidia-data-center", "nvidia-edge"} <= {
        item.chunk_id for item in ranked
    }


def test_growth_driver_retrieval_prefers_reported_commentary_over_safe_harbor():
    boilerplate = _result(
        "nvidia-q1",
        "safe-harbor",
        0.99,
        "Certain statements in this press release include forward-looking statements about growth, trends and drivers, subject to risks and uncertainties.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="About NVIDIA",
    )
    reported_commentary = _result(
        "nvidia-q1",
        "reported-drivers",
        0.10,
        "The buildout of AI factories is accelerating at extraordinary speed. Agentic AI has arrived, generating real value and scaling rapidly across companies and industries.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Page 1",
    )
    statement = _result(
        "nvidia-q1",
        "income-statement",
        0.95,
        "NVIDIA Q1 FY2027 revenue was $81.6 billion.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Three Months Ended",
    )
    corpus = [boilerplate, statement, reported_commentary]
    store = _HybridStore(vectors={0: [boilerplate, statement]}, corpora={0: corpus})

    questions = (
        "What were the main drivers of NVIDIA's growth in Q1 FY2027?",
        "英伟达 2027 财年第一季度增长的主要驱动因素是什么？",
    )
    for question in questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="NVIDIA",
                top_k=3,
                tenant_id=0,
            ),
            store,
        )

        assert "reported-drivers" in {item.chunk_id for item in ranked}


def test_growth_narrative_comparison_reserves_reported_evidence_for_each_company():
    apple = _result(
        "apple-q2",
        "apple-growth",
        0.20,
        "Apple total net sales increased 17% year over year, with Services growth driven by advertising, the App Store, and cloud services.",
        company="Apple",
        tenant_id=0,
    )
    nvidia = _result(
        "nvidia-q1",
        "nvidia-growth",
        0.30,
        "NVIDIA revenue grew 69% year over year, driven by strong Data Center demand and AI factory buildout.",
        company="NVIDIA",
        tenant_id=0,
    )
    tesla = _result(
        "tesla-q2",
        "tesla-growth",
        0.40,
        "Tesla total revenue declined 3% year over year, while energy storage growth provided a positive offset.",
        company="Tesla",
        tenant_id=0,
    )
    # Include a high-scoring generic statement row to prove narrative coverage
    # is not lost to one issuer's semantic match.
    generic = _result(
        "apple-q2",
        "apple-generic",
        0.01,
        "Apple certification and filing information.",
        company="Apple",
        tenant_id=0,
    )
    corpus = [apple, nvidia, tesla, generic]
    store = _HybridStore(vectors={0: corpus}, corpora={0: corpus})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question=(
                "Which of Apple, NVIDIA and Tesla reports the strongest growth "
                "narrative? Support the comparison with sources."
            ),
            tenant_id=0,
            top_k=3,
        ),
        store,
    )

    retrieved = {item.chunk_id for item in ranked}
    assert {"apple-growth", "nvidia-growth", "tesla-growth"} <= retrieved
    assert "apple-generic" not in retrieved


def test_nvidia_growth_driver_followup_retrieves_reported_commentary():
    history = [
        {"role": "user", "content": "Summarize NVIDIA's financial performance."},
        {"role": "assistant", "content": "NVIDIA reported strong quarterly results."},
    ]
    boilerplate = _result(
        "nvidia-q1",
        "safe-harbor",
        0.99,
        "Certain statements include forward-looking statements about growth, trends and drivers, subject to risks and uncertainties.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="About NVIDIA",
    )
    reported_commentary = _result(
        "nvidia-q1",
        "reported-drivers",
        0.10,
        "The buildout of AI factories is accelerating at extraordinary speed. Agentic AI has arrived, generating real value and scaling rapidly across companies and industries.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Page 1",
    )
    apple_driver = _result(
        "apple-q2",
        "apple-driver",
        1.0,
        "Apple growth was driven by higher iPhone sales.",
        company="Apple",
        tenant_id=0,
        quarter="Q2_FY2026",
        section="Management discussion",
    )
    store = _HybridStore(
        vectors={0: [apple_driver, boilerplate]},
        corpora={0: [apple_driver, boilerplate, reported_commentary]},
    )

    for followup in (
        "What was the main growth driver?",
        "它最主要的增长动力是什么？",
    ):
        prior = prior_user_context_for_followup(followup, history)
        assert prior == ("Summarize NVIDIA's financial performance.", ["NVIDIA"])
        resolved = (
            f"{followup}\nRelevant prior user request for reference resolution: {prior[0]}"
        )
        plan, task_result, _ = QueryPlanner().plan(
            PlanningContext(question=resolved, companies=prior[1])
        )
        retrieval_step = next(
            step for step in plan.tasks if step.step_type is StepType.RETRIEVE
        )
        assert retrieval_step.company == "NVIDIA"

        ranked = HybridRetriever(_EmbeddingModel()).retrieve_evidence(
            RetrievalContext(
                question=retrieval_step.query,
                company=retrieval_step.company,
                tenant_id=7,
                include_public=True,
                top_k=3,
            ),
            store,
        )

        assert task_result.task.task_type.value == "document_qa"
        assert [item.metadata["chunk_id"] for item in ranked][0] == "reported-drivers"
        assert all(item.company == "NVIDIA" for item in ranked)


def test_public_apple_retrieve_reserves_reported_growth_driver_commentary():
    path = "demo/documents/Apple_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    document_period = get_document_period(chunks)
    corpus = [
        _result(
            "apple-q2-2026",
            f"apple-sample-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company="Apple",
            tenant_id=7,
            source="Apple_sample.pdf",
            page=chunk.page,
            section=chunk.section,
            quarter=document_period,
            table_context=chunk.table_context or "",
            periods="|".join(
                extract_periods(f"{chunk.table_context or ''}\n{chunk.text}")
            ),
            metrics="|".join(extract_metrics(chunk.text)),
            content_type=chunk.content_type,
            source_authority="tenant_upload",
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="What major business drivers are described in Apple's Q2 FY2026 report?",
            company="Apple",
            top_k=8,
            tenant_id=7,
        ),
        store,
    )
    retrieved_text = "\n".join(item.content for item in ranked)

    assert document_period == "Q2_FY2026"
    assert "Pro models" in retrieved_text
    assert "advertising" in retrieved_text
    assert all(item.metadata["company"] == "Apple" for item in ranked)


def test_public_apple_service_business_retrieval_keeps_verified_revenue_row():
    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    chunks = load_pdf_chunks("demo/documents/Apple_sample.pdf", ocr_enabled=False)
    document_period = get_document_period(chunks)
    corpus = [
        _result(
            "apple-q2-2026",
            f"apple-services-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company="Apple",
            tenant_id=7,
            source="Apple_sample.pdf",
            page=chunk.page,
            section=chunk.section,
            quarter=document_period,
            table_context=chunk.table_context or "",
            periods="|".join(
                extract_periods(f"{chunk.table_context or ''}\n{chunk.text}")
            ),
            metrics="|".join(extract_metrics(chunk.text)),
            content_type=chunk.content_type,
            source_authority="tenant_upload",
        )
        for index, chunk in enumerate(chunks)
    ]
    questions = (
        (
            "How is Apple's service-related business doing?",
            "The evidence does not contain Apple's services business results.",
        ),
        (
            "苹果的服务业务在 2026 年第二季度表现如何？",
            "当前检索到的证据不足以可靠回答该问题。",
        ),
    )
    signatures = []
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})
    for question, raw in questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="Apple",
                top_k=8,
                tenant_id=7,
            ),
            store,
        )
        evidence = [
            Evidence(
                content=item.content,
                source="Apple_sample.pdf",
                company="Apple",
                confidence=item.score,
                metadata={**item.metadata, "chunk_id": item.chunk_id},
            )
            for item in ranked
        ]
        finalized = finalize_grounded_answer(question, raw, evidence)
        assert any(
            "Resolved financial label: Services net sales" in item.content
            and "30,976" in item.content
            for item in ranked
        )
        assert "30.976 billion USD" in finalized.answer
        assert "advertising" in finalized.answer.casefold()
        assert "App Store" in finalized.answer
        assert "cloud services" in finalized.answer.casefold()
        assert "emerging growth company" not in finalized.answer.casefold()
        assert "does not contain" not in finalized.answer.casefold()
        assert "证据不足" not in finalized.answer
        assert finalized.grounded.evidence
        assert finalized.grounded.unsupported_count == 0
        signatures.append(
            (
                "30.976" in finalized.answer,
                "advertising" in finalized.answer.casefold(),
                "App Store" in finalized.answer,
                "cloud services" in finalized.answer.casefold(),
            )
        )

    assert document_period == "Q2_FY2026"
    assert signatures[0] == signatures[1]


def test_risk_comparison_retrieval_reserves_each_companys_risk_evidence():
    apple_risk = _result(
        "apple-q2",
        "apple-risk-factors",
        0.05,
        "Apple's risk factors include new and changing online safety laws, "
        "mandatory age verification requirements, and increased compliance costs.",
        company="Apple",
        tenant_id=7,
        section="Risk Factors",
    )
    tesla_risk = _result(
        "tesla-fy",
        "tesla-risk-factors",
        0.04,
        "Tesla's risk factors include its ability to attract and retain key "
        "employees and to comply with changing regulations and laws.",
        company="Tesla",
        tenant_id=7,
        section="Forward-Looking Statements",
    )
    apple_safe_harbor = _result(
        "apple-q2",
        "apple-safe-harbor",
        0.99,
        "Forward-looking statements are subject to risks and uncertainties "
        "that may cause future results to differ.",
        company="Apple",
        tenant_id=7,
        section="Forward-Looking Statements",
    )
    tesla_boilerplate = _result(
        "tesla-fy",
        "tesla-general-outlook",
        0.98,
        "Tesla's financial results and outlook are discussed in this report.",
        company="Tesla",
        tenant_id=7,
        section="Outlook",
    )
    unrelated_risk = _result(
        "nvidia-q1",
        "nvidia-risk-factors",
        0.97,
        "NVIDIA's risk factors include global economic and political conditions.",
        company="NVIDIA",
        tenant_id=7,
        section="Forward-Looking Statements",
    )
    corpus = [
        apple_safe_harbor,
        tesla_boilerplate,
        unrelated_risk,
        apple_risk,
        tesla_risk,
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Compare the main risks mentioned in Tesla and Apple's reports.",
            top_k=2,
            tenant_id=7,
        ),
        store,
    )

    assert {item.chunk_id for item in ranked} == {
        "apple-risk-factors",
        "tesla-risk-factors",
    }


def test_single_company_risk_retrieval_prefers_concrete_risks_over_safe_harbor():
    safe_harbor = _result(
        "nvidia-q1",
        "generic-safe-harbor",
        0.99,
        "Certain forward-looking statements are subject to risks and uncertainties "
        "that could cause results to differ materially.",
        company="NVIDIA",
        tenant_id=7,
        section="About NVIDIA",
    )
    unrelated_commentary = _result(
        "nvidia-q1",
        "generic-commentary",
        0.98,
        "NVIDIA returned cash to shareholders and discussed product announcements.",
        company="NVIDIA",
        tenant_id=7,
        section="CFO Commentary",
    )
    specific_risks = _result(
        "nvidia-q1",
        "specific-risk-list",
        0.05,
        "Important factors that could cause results to differ include global "
        "economic and political conditions and NVIDIA's reliance on third parties.",
        company="NVIDIA",
        tenant_id=7,
        section="About NVIDIA",
    )
    china_constraint = _result(
        "nvidia-q1",
        "china-guidance-constraint",
        0.04,
        "NVIDIA is not assuming any Data Center compute revenue from China in its outlook.",
        company="NVIDIA",
        tenant_id=7,
        section="Outlook",
    )
    table_of_contents = _result(
        "nvidia-q1",
        "table-of-contents-risk-mentions",
        0.97,
        "Item 1. Financial Statements 1 Item 1A. Risk Factors 20 Item 2. Legal Proceedings 22.",
        company="NVIDIA",
        tenant_id=7,
        section="Table of Contents",
    )
    corpus = [
        safe_harbor,
        unrelated_commentary,
        table_of_contents,
        specific_risks,
        china_constraint,
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="What risks or constraints are mentioned in NVIDIA's report?",
            top_k=4,
            tenant_id=7,
        ),
        store,
    )

    assert {item.chunk_id for item in ranked} == {
        "specific-risk-list",
        "china-guidance-constraint",
    }


def test_risk_comparison_does_not_fill_context_with_a_third_known_company():
    corpus = [
        _result(
            "nvidia-q1",
            f"nvidia-risk-{index}",
            0.99 - index * 0.01,
            "NVIDIA's risk factors include global economic conditions and reliance "
            "on third parties.",
            company="NVIDIA",
            tenant_id=7,
            section="Risk Factors",
        )
        for index in range(2)
    ]
    corpus.extend(
        [
            _result(
                "apple-q2",
                "apple-risk-one",
                0.10,
                "Apple's risk factors include new laws and legal proceedings.",
                company="Apple",
                tenant_id=7,
                section="Risk Factors",
            ),
            _result(
                "apple-q2",
                "apple-risk-two",
                0.09,
                "Apple may face regulatory action and material adverse effects.",
                company="Apple",
                tenant_id=7,
                section="Risk Factors",
            ),
            _result(
                "tesla-fy",
                "tesla-risk-one",
                0.08,
                "Tesla's risk factors include international regulatory and tariff exposure.",
                company="Tesla",
                tenant_id=7,
                section="Forward-Looking Statements",
            ),
            _result(
                "tesla-fy",
                "tesla-risk-two",
                0.07,
                "Tesla's ability to procure battery-cell supply is a material uncertainty.",
                company="Tesla",
                tenant_id=7,
                section="Forward-Looking Statements",
            ),
        ]
    )
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Compare the main risks mentioned in Tesla and Apple's reports.",
            top_k=6,
            tenant_id=7,
        ),
        store,
    )

    assert ranked
    assert {item.metadata["company"] for item in ranked} == {"Apple", "Tesla"}


def test_risk_evidence_classifier_handles_real_filing_wording_variants():
    apple_risk = _result(
        "apple-q2",
        "apple-risk-intro",
        0.05,
        "The Company's business, reputation, results of operations, financial condition and stock price can be materially and adversely affected by a number of factors.",
        company="Apple",
        section="Other Legal Proceedings",
    )
    apple_noise = _result(
        "apple-q2",
        "apple-cover-noise",
        0.99,
        "Apple Inc. Form 10-Q quarterly report cover and registered securities information.",
        company="Apple",
        section="Cover Page",
    )
    tesla_risk = _result(
        "tesla-fy",
        "tesla-risk-intro",
        0.1,
        "Certain statements in this update involve risks and uncertainties. The following important factors, without limitation, could cause actual results to differ materially: the risk of delays in launching products.",
        company="Tesla",
        section="Forward-Looking Statements",
    )
    store = _HybridStore(
        vectors={7: [apple_noise, apple_risk, tesla_risk]},
        corpora={7: [apple_noise, apple_risk, tesla_risk]},
    )

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Compare the risks mentioned in Apple and Tesla's reports.",
            top_k=2,
            tenant_id=7,
        ),
        store,
    )

    assert {item.chunk_id for item in ranked} == {"apple-risk-intro", "tesla-risk-intro"}


def test_risk_query_returns_no_evidence_for_boilerplate_and_routine_conditions():
    boilerplate = _result(
        "tesla-update",
        "forward-looking-boilerplate",
        0.99,
        "Certain statements in this update involve risks and uncertainties and are not guarantees. "
        "This investment is subject to customary regulatory conditions. The Private Securities "
        "Litigation Reform Act of 1995 applies to forward-looking statements.",
        company="Tesla",
        tenant_id=7,
        section="Forward-Looking Statements",
    )
    store = _HybridStore(vectors={7: [boilerplate]}, corpora={7: [boilerplate]})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="What risks does Tesla identify in its report?",
            top_k=3,
            tenant_id=7,
        ),
        store,
    )

    assert ranked == []


def test_explicit_financial_comparison_does_not_fill_with_third_known_company():
    apple = _result(
        "apple-q2",
        "apple-revenue",
        0.12,
        "Apple total net sales were $111,184 million.",
        company="Apple",
        tenant_id=7,
    )
    tesla = _result(
        "tesla-q4",
        "tesla-revenue",
        0.11,
        "Tesla total revenues were $24,901 million.",
        company="Tesla",
        tenant_id=7,
    )
    nvidia = _result(
        "nvidia-q1",
        "nvidia-revenue",
        0.99,
        "NVIDIA total revenue was $81.6 billion.",
        company="NVIDIA",
        tenant_id=7,
    )
    candidates = [apple, tesla, nvidia]
    store = _HybridStore(vectors={7: candidates}, corpora={7: candidates})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Compare Apple and Tesla's financial performance.",
            top_k=3,
            tenant_id=7,
        ),
        store,
    )

    assert {item.metadata["company"] for item in ranked} <= {"Apple", "Tesla"}
    assert {item.chunk_id for item in ranked} == {"apple-revenue", "tesla-revenue"}


def test_comparison_keeps_evidence_with_unknown_company_metadata_eligible():
    apple = _result("apple-q2", "apple-revenue", 0.12, "Apple total net sales were $111,184 million.", company="Apple")
    tesla = _result("tesla-q4", "tesla-revenue", 0.11, "Tesla total revenues were $24,901 million.", company="Tesla")
    unknown = _result(
        "legacy-report",
        "unknown-company-revenue",
        0.10,
        "Reported revenue and operating margin were disclosed for the period.",
        company="",
    )
    store = _HybridStore(vectors={7: [apple, tesla, unknown]}, corpora={7: [apple, tesla, unknown]})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="Compare Apple and Tesla's financial performance.",
            top_k=3,
            tenant_id=7,
        ),
        store,
    )

    assert "unknown-company-revenue" in {item.chunk_id for item in ranked}


def test_canonical_apple_pdf_retrieval_finds_revenue_and_cash_flow_rows_offline():
    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    path = "demo/documents/Apple_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    document_period = get_document_period(chunks)
    corpus = [
        _result(
            "apple_q2_2026",
            f"apple-pdf-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company=get_company(path),
            tenant_id=7,
            source=path.rsplit("/", maxsplit=1)[-1],
            section=chunk.section,
            page=chunk.page,
            quarter=document_period,
            table_context=chunk.table_context or "",
            content_type=chunk.content_type,
            source_locator=chunk.source_locator or "",
            periods="|".join(extract_periods(f"{chunk.table_context or ''}\n{chunk.text}")),
            metrics="|".join(extract_metrics(chunk.text)),
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})
    retriever = HybridRetriever(_EmbeddingModel())

    for question in (
        "What does Apple's Q2 2026 report say about revenue performance?",
        "苹果 2026 财年第二季度报告如何描述收入表现？",
        "苹果 2026 年第二季度财报中的营收表现如何？",
    ):
        revenue = retriever.retrieve(
            RetrievalContext(
                question=question,
                company="Apple",
                top_k=6,
                tenant_id=7,
            ),
            store,
        )
        revenue_text = "\n".join(item.content for item in revenue)
        evidence = [
            Evidence(
                content=item.content,
                source=str(item.metadata.get("source", "Apple_sample.pdf")),
                company=str(item.metadata.get("company", "Apple")),
                confidence=item.score,
                metadata={**item.metadata, "chunk_id": item.chunk_id},
            )
            for item in revenue
        ]
        language_mismatch_refusal = (
            "当前检索到的证据没有包含 Apple Q2 2026 的总收入数字。"
            if any("\u3400" <= char <= "\u9fff" for char in question)
            else "Apple's Q2 2026 report does not disclose total revenue in the retrieved evidence."
        )
        finalized = finalize_grounded_answer(question, language_mismatch_refusal, evidence)

        assert "111,184" in revenue_text and "95,359" in revenue_text
        assert "111.184 billion USD" in finalized.answer or "111,184" in finalized.answer, {
            "question": question,
            "raw_grounding": finalized.raw_grounding.answer,
            "required": finalized.plan.as_dict(finalized.ledger, finalized.answer)["required"],
            "facts": [
                (fact.metric_id, fact.fact_period, str(fact.normalized_value), fact.chunk_id)
                for fact in finalized.ledger.facts
            ],
            "retrieved": [(item.chunk_id, item.metadata.get("content_type"), item.content[:120]) for item in revenue],
        }
        assert "does not disclose" not in finalized.answer.casefold()
        assert "没有包含" not in finalized.answer
        assert finalized.grounded.unsupported_count == 0
    cash_flow = retriever.retrieve(
        RetrievalContext(
            question="What does Apple report about cash flow in Q2 2026?",
            company="Apple",
            top_k=6,
            tenant_id=7,
        ),
        store,
    )

    assert any("82,627" in item.content and "cash generated by operating activities" in item.content.casefold() for item in cash_flow)


def test_canonical_apple_broad_financial_summary_keeps_key_statement_rows_offline():
    path = "demo/documents/Apple_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    corpus = [
        _result(
            "apple_q2_2026",
            f"apple-summary-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company=get_company(path),
            tenant_id=7,
            source=path.rsplit("/", maxsplit=1)[-1],
            section=chunk.section,
            page=chunk.page,
            table_context=getattr(chunk, "table_context", ""),
            content_type=chunk.content_type,
            quarter=get_document_period(chunks),
            source_locator=chunk.source_locator or "",
            source_format=chunk.source_format,
            periods="|".join(extract_periods(chunk.text)),
            metrics="|".join(extract_metrics(chunk.text)),
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    questions = (
        "How was Apple doing financially in Q2 2026?",
        "How was the iPhone maker doing financially in the second quarter of 2026?",
        "那个做 iPhone 的公司 2026 年二季度业绩怎么样？",
    )
    contexts = []
    retrieved = []
    for question in questions:
        companies = extract_companies(question)
        assert companies == ["Apple"]
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company=companies[0],
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        retrieved.append((question, ranked))
        contexts.append("\n".join(item.content for item in ranked))

    for context in contexts:
        assert "111,184" in context  # Q2 total net sales, USD millions.
        assert "29,578" in context  # Q2 net income, USD millions.
        assert "54,781" in context  # Q2 gross-profit dollars; the filing labels this line "Gross margin".
        assert "2.01" in context  # Q2 diluted earnings per share.

    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    finalized = []
    for question, ranked in retrieved:
        chinese = any("\u3400" <= char <= "\u9fff" for char in question)
        refusal = (
            "当前检索到的证据没有包含苹果 Q2 FY2026 财务表现。"
            if chinese
            else "The retrieved passages do not include Apple's Q2 FY2026 financial results."
        )
        finalized.append(
            finalize_grounded_answer(
                question,
                refusal,
                [
                    Evidence(
                        content=item.content,
                        source=str(item.metadata.get("source", "Apple_sample.pdf")),
                        company=str(item.metadata.get("company", "Apple")),
                        confidence=item.score,
                        metadata={**item.metadata, "chunk_id": item.chunk_id},
                    )
                    for item in ranked
                ],
            )
        )

    def fact_plan_signature(result):
        return [
            (
                row["company"],
                row["metric_id"],
                row["period"],
                row["available"],
                row["answer_present"],
            )
            for row in result.plan.as_dict(result.ledger, result.answer)["required"]
        ]

    expected_signature = fact_plan_signature(finalized[0])
    assert expected_signature
    assert all(fact_plan_signature(result) == expected_signature for result in finalized[1:])
    for result in finalized:
        assert "111.184" in result.answer
        assert "29.578" in result.answer
        assert "54.781" in result.answer
        assert "2.01" in result.answer
        assert "do not include Apple's" not in result.answer
        assert "没有包含苹果" not in result.answer
        assert "retrieved passages do not include" not in result.answer.casefold()
        assert result.grounded.unsupported_count == 0


def test_canonical_apple_services_performance_retrieval_is_bilingual_and_grounded():
    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    path = "demo/documents/Apple_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    corpus = [
        _result(
            "apple_q2_2026",
            f"apple-services-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company=get_company(path),
            tenant_id=7,
            source="Apple_sample.pdf",
            section=chunk.section,
            page=chunk.page,
            table_context=getattr(chunk, "table_context", ""),
            content_type=chunk.content_type,
            source_locator=chunk.source_locator or "",
            source_format=chunk.source_format,
            quarter=get_document_period(chunks),
            periods="|".join(extract_periods(f"{chunk.table_context}\n{chunk.text}")),
            metrics="|".join(extract_metrics(chunk.text)),
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})
    questions = (
        "How did Apple's Services business perform in Q2 2026?",
        "How is Apple's service-related business doing?",
        "苹果的服务业务在 2026 年第二季度表现如何？",
        "苹果的服务业务表现怎么样？",
    )

    signatures = []
    for question in questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="Apple",
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        assert all(
            item.metadata.get("content_type") != "unverified_table"
            for item in ranked
        ), (question, [item.chunk_id for item in ranked])
        context = "\n".join(item.content for item in ranked)
        assert "30,976" in context, (question, [item.chunk_id for item in ranked])

        finalized = finalize_grounded_answer(
            question,
            "The retrieved passages do not identify Apple's Services performance.",
            [
                Evidence(
                    content=item.content,
                    source=str(item.metadata.get("source", "Apple_sample.pdf")),
                    company=str(item.metadata.get("company", "Apple")),
                    confidence=item.score,
                    metadata={**item.metadata, "chunk_id": item.chunk_id},
                )
                for item in ranked
            ],
        )
        required = finalized.plan.as_dict(finalized.ledger, finalized.answer)["required"]
        service_fact = next(row for row in required if row["metric_id"] == "services_revenue")
        assert service_fact["available"] and service_fact["answer_present"], (question, service_fact)
        assert "30.976" in finalized.answer or "30,976" in finalized.answer
        assert finalized.grounded.unsupported_count == 0
        signatures.append((service_fact["metric_id"], service_fact["available"], service_fact["answer_present"]))

    assert len(set(signatures)) == 1


def test_canonical_nvidia_summary_retrieval_keeps_headlines_and_reported_drivers_offline():
    path = "demo/documents/NVIDIA_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    corpus = [
        _result(
            "nvidia_q1_fy2027",
            f"nvidia-pdf-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company=get_company(path),
            tenant_id=7,
            source=path.rsplit("/", maxsplit=1)[-1],
            section=chunk.section,
            page=chunk.page,
            periods="|".join(extract_periods(chunk.text)),
            metrics="|".join(extract_metrics(chunk.text)),
            quarter="Q1_FY2027",
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    questions = (
        "Summarize NVIDIA's financial performance in Q1 FY2027.",
        "总结英伟达 2027 财年第一季度的财务表现。",
    )
    contexts = []
    for question in questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="NVIDIA",
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        contexts.append("\n".join(item.content.casefold() for item in ranked))

    for context in contexts:
        assert any(value in context for value in ("81,615", "81.6 billion"))
        assert "85%" in context and "20%" in context
        assert "data center" in context and any(value in context for value in ("75.2", "75. 2"))
        assert "92%" in context
        assert "74.9%" in context and "75.0%" in context
        assert "$2.39" in context and "$1.87" in context
        assert "agentic ai" in context and "ai factories" in context
        assert "$91.0 billion" not in context

    driver_questions = (
        "What drove the chip company's data-center business in its first fiscal quarter of 2027?",
        "那家做 GPU 的公司在 2027 财年第一季度，数据中心业务为什么增长？",
        "What were the main drivers of NVIDIA's growth in Q1 FY2027?",
        "英伟达 2027 财年第一季度增长的主要驱动因素是什么？",
    )
    driver_retrievals = {}
    for question in driver_questions:
        assert extract_companies(question) == ["NVIDIA"]
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                top_k=8,
                tenant_id=7,
            ),
            store,
        )
        context = "\n".join(item.content.casefold() for item in ranked)
        assert "ai factories" in context and "agentic ai" in context
        if "data-center" in question.casefold() or "数据中心" in question:
            assert any(value in context for value in ("75.2", "75. 2"))
        driver_retrievals[question] = ranked

    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    for question, refusal in (
        (
            "What were the main drivers of NVIDIA's growth in Q1 FY2027?",
            "The retrieved passages are insufficient to answer this question reliably.",
        ),
        (
            "英伟达 2027 财年第一季度增长的主要驱动因素是什么？",
            "当前检索到的证据不足以可靠回答该问题。",
        ),
    ):
        evidence = [
            Evidence(
                content=item.content,
                source=str(item.metadata.get("source", "NVIDIA_sample.pdf")),
                company=str(item.metadata.get("company", "NVIDIA")),
                confidence=item.score,
                metadata={**item.metadata, "chunk_id": item.chunk_id},
            )
            for item in driver_retrievals[question]
        ]
        finalized = finalize_grounded_answer(question, refusal, evidence)
        assert "AI factories" in finalized.answer
        assert "Agentic AI" in finalized.answer
        if question.startswith("What"):
            assert "Related filing context" in finalized.answer
            assert "not an explicit attribution" in finalized.answer
        else:
            assert "财报相关背景" in finalized.answer
            assert "未明确归因" in finalized.answer
        assert finalized.grounded.unsupported_count == 0
        assert all(item.company == "NVIDIA" for item in finalized.grounded.evidence)

    margin_results = []
    margin_questions = (
        "What does NVIDIA's Q1 FY2027 report say about margins?",
        "英伟达 2027 财年第一季度财报如何描述利润率？",
    )
    for question in margin_questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="NVIDIA",
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        margin_results.append(ranked)

    for results in margin_results:
        assert any(
            item.metadata.get("page") == 1
            and "gross margins were 74.9% and 75.0%" in item.content.casefold()
            for item in results
        )

    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    finalized_margins = []
    for question, results in zip(margin_questions, margin_results, strict=True):
        evidence = [
            Evidence(
                content=item.content,
                source=str(item.metadata.get("source", "NVIDIA_sample.pdf")),
                company=str(item.metadata.get("company", "NVIDIA")),
                confidence=item.score,
                metadata={**item.metadata, "chunk_id": item.chunk_id},
            )
            for item in results
        ]
        refusal = (
            "The retrieved passages are insufficient to establish the Q1 FY2027 margins."
            if question.startswith("What")
            else "当前检索到的内容不足以确认 Q1 FY2027 利润率。"
        )
        finalized_margins.append(
            finalize_grounded_answer(question, refusal, evidence)
        )

    def margin_plan_signature(result):
        return [
            (
                row["company"],
                row["metric_id"],
                row["period"],
                row["available"],
                row["answer_present"],
            )
            for row in result.plan.as_dict(result.ledger, result.answer)["required"]
        ]

    assert margin_plan_signature(finalized_margins[0]) == margin_plan_signature(
        finalized_margins[1]
    )
    for result in finalized_margins:
        assert "74.9%" in result.answer
        assert "Q2 FY2027" not in result.answer
        assert result.grounded.unsupported_count == 0

    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    driver_cases = (
        (
            "What drove the chip company's data-center business in its first fiscal quarter of 2027?",
            "NVIDIA",
            "The available evidence does not establish the requested driver.\n"
            "NVIDIA Q2 FY2027 revenue was $91 billion USD [Evidence 2].",
        ),
        (
            "那家做 GPU 的公司在 2027 财年第一季度，数据中心业务为什么增长？",
            None,
            "当前证据没有说明该业务的驱动因素。\n"
            "NVIDIA Q2 FY2027 revenue was $91 billion USD [Evidence 2].",
        ),
    )
    for driver_question, driver_company, raw_answer in driver_cases:
        driver_results = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=driver_question,
                company=driver_company,
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        assert any("75.2" in item.content or "75. 2" in item.content for item in driver_results)
        assert any(
            "agentic ai" in item.content.casefold()
            or "ai factories" in item.content.casefold()
            for item in driver_results
        ), (driver_question, [item.chunk_id for item in driver_results])
        assert all("$91.0 billion" not in item.content for item in driver_results), (
            driver_question,
            [item.chunk_id for item in driver_results],
        )
        finalized = finalize_grounded_answer(
            driver_question,
            raw_answer,
            [
                Evidence(
                    content=item.content,
                    source=str(item.metadata.get("source", "NVIDIA_Q1_FY2027.pdf")),
                    company=str(item.metadata.get("company", "NVIDIA")),
                    confidence=item.score,
                    metadata={**item.metadata, "chunk_id": item.chunk_id},
                )
                for item in driver_results
            ],
        )
        assert "75.2 billion" in finalized.answer
        assert "ai factories" in finalized.answer.casefold()
        assert "agentic ai" in finalized.answer.casefold()
        assert "91 billion" not in finalized.answer
        assert "does not establish the requested driver" not in finalized.answer.casefold()
        assert finalized.grounded.unsupported_count == 0


def test_canonical_tesla_pdf_retrieval_keeps_q2_2025_margin_rows_offline():
    path = "demo/documents/Tesla_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    corpus = [
        _result(
            "tesla_fy2025",
            f"tesla-pdf-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company=get_company(path),
            tenant_id=7,
            source=path.rsplit("/", maxsplit=1)[-1],
            section=chunk.section,
            page=chunk.page,
            table_context=getattr(chunk, "table_context", ""),
            periods="|".join(
                extract_periods(
                    f"{getattr(chunk, 'table_context', '')}\n{chunk.text}"
                )
            ),
            metrics="|".join(extract_metrics(chunk.text)),
            quarter="Q4_FY2025",
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    questions = (
        "What were Tesla's gross and operating margins in Q2 2025?",
        "特斯拉 2025 年第二季度的毛利率和营业利润率是多少？",
    )
    for question in questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="Tesla",
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        context = "\n".join(item.content for item in ranked)
        assert "17.2%" in context and "4.1%" in context, [
            item.chunk_id for item in ranked
        ]


def test_canonical_tesla_pdf_retrieval_keeps_q2_2025_free_cash_flow_row_offline():
    """Flattened verified summary rows must still expose the Q2 FCF cell."""

    path = "demo/documents/Tesla_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    corpus = [
        _result(
            "tesla_fy2025",
            f"tesla-fcf-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company=get_company(path),
            tenant_id=7,
            source=path.rsplit("/", maxsplit=1)[-1],
            section=chunk.section,
            page=chunk.page,
            table_context=getattr(chunk, "table_context", ""),
            content_type=chunk.content_type,
            periods="|".join(
                extract_periods(
                    f"{getattr(chunk, 'table_context', '')}\n{chunk.text}"
                )
            ),
            metrics="|".join(extract_metrics(chunk.text)),
            quarter="Q4_FY2025",
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    for question in (
        "What was Tesla's free cash flow in Q2 2025?",
        "特斯拉 2025 年第二季度的自由现金流是多少？",
    ):
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="Tesla",
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        context = "\n".join(item.content for item in ranked)
        assert "Free cash flow" in context and "2,034 664 146" in context, [
            item.chunk_id for item in ranked
        ]


def test_bilingual_tesla_margin_followup_inherits_company_and_period_without_leakage():
    path = "demo/documents/Tesla_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    corpus = [
        _result(
            "tesla_fy2025",
            f"tesla-followup-{index}",
            0.9 - index * 0.0001,
            chunk.text,
            company=get_company(path),
            tenant_id=7,
            source=path.rsplit("/", maxsplit=1)[-1],
            section=chunk.section,
            page=chunk.page,
            table_context=getattr(chunk, "table_context", ""),
            periods="|".join(extract_periods(f"{getattr(chunk, 'table_context', '')}\n{chunk.text}")),
            metrics="|".join(extract_metrics(chunk.text)),
            quarter="Q4_FY2025",
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})
    retriever = HybridRetriever(_EmbeddingModel())
    cases = (
        (
            "What did it say about margins?",
            "Tell me about Tesla's Q2 2025 performance.",
        ),
        (
            "那它的利润率表现呢？",
            "介绍一下特斯拉 2025 年第二季度的表现。",
        ),
    )

    for question, setup in cases:
        inherited = prior_user_context_for_followup(
            question, [{"role": "user", "content": setup}]
        )
        assert inherited is not None
        prior_question, companies = inherited
        resolved = f"{question}\nRelevant prior user request: {prior_question}"
        assert companies == ["Tesla"]
        directly_ranked = HybridRetriever.coverage_aware_rerank(
            corpus, resolved, top_k=4, company=companies[0]
        )
        ranked = retriever.retrieve(
            RetrievalContext(
                question=resolved,
                company=companies[0],
                top_k=4,
                tenant_id=7,
            ),
            store,
        )
        assert ranked
        assert all(item.metadata["company"] == "Tesla" for item in ranked)
        context = "\n".join(item.content for item in ranked)
        assert "17.2%" in context and "4.1%" in context, (
            question,
            [item.chunk_id for item in ranked],
            [item.chunk_id for item in directly_ranked],
        )
        assert "NVIDIA" not in context and "Apple" not in context


def test_explicit_metric_question_runs_structural_lexical_candidate_search():
    narrative = _result(
        "nvidia-q1",
        "generic-narrative",
        0.99,
        "NVIDIA Q1 FY2027 discussed strong demand and a new product framework.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
    )
    margin = _result(
        "nvidia-q1",
        "gross-margin-row",
        0.10,
        "NVIDIA Q1 FY2027 Summary. GAAP gross margin 74.9%; non-GAAP gross margin 75.0%.",
        company="NVIDIA",
        tenant_id=0,
        quarter="Q1_FY2027",
        section="Financial Summary",
        table_context="Q1 FY2027; gross margin table",
    )
    store = _HybridStore(vectors={0: [narrative]}, corpora={0: [narrative, margin]})

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="What does NVIDIA's Q1 FY2027 report say about margins?",
            company="NVIDIA",
            top_k=3,
            tenant_id=0,
        ),
        store,
    )

    assert "gross-margin-row" in {item.chunk_id for item in ranked}


def test_public_retrieve_prefers_split_q1_table_row_over_wrong_period_vector_hit():
    wrong_period = _result(
        "nvidia-report",
        "q2-outlook",
        0.99,
        "NVIDIA Q2 FY2027 outlook: revenue is expected to be $91 billion.",
        company="NVIDIA",
        tenant_id=7,
        quarter="Q1_FY2027",
        filename_period_hint="Q1_FY2027",
        source_authority="tenant_upload",
        content_type="narrative",
    )
    q1_row = _result(
        "nvidia-report",
        "q1-revenue-row",
        0.20,
        "Financial table row — Total revenues: $81.6 billion",
        company="NVIDIA",
        tenant_id=7,
        source_authority="tenant_upload",
        content_type="table",
        table_context="NVIDIA Q1 FY2027 results; Statement of Operations",
    )
    store = _HybridStore(
        vectors={7: [wrong_period, q1_row]},
        corpora={7: [wrong_period, q1_row]},
    )

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="What was NVIDIA's revenue in Q1 FY2027?",
            company="NVIDIA",
            top_k=1,
            tenant_id=7,
        ),
        store,
    )
    vector_only_ranked = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(enabled=False),
    ).retrieve(
        RetrievalContext(
            question="What was NVIDIA's revenue in Q1 FY2027?",
            company="NVIDIA",
            top_k=1,
            tenant_id=7,
        ),
        _VectorOnlyStore([wrong_period, q1_row]),
    )

    assert [item.chunk_id for item in ranked] == ["q1-revenue-row"]
    assert [item.chunk_id for item in vector_only_ranked] == ["q1-revenue-row"]


def test_public_retrieve_keeps_each_company_risk_and_excludes_disclaimer_slots():
    apple_disclaimer = _result(
        "apple-report",
        "apple-safe-harbor",
        0.99,
        "Apple Inc. forward-looking statements are subject to risks and uncertainties.",
        company="Apple",
        tenant_id=7,
    )
    apple_risk = _result(
        "apple-report",
        "apple-risk",
        0.45,
        "Apple risk factors include supply constraints and regulatory requirements.",
        company="Apple",
        tenant_id=7,
    )
    nvidia_disclaimer = _result(
        "nvidia-report",
        "nvidia-safe-harbor",
        0.98,
        "NVIDIA forward-looking statements are subject to risks and uncertainties.",
        company="NVIDIA",
        tenant_id=7,
    )
    nvidia_risk = _result(
        "nvidia-report",
        "nvidia-risk",
        0.40,
        "NVIDIA may be adversely affected by export restrictions.",
        company="NVIDIA",
        tenant_id=7,
    )
    candidates = [apple_disclaimer, nvidia_disclaimer, apple_risk, nvidia_risk]
    store = _HybridStore(vectors={7: candidates}, corpora={7: candidates})

    retriever = HybridRetriever(_EmbeddingModel())
    for question in (
        "Compare Apple and NVIDIA risk factors.",
        "比较 Apple 和 NVIDIA 的风险因素。",
    ):
        ranked = retriever.retrieve(
            RetrievalContext(
                question=question,
                top_k=2,
                tenant_id=7,
            ),
            store,
        )

        assert {item.chunk_id for item in ranked} == {"apple-risk", "nvidia-risk"}


def test_risk_disclosure_uses_verified_filing_period_not_incidental_outlook_period():
    risk_text = (
        "NVIDIA's outlook for the second quarter of fiscal 2027 is as follows. "
        "Forward-looking statements are subject to risks and uncertainties. "
        "Important factors that could cause actual results to differ materially "
        "include global economic and political conditions and NVIDIA's reliance "
        "on third parties to manufacture, assemble, package and test products."
    )
    q1_filing_risk = _result(
        "nvidia-q1-filing",
        "nvidia-q1-risk-disclosure",
        0.4,
        risk_text,
        company="NVIDIA",
        tenant_id=7,
        quarter="Q1_FY2027",
        periods="Q2_FY2027",
        source_authority="tenant_upload",
    )
    q2_filing_risk = _result(
        "nvidia-q2-filing",
        "nvidia-q2-risk-disclosure",
        0.9,
        risk_text,
        company="NVIDIA",
        tenant_id=7,
        quarter="Q2_FY2027",
        periods="Q2_FY2027",
        source_authority="tenant_upload",
    )
    store = _HybridStore(
        vectors={7: [q2_filing_risk, q1_filing_risk]},
        corpora={7: [q2_filing_risk, q1_filing_risk]},
    )

    ranked = HybridRetriever(_EmbeddingModel()).retrieve(
        RetrievalContext(
            question="What risk factors are mentioned in NVIDIA's Q1 FY2027 report?",
            company="NVIDIA",
            top_k=1,
            tenant_id=7,
        ),
        store,
    )

    assert [item.chunk_id for item in ranked] == ["nvidia-q1-risk-disclosure"]


def test_broad_financial_comparison_reserves_metrics_for_each_company():
    candidates = [
        _result("apple", "apple-revenue", 0.90, "Apple total net sales $111,184 million.", company="Apple"),
        _result("apple", "apple-net-income", 0.60, "Apple net income $29,578 million.", company="Apple"),
        _result("tesla", "tesla-revenue", 0.80, "Tesla total revenues $22,496 million.", company="Tesla"),
        _result("tesla", "tesla-net-income", 0.50, "Tesla net income $1,172 million.", company="Tesla"),
    ]

    ranked = HybridRetriever.coverage_aware_rerank(
        candidates,
        "Compare Apple and Tesla's financial performance.",
        top_k=4,
    )

    assert {"apple-revenue", "tesla-revenue", "apple-net-income", "tesla-net-income"} <= {
        item.chunk_id for item in ranked
    }


def test_canonical_apple_tesla_comparison_keeps_each_report_income_facts_offline():
    from agent.reasoning_models import Evidence
    from core.fact_ledger import FactLedger
    from core.required_fact_plan import infer_required_fact_plan

    corpus = []
    for path, document_id in (
        ("demo/documents/Apple_sample.pdf", "apple_q2_2026"),
        ("demo/documents/Tesla_sample.pdf", "tesla_fy2025"),
    ):
        chunks = load_pdf_chunks(path, ocr_enabled=False)
        document_period = get_document_period(chunks)
        for index, chunk in enumerate(chunks):
            table_context = getattr(chunk, "table_context", "")
            corpus.append(
                _result(
                    document_id,
                    f"{document_id}-{index}",
                    0.9 - len(corpus) * 0.0001,
                    chunk.text,
                    company=get_company(path),
                    tenant_id=7,
                    source=path.rsplit("/", maxsplit=1)[-1],
                    section=chunk.section,
                    page=chunk.page,
                    table_context=table_context,
                    content_type=chunk.content_type,
                    source_locator=chunk.source_locator or "",
                    source_format=chunk.source_format,
                    periods="|".join(extract_periods(f"{table_context}\n{chunk.text}")),
                    metrics="|".join(extract_metrics(chunk.text)),
                    quarter=document_period,
                )
            )
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    questions = (
        ("Compare Apple and Tesla's financial performance.", "94,827", "3,794", "18.0%", "4.6%"),
        ("比较苹果和特斯拉的财务表现。", "94,827", "3,794", "18.0%", "4.6%"),
        (
            "Compare Apple's Q2 FY2026 and Tesla's Q2 2025 financial performance.",
            "22,496",
            "1,172",
            "17.2%",
            "4.1%",
        ),
        (
            "比较苹果 2026 财年第二季度和特斯拉 2025 年第二季度的财务表现。",
            "22,496",
            "1,172",
            "17.2%",
            "4.1%",
        ),
    )
    comparison_coverage = {}
    for (
        question,
        expected_tesla_revenue,
        expected_tesla_net_income,
        expected_tesla_gross_margin,
        expected_tesla_operating_margin,
    ) in questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                top_k=8,
                tenant_id=7,
            ),
            store,
        )

        by_company = {
            company: "\n".join(item.content for item in ranked if item.metadata["company"] == company)
            for company in ("Apple", "Tesla")
        }
        results_by_company = {
            company: [item for item in ranked if item.metadata["company"] == company]
            for company in ("Apple", "Tesla")
        }
        language = "zh" if any("\u3400" <= character <= "\u9fff" for character in question) else "en"
        period_scope = "period_specific" if extract_periods(question) else "broad"
        evidence = [
            Evidence(
                content=item.content,
                source=str(item.metadata.get("source", "")),
                company=str(item.metadata.get("company", "")),
                metadata={**item.metadata, "chunk_id": item.chunk_id},
            )
            for item in ranked
        ]
        ledger = FactLedger.from_evidence(evidence)
        plan = infer_required_fact_plan(question, evidence, ledger)
        comparison_coverage[(period_scope, language)] = {
            (
                str(item["company"]),
                str(item["metric_id"]),
                str(item["period"]),
            )
            for item in plan.as_dict(ledger, "")["required"]
            if item["answer_present"]
        }
        assert "111,184" in by_company["Apple"] and "29,578" in by_company["Apple"], (
            question,
            [item.chunk_id for item in ranked if item.metadata["company"] == "Apple"],
        )
        assert expected_tesla_revenue in by_company["Tesla"] and expected_tesla_net_income in by_company["Tesla"], (
            question,
            [item.chunk_id for item in ranked if item.metadata["company"] == "Tesla"],
        )
        assert expected_tesla_gross_margin in by_company["Tesla"] and expected_tesla_operating_margin in by_company["Tesla"], [
            "gross_present=" + str(expected_tesla_gross_margin in by_company["Tesla"]),
            "operating_present=" + str(expected_tesla_operating_margin in by_company["Tesla"]),
            [item.chunk_id for item in ranked if item.metadata["company"] == "Tesla"],
        ]
        for company in ("Apple", "Tesla"):
            available_metrics = {
                metric
                for item in results_by_company[company]
                for metric in extract_metrics(item.content)
            }
            assert {"revenue", "net_income", "gross_margin"} <= available_metrics, (
                question,
                company,
                available_metrics,
            )
        if "Q2 2025" in question or "第二季度" in question:
            assert any("Q2_FY2026" in item.metadata["periods"] for item in results_by_company["Apple"])
            assert any("Q2_2025" in item.metadata["periods"] for item in results_by_company["Tesla"])
        else:
            assert "2025" in by_company["Tesla"]
            assert {
                item.metadata["quarter"] for item in results_by_company["Apple"]
            } == {"Q2_FY2026"}
            assert {
                item.metadata["quarter"] for item in results_by_company["Tesla"]
            } == {"Q4_2025"}

    assert comparison_coverage[("broad", "en")] == comparison_coverage[("broad", "zh")]
    assert comparison_coverage[("period_specific", "en")] == comparison_coverage[("period_specific", "zh")]


def test_real_tesla_annual_summary_rows_are_not_labeled_as_q4_actuals():
    from agent.reasoning_models import Evidence
    from core.fact_ledger import FactLedger

    path = "demo/documents/Tesla_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    reporting_period = get_document_period(chunks)
    evidence = [
        Evidence(
            content=chunk.text,
            source="Tesla_sample.pdf",
            company="Tesla",
            metadata={
                "chunk_id": str(index),
                "quarter": reporting_period,
                "content_type": chunk.content_type,
                "table_context": chunk.table_context or "",
            },
        )
        for index, chunk in enumerate(chunks)
        if "94,827" in chunk.text
    ]
    ledger = FactLedger.from_evidence(evidence)

    assert any(
        fact.normalized_value == 94_827_000_000
        for fact in ledger.lookup(company="Tesla", metric_id="revenue", period="FY2025")
    )
    assert not any(
        fact.normalized_value == 94_827_000_000
        for fact in ledger.lookup(company="Tesla", metric_id="revenue", period="Q4_2025")
    )

def test_public_retrieve_resolves_ev_maker_and_finds_historical_q2_tesla_facts():
    path = "demo/documents/Tesla_sample.pdf"
    chunks = load_pdf_chunks(path, ocr_enabled=False)
    reporting_period = get_document_period(chunks)
    assert reporting_period == "Q4_2025"
    corpus = [
        _result(
            "tesla-fy2025",
            f"tesla-sample-{index}",
            0.99 - index * 0.0001,
            chunk.text,
            company="Tesla",
            source="Tesla_sample.pdf",
            page=chunk.page,
            section=chunk.section,
            quarter=reporting_period,
            content_type=chunk.content_type,
            table_context=chunk.table_context or "",
            periods="|".join(extract_periods(f"{chunk.table_context or ''}\n{chunk.text}")),
            metrics="|".join(extract_metrics(chunk.text)),
        )
        for index, chunk in enumerate(chunks)
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})
    questions = (
        "How did the EV maker perform financially in the second quarter of 2025?",
        "那家电动车公司在 2025 年二季度经营得怎么样？",
    )

    from agent.reasoning_models import Evidence
    from core.answer_policy import finalize_grounded_answer

    for question in questions:
        ranked = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(question=question, top_k=8, tenant_id=7),
            store,
        )
        tesla_text = "\n".join(item.content for item in ranked if item.metadata["company"] == "Tesla")
        assert extract_companies(question) == ["Tesla"]
        assert "22,496" in tesla_text
        assert not any(
            "Q4-2025" in item.content and "Q2-2025" not in item.content
            for item in ranked
        )
        chinese = any("\u3400" <= char <= "\u9fff" for char in question)
        historical_refusal = (
            "当前可检索的上传财报中没有找到足以支持该问题的证据，因此无法可靠回答。"
            if chinese
            else "The Q2 2025 financial facts are not available in the evidence."
        )
        finalized = finalize_grounded_answer(
            question,
            historical_refusal,
            [
                Evidence(
                    content=item.content,
                    source=str(item.metadata.get("source", "Tesla_sample.pdf")),
                    company=str(item.metadata.get("company", "Tesla")),
                    confidence=item.score,
                    metadata={**item.metadata, "chunk_id": item.chunk_id},
                )
                for item in ranked
            ],
        )
        assert "22.496" in finalized.answer or "22,496" in finalized.answer
        assert finalized.grounded.unsupported_count == 0


def test_runtime_retrieval_tool_executes_hybrid_pipeline():
    semantic = _result(
        "semantic",
        "semantic-1",
        0.01,
        "General performance discussion.",
    )
    lexical = _result(
        "tesla-q2",
        "tesla-revenue",
        0.20,
        "Tesla revenue growth accelerated.",
    )
    store = _HybridStore(
        vectors={7: [semantic, lexical]},
        corpora={7: [semantic, lexical]},
    )

    evidence = TenantRetrievalToolExecutor(
        HybridRetriever(_EmbeddingModel())
    ).execute(
        store=store,
        query="Tesla revenue growth",
        tenant_id=7,
        top_k=2,
    )

    assert evidence[0].metadata["retrieval_strategy"] == "hybrid_rrf"
    assert evidence[0].metadata["bm25_rank"] == 1
    assert evidence[0].confidence > 0
    assert store.lexical_calls == [7]


def test_chroma_lexical_corpus_is_tenant_scoped(tmp_path):
    store = ChromaEmbeddingStore(persist_directory=tmp_path / "chroma")
    store.add_documents(
        [
            VectorDocument(
                document_id="tenant-7",
                chunk_id="tenant-7-1",
                company="Tesla",
                content="Tenant seven revenue evidence.",
                embedding=[0.1, 0.2],
                metadata={
                    "collection": "financial_reports",
                    "tenant_id": 7,
                },
            ),
            VectorDocument(
                document_id="tenant-99",
                chunk_id="tenant-99-1",
                company="Tesla",
                content="Tenant ninety-nine revenue evidence.",
                embedding=[0.2, 0.1],
                metadata={
                    "collection": "financial_reports",
                    "tenant_id": 99,
                },
            ),
        ]
    )

    results = store.lexical_corpus(tenant_id=7)

    assert [result.chunk_id for result in results] == ["tenant-7-1"]
    assert results[0].metadata["tenant_id"] == 7


def test_public_retrieve_covers_gaap_gross_margin_row_in_bilingual_multi_metric_question():
    table_context = "Tesla FINANCIAL SUMMARY; columns Q4-2024 | Q2-2025"
    corpus = [
        _result(
            "tesla-q2-2025",
            "tesla-revenue",
            0.99,
            "Structured financial table row. Metric: Total revenues | Q2-2025: 22,496",
            company="Tesla",
            periods="Q2_2025",
            metrics="revenue",
            table_context=table_context,
            source_authority="public_filing",
        ),
        _result(
            "tesla-q2-2025",
            "tesla-gaap-gross-margin",
            0.95,
            "Structured financial table row. Metric: Total GAAP gross margin | Q2-2025: 17.2%",
            company="Tesla",
            periods="Q2_2025",
            metrics="gross_margin",
            table_context=table_context,
            source_authority="public_filing",
        ),
        _result(
            "tesla-q2-2025",
            "tesla-operating-margin",
            0.90,
            "Structured financial table row. Metric: Operating margin | Q2-2025: 4.1%",
            company="Tesla",
            periods="Q2_2025",
            metrics="operating_margin",
            table_context=table_context,
            source_authority="public_filing",
        ),
    ]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})
    questions = (
        "What were Tesla's gross and operating margins in Q2 2025?",
        "特斯拉 2025 年第二季度的毛利率和营业利润率是多少？",
    )

    for question in questions:
        results = HybridRetriever(_EmbeddingModel()).retrieve(
            RetrievalContext(
                question=question,
                company="Tesla",
                top_k=3,
                tenant_id=7,
            ),
            store,
        )

        retrieved_text = "\n".join(result.content for result in results)
        assert "Total GAAP gross margin" in retrieved_text
        assert "17.2%" in retrieved_text
        assert "Operating margin" in retrieved_text
        assert "4.1%" in retrieved_text


def test_public_retrieve_reserves_requested_period_metric_row_before_statement_noise():
    same_period_cash_flow = _result(
        "nvidia-q1-fy2027",
        "nvidia-cash-flow",
        0.99,
        "Structured financial table row. Metric: GAAP net cash provided by operating activities | Q1 FY2027: $27.4 billion",
        company="NVIDIA",
        periods="Q1_FY2027",
        metrics="operating_cash_flow",
        table_context="NVIDIA Q1 FY2027 Statement of Cash Flows",
        content_type="table",
        source_authority="public_filing",
    )
    same_period_revenue = _result(
        "nvidia-q1-fy2027",
        "nvidia-revenue",
        0.98,
        "Structured financial table row. Metric: Total revenue | Q1 FY2027: $81.6 billion",
        company="NVIDIA",
        periods="Q1_FY2027",
        metrics="revenue",
        table_context="NVIDIA Q1 FY2027 Statement of Operations",
        content_type="table",
        source_authority="public_filing",
    )
    requested_margin = _result(
        "nvidia-q1-fy2027",
        "nvidia-gross-margin",
        0.10,
        "Structured financial table row. Metric: GAAP gross margin | Q1 FY2027: 74.9%",
        company="NVIDIA",
        periods="Q1_FY2027",
        metrics="gross_margin",
        table_context="NVIDIA Q1 FY2027 Statement of Operations",
        content_type="table",
        source_authority="public_filing",
    )
    corpus = [same_period_cash_flow, same_period_revenue, requested_margin]
    store = _HybridStore(vectors={7: corpus}, corpora={7: corpus})

    retrieved = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(lexical_weight=0.0),
    ).retrieve(
        RetrievalContext(
            question="What was NVIDIA's gross margin in Q1 FY2027?",
            company="NVIDIA",
            top_k=2,
            tenant_id=7,
        ),
        store,
    )

    assert "nvidia-gross-margin" in {item.chunk_id for item in retrieved}


def test_nvidia_release_highlight_is_not_dropped_by_production_table_quarantine():
    source = (
        Path(__file__).resolve().parents[1]
        / "demo"
        / "documents"
        / "NVIDIA_sample.pdf"
    )
    parsed = parse_pdf(source, ocr_enabled=False)
    chunk = next(
        chunk
        for chunk in chunk_document(parsed)
        if "Data Center revenue" in chunk.text and "$75.2 billion" in chunk.text
    )
    evidence = SearchResult(
        document_id="nvidia-sample",
        chunk_id=str(chunk.chunk_index),
        score=0.1,
        content=chunk.text,
        metadata={
            "company": "NVIDIA",
            "content_type": chunk.content_type,
            "quarter": "Q1_FY2027",
            "tenant_id": 7,
            "source_type": "public_filing",
        },
    )
    store = _HybridStore(vectors={7: [evidence]}, corpora={7: [evidence]})

    results = HybridRetriever(
        _EmbeddingModel(),
        config=HybridRetrievalConfig(enabled=False),
    ).retrieve(
        RetrievalContext(
            question="What was NVIDIA Data Center revenue in Q1 FY2027?",
            company="NVIDIA",
            tenant_id=7,
            top_k=4,
        ),
        store,
    )

    assert any("$75.2 billion" in item.content for item in results)
    assert all(item.metadata.get("content_type") != "unverified_table" for item in results)
