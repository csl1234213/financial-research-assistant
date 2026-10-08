from agent.planning import PlanningContext
from agent.query_planner import QueryPlanner
from core.financial_grounding import canonical_metrics
from retrieval.bm25_retriever import BM25Retriever
from retrieval.hybrid_retriever import HybridRetriever, _extract_company_period_targets
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
from storage.vector_models import SearchResult


def test_period_parser_normalizes_fiscal_and_calendar_quarters():
    assert "Q1_FY2027" in extract_periods(
        "NVIDIA reported results for the first quarter of fiscal 2027."
    )


def test_chinese_comparison_conjunction_binds_period_to_each_company():
    question = "比较苹果 2026 财年第二季度和特斯拉 2025 年第二季度的财务表现。"
    assert _extract_company_period_targets(question) == {
        "apple": "Q2_FY2026",
        "tesla": "Q2_2025",
    }


def test_annual_period_parser_does_not_infer_quarters_from_year_only_headers():
    header = "FINANCIAL SUMMARY | 2021 | 2022 | 2023 | 2024 | 2025 | YoY"
    assert extract_annual_periods(header) == (
        "FY2021", "FY2022", "FY2023", "FY2024", "FY2025"
    )
    assert query_filters("What was Tesla's FY2025 revenue?") == {
        "period": "FY2025", "metric": "revenue"
    }

    annual_row = SearchResult(
        document_id="tesla-fy2025",
        chunk_id="tesla-fy-revenue",
        score=0.9,
        content="Total revenues | 2021: 53,823 | 2022: 81,462 | 2023: 96,773 | 2024: 97,690 | 2025: 94,827",
        metadata={
            "company": "Tesla",
            "quarter": "Q4_2025",
            "content_type": "table",
            "table_context": header,
        },
    )
    assert matches_filter(annual_row.content, annual_row.metadata, "period", "FY2025")
    assert not matches_filter(annual_row.content, annual_row.metadata, "period", "Q4_2025")


def test_annual_period_parser_accepts_extracted_chinese_report_title_spacing():
    content = (
        "贵州茅台酒股份有限公司2025 年年度报告\n"
        "天健会计师事务所(特殊普通合伙)为本公司出具了标准无保留意见的审计报告。"
    )
    metadata = {
        "quarter": "2025-12-31",
        "periods": "",
        "table_context": "",
    }

    assert extract_annual_periods(content) == ("FY2025",)
    assert matches_filter(content, metadata, "period", "FY2025")
    assert not matches_filter(content, metadata, "period", "Q4_2025")


def test_metadata_periods_allow_exact_quarter_with_optional_fiscal_marker():
    row = SearchResult(
        document_id="apple-q2-2026",
        chunk_id="sales-row",
        score=1.0,
        content="Total net sales | Q2 FY2026: 111,184 | Q2 FY2025: 95,359",
        metadata={
            "content_type": "table",
            "quarter": "Q2_FY2026",
            "periods": "Q2_FY2026|Q2_FY2025",
            "table_context": "Comparative columns: Q2 FY2026 | Q2 FY2025",
        },
    )

    assert matches_filter(row.content, row.metadata, "period", "Q2_2026")
    assert matches_filter(row.content, row.metadata, "period", "Q2_FY2025")
    assert not matches_filter(row.content, row.metadata, "period", "Q1_2026")


def test_duration_table_year_columns_still_map_to_report_quarters():
    context = "Three Months Ended March 28, March 29, 2026 2025 (In millions)"
    assert extract_annual_periods(context) == ()
    assert query_filters("What were Apple's Q2 FY2026 net sales?") == {
        "period": "Q2_FY2026", "metric": "revenue"
    }


def test_twelve_month_duration_is_annual_not_the_document_q4_label():
    table = SearchResult(
        document_id="tesla-fy2025",
        chunk_id="tesla-full-year-revenue",
        score=0.9,
        content="Total revenues: 94,827",
        metadata={
            "company": "Tesla",
            "quarter": "Q4_2025",
            "content_type": "table",
            "table_context": "Twelve Months Ended December 31, 2025 and 2024 (in millions)",
        },
    )
    assert matches_filter(table.content, table.metadata, "period", "FY2025")
    assert not matches_filter(table.content, table.metadata, "period", "Q4_2025")
    assert "Q2_2025" in extract_periods(
        "Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025"
    )
    assert extract_periods("Q1_FY2027") == ("Q1_FY2027",)
    assert extract_periods("Q1 Fiscal 2027 Summary; Q1 FY27 Q4 FY26 Q1 FY26") == (
        "Q1_FY2027",
        "Q4_FY2026",
        "Q1_FY2026",
    )


def test_period_parser_recognizes_ordinal_before_fiscal_quarter():
    assert extract_periods("in its first fiscal quarter of 2027") == (
        "Q1_FY2027",
    )
    assert extract_periods("during the second fiscal quarter 2027") == (
        "Q2_FY2027",
    )
    assert extract_periods("in the first quarter of fiscal year 2027") == (
        "Q1_FY2027",
    )


def test_forward_quarter_sequence_does_not_create_overlapping_reverse_period():
    assert extract_periods("Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025") == (
        "Q4_2024",
        "Q1_2025",
        "Q2_2025",
        "Q3_2025",
        "Q4_2025",
    )
    assert extract_periods("2025-Q2") == ("Q2_2025",)


def test_metric_parser_preserves_table_subject():
    assert "data_center" in extract_metrics("Record Data Center revenue")
    assert query_filters("NVIDIA Q1 FY2027 Data Center revenue") == {
        "period": "Q1_FY2027",
        "metric": "data_center",
    }


def test_metric_parser_handles_natural_language_margin_and_services_phrasing():
    assert query_filters("What does NVIDIA's Q1 FY2027 report say about margins?") == {
        "period": "Q1_FY2027",
    }
    assert query_filters("How is Apple's service-related business doing?") == {
        "metric": "services",
    }


def test_multi_metric_margin_question_preserves_gross_and_operating_scope():
    question = "What were Tesla's gross and operating margins in Q2 2025?"

    assert extract_metrics(question) == ("gross_margin", "operating_margin")
    assert canonical_metrics(question) == ("operating_margin", "gross_margin")
    assert query_filters(question) == {"period": "Q2_2025"}


def test_multi_period_growth_query_does_not_hard_filter_to_only_the_first_period():
    assert extract_periods("NVIDIA revenue grew from Q1 FY2026 to Q1 FY2027") == (
        "Q1_FY2026",
        "Q1_FY2027",
    )
    assert query_filters("NVIDIA revenue grew from Q1 FY2026 to Q1 FY2027") == {
        "metric": "revenue",
    }


def test_query_planner_attaches_period_constraint_to_retrieval_step():
    plan, _, _ = QueryPlanner().plan(
        PlanningContext(question="Summarize NVIDIA's financial performance in Q1 FY2027.")
    )
    retrieve = plan.tasks[0]
    assert retrieve.parameters["filters"]["period"] == "Q1_FY2027"


def test_hybrid_filter_rejects_wrong_period_but_accepts_comparative_table():
    retriever = HybridRetriever()
    wrong = SearchResult(
        document_id="nvidia",
        chunk_id="q2",
        score=0.1,
        content="NVIDIA outlook for the second quarter of fiscal 2027.",
        metadata={"company": "NVIDIA"},
    )
    table = SearchResult(
        document_id="tesla",
        chunk_id="summary",
        score=0.1,
        content="FINANCIAL SUMMARY Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025 Total revenues 22,496",
        metadata={"company": "Tesla"},
    )
    context = RetrievalContext(
        question="Tesla Q2 2025 revenue",
        company="Tesla",
        filters={"period": "Q2_2025"},
    )
    filtered = retriever._apply_filters(
        [wrong, table],
        {"document_ids": None},
        retriever.metadata_filter.build(context.company, context.filters),
    )
    assert [item.chunk_id for item in filtered] == ["summary"]


def test_table_context_supplies_period_when_a_bound_row_is_split_from_header():
    row = SearchResult(
        document_id="nvidia-q1",
        chunk_id="revenue-row",
        score=0.1,
        content="Financial table row — Total revenues: $81.6 billion",
        metadata={
            "company": "NVIDIA",
            "content_type": "table",
            "table_context": "NVIDIA Q1 FY2027 results; Statement of Operations",
        },
    )

    assert matches_filter(row.content, row.metadata, "period", "Q1_FY2027")


def test_table_context_does_not_guess_a_period_for_unbound_comparative_row():
    row = SearchResult(
        document_id="nvidia-comparative",
        chunk_id="unbound-revenue-row",
        score=0.1,
        content="Total revenues: $81.6 billion",
        metadata={
            "company": "NVIDIA",
            "content_type": "table",
            "table_context": "Q1 FY2027 | Q2 FY2027 | Total revenues",
        },
    )

    assert not matches_filter(row.content, row.metadata, "period", "Q1_FY2027")


def test_explicit_content_period_overrides_stale_document_quarter_metadata():
    row = SearchResult(
        document_id="nvidia-q2",
        chunk_id="q2-outlook",
        score=0.1,
        content="NVIDIA Q2 FY2027 outlook: revenue is expected to be $91 billion.",
        metadata={
            "company": "NVIDIA",
            "quarter": "Q1_FY2027",
            "filename_period_hint": "Q1_FY2027",
        },
    )

    assert not matches_filter(row.content, row.metadata, "period", "Q1_FY2027")


def test_fiscal_marker_variant_requires_matching_document_period_metadata():
    content = "Apple Q2 FY2026 Services net sales were $30,976 million."

    assert matches_filter(
        content,
        {"company": "Apple", "quarter": "Q2_2026"},
        "period",
        "Q2_2026",
    )
    assert not matches_filter(
        content,
        {"company": "Apple", "quarter": "Q1_2026"},
        "period",
        "Q2_2026",
    )


def test_split_row_accepts_same_document_period_with_or_without_fiscal_marker():
    row = SearchResult(
        document_id="apple-q2-2026",
        chunk_id="apple-total-net-sales",
        score=0.1,
        content="Total net sales $111,184 million.",
        metadata={"company": "Apple", "quarter": "Q2_2026"},
    )

    assert matches_filter(row.content, row.metadata, "period", "Q2_FY2026")
    assert not matches_filter(row.content, row.metadata, "period", "Q1_FY2026")


def test_explicit_same_quarter_marker_variant_is_not_a_period_conflict():
    content = "Apple Services net sales increased during the second quarter of 2026."
    matching_metadata = {"company": "Apple", "quarter": "Q2_2026"}
    wrong_metadata = {"company": "Apple", "quarter": "Q1_2026"}

    assert matches_filter(content, matching_metadata, "period", "Q2_FY2026")
    assert not has_explicit_period_conflict(content, matching_metadata, "Q2_FY2026")
    assert not matches_filter(content, wrong_metadata, "period", "Q2_FY2026")
    assert has_explicit_period_conflict(content, wrong_metadata, "Q2_FY2026")


def test_table_header_period_list_cannot_bind_an_explicit_other_period_row():
    row = SearchResult(
        document_id="nvidia-comparative",
        chunk_id="q2-revenue-row",
        score=0.1,
        content="Financial table row — Q2 FY2027 total revenues: $91 billion",
        metadata={
            "company": "NVIDIA",
            "content_type": "table",
            "table_periods": ["Q1_FY2027", "Q2_FY2027"],
        },
    )

    assert not matches_filter(row.content, row.metadata, "period", "Q1_FY2027")


def test_financial_table_recall_prefers_q1_actual_over_q2_outlook():
    documents = [
        SearchResult(
            document_id="nvidia",
            chunk_id="q2-outlook",
            score=0.0,
            content="NVIDIA outlook for the second quarter of fiscal 2027: revenue $91.0 billion.",
            metadata={"company": "NVIDIA"},
        ),
        SearchResult(
            document_id="nvidia",
            chunk_id="q1-results",
            score=0.0,
            content="NVIDIA reported first quarter fiscal 2027 revenue $81.6 billion and Data Center revenue $75.2 billion.",
            metadata={"company": "NVIDIA"},
        ),
    ]
    query = enrich_financial_query(
        "Summarize NVIDIA financial performance in Q1 FY2027.", "NVIDIA"
    )
    candidates = [
        item
        for item in documents
        if matches_filter(item.content, item.metadata, "period", "Q1_FY2027")
    ]
    results = BM25Retriever().search(query=query, documents=candidates, top_k=4)
    assert [item.chunk_id for item in results] == ["q1-results"]
