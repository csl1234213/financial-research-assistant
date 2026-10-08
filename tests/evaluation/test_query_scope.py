from core.growth_driver_evidence import (
    has_growth_driver_evidence,
    is_explicit_growth_driver_question,
    is_growth_driver_question,
    is_growth_narrative_question,
)
from core.query_scope import (
    QueryScope,
    classify_query_scope,
    is_nonfinancial_business_development_summary,
)


def test_scope_classifier_covers_answer_breadth_contracts():
    assert classify_query_scope("What was Tesla revenue in Q2 2025?") is QueryScope.FACT
    assert classify_query_scope("Summarize NVIDIA performance") is QueryScope.SUMMARY
    assert classify_query_scope("Compare Apple and Tesla") is QueryScope.COMPARE
    assert classify_query_scope("Analyze Tesla revenue drivers") is QueryScope.ANALYSIS
    assert classify_query_scope("What risks are mentioned?") is QueryScope.RISK
    assert classify_query_scope("What is gross margin?") is QueryScope.GENERAL_CONCEPT
    assert classify_query_scope("What is Tesla's stock price target for the next 12 months?") is QueryScope.FACT
    assert classify_query_scope("What was Tesla's China market share in 2025?") is QueryScope.FACT
    assert classify_query_scope("How many gross hires did Tesla make?") is QueryScope.FACT
    assert classify_query_scope("Analyze Tesla stock price trends") is QueryScope.ANALYSIS
    assert classify_query_scope(
        "What drove the chip company's data-center business in its first fiscal quarter of 2027?"
    ) is QueryScope.ANALYSIS
    assert classify_query_scope("数据中心业务为什么增长？") is QueryScope.ANALYSIS
    assert classify_query_scope("What is Apple's expected stock price in 2027?") is QueryScope.FACT
    assert classify_query_scope("What is Apple's revenue in Q2 2026?") is QueryScope.FACT
    assert classify_query_scope("什么是毛利率？") is QueryScope.GENERAL_CONCEPT
    assert classify_query_scope("特斯拉未来12个月股价目标是多少？") is QueryScope.FACT
    assert classify_query_scope("苹果的服务业务在 2026 年第二季度表现如何？") is QueryScope.SUMMARY
    assert classify_query_scope("NVDA 的数据中心业务表现咋样？") is QueryScope.SUMMARY
    assert classify_query_scope("How was Apple doing financially in Q2 2026?") is QueryScope.SUMMARY
    assert classify_query_scope("Summarize Tesla revenue in Q2 2025.") is QueryScope.SUMMARY


def test_bilingual_metric_questions_use_the_same_fact_scope():
    english = "What does the Tesla Q2 2025 report say about revenue?"
    chinese = "特斯拉 2025 年第二季度财报披露的营收是多少？"

    assert classify_query_scope(english) is QueryScope.FACT
    assert classify_query_scope(chinese) is QueryScope.FACT


def test_bilingual_revenue_performance_questions_use_summary_scope():
    english = "What does Apple's Q2 2026 report say about revenue performance?"
    chinese = "苹果 2026 年第二季度财报中的营收表现如何？"
    narrow_fact = "What revenue did Tesla report in Q2 2025?"

    assert classify_query_scope(english) is QueryScope.SUMMARY
    assert classify_query_scope(chinese) is QueryScope.SUMMARY
    assert classify_query_scope(narrow_fact) is QueryScope.FACT


def test_financial_summary_may_use_driver_evidence_without_driver_only_retrieval():
    summary = "Summarize NVIDIA's financial performance in Q1 FY2027."
    explicit_driver_question = "What were NVIDIA's main growth drivers in Q1 FY2027?"
    segment_performance = "How did Apple's Services business perform in Q2 2026?"
    chinese_segment_performance = "苹果的服务业务在 2026 年第二季度表现如何？"
    service_business_status = "How is Apple's service-related business doing?"

    # Answer grounding may add reported drivers to a broad summary, while the
    # retriever must still preserve its financial statement evidence.
    assert is_growth_driver_question(summary)
    assert not is_explicit_growth_driver_question(summary)
    assert is_explicit_growth_driver_question(explicit_driver_question)
    for question in (
        segment_performance,
        chinese_segment_performance,
        service_business_status,
    ):
        assert classify_query_scope(question) is QueryScope.SUMMARY
        assert is_growth_driver_question(question)
        assert not is_explicit_growth_driver_question(question)


def test_business_development_summary_is_not_implicitly_a_financial_summary():
    english = "Summarize Tesla's major business developments during Q2 2025."
    chinese = "总结特斯拉 2025 年第二季度的主要业务发展。"
    financial = "Summarize Tesla's financial performance and business developments."

    assert is_nonfinancial_business_development_summary(english)
    assert is_nonfinancial_business_development_summary(chinese)
    assert not is_nonfinancial_business_development_summary(financial)


def test_bilingual_margin_followups_with_inherited_company_period_use_fact_scope():
    english = "Tell me about Tesla's Q2 2025 performance.\nWhat did it say about margins?"
    chinese = "介绍一下特斯拉2025年第二季度的表现。\n那它的利润率表现呢？"

    assert classify_query_scope(english) is QueryScope.FACT
    assert classify_query_scope(chinese) is QueryScope.FACT


def test_benchmark_bilingual_business_driver_questions_share_analysis_scope():
    english = "What major business drivers are described in Apple's Q2 2026 report?"
    chinese = "苹果 2026 年第二季度主要的业务增长驱动因素有哪些？"

    assert classify_query_scope(english) is QueryScope.ANALYSIS
    assert classify_query_scope(chinese) is QueryScope.ANALYSIS


def test_benchmark_bilingual_company_ranking_questions_share_compare_scope():
    english = "Which of Apple, NVIDIA and Tesla reports the strongest growth narrative? Support the comparison with sources."
    chinese = "苹果、英伟达和特斯拉中，哪一家财报体现出的增长势头最强？请用财报证据支持。"

    assert classify_query_scope(english) is QueryScope.COMPARE
    assert classify_query_scope(chinese) is QueryScope.COMPARE


def test_growth_narrative_intent_is_broader_than_causal_driver_intent():
    cases = (
        "Which of Apple, NVIDIA and Tesla reports the strongest growth narrative?",
        "苹果、英伟达和特斯拉中，哪一家财报体现出的增长势头最强？",
        "Compare the companies' growth momentum.",
    )
    for question in cases:
        assert is_growth_narrative_question(question)
        assert not is_explicit_growth_driver_question(question)
        assert is_growth_driver_question(question)


def test_followup_compare_probe_expands_prior_report_to_financial_metrics():
    from core.retrieval_probes import retrieval_probe_queries

    question = (
        "Now compare it with Tesla.\n"
        "Relevant prior user request for reference resolution: Analyze Apple's report."
    )
    probes = retrieval_probe_queries(question, classify_query_scope(question))

    assert "Apple total revenues" in probes
    assert "Tesla total revenues" in probes
    assert "Apple net income" in probes
    assert "Tesla net income" in probes


def test_benchmark_bilingual_business_status_questions_share_summary_scope():
    cases = (
        (
            "What happened to TSLA's automotive business?",
            "TSLA 的汽车业务最近表现如何？",
        ),
        (
            "How is Apple's service-related business doing?",
            "苹果的服务类业务做得怎么样？",
        ),
    )

    for english, chinese in cases:
        assert classify_query_scope(english) is QueryScope.SUMMARY
        assert classify_query_scope(chinese) is QueryScope.SUMMARY


def test_benchmark_bilingual_margin_followups_share_fact_scope():
    english = "What did it say about margins?"
    chinese = "那它的利润率表现呢？"

    assert classify_query_scope(english) is QueryScope.FACT
    assert classify_query_scope(chinese) is QueryScope.FACT


def test_latest_followup_scope_overrides_inherited_comparison_focus():
    english = (
        "Focus only on the business growth drivers.\n"
        "Relevant prior user request for reference resolution: Compare Apple and NVIDIA."
    )
    chinese = (
        "只重点分析它们的业务增长动力。\n"
        "Relevant prior user request for reference resolution: 比较苹果和英伟达的财务表现。"
    )

    assert classify_query_scope(english) is QueryScope.ANALYSIS
    assert classify_query_scope(chinese) is QueryScope.ANALYSIS


def test_current_explicit_comparison_is_not_overridden_by_inherited_driver_context():
    question = (
        "Compare Apple and NVIDIA's business growth drivers.\n"
        "Relevant prior user request for reference resolution: Summarize Apple and NVIDIA."
    )

    assert classify_query_scope(question) is QueryScope.COMPARE


def test_main_growth_driver_question_is_analysis_in_both_languages():
    english = "What were the main drivers of NVIDIA's growth in Q1 FY2027?"
    chinese = "英伟达 2027 财年第一季度的增长，主要驱动因素是什么？"

    assert classify_query_scope(english) is QueryScope.ANALYSIS
    assert classify_query_scope(chinese) is QueryScope.ANALYSIS


def test_chinese_financial_decline_attribution_is_analysis_not_fact_lookup():
    question = "年报中2025年经营活动现金流净额下降主要归因于什么？"

    assert classify_query_scope(question) is QueryScope.ANALYSIS


def test_chinese_growth_driver_word_orders_enable_explicit_driver_retrieval():
    questions = (
        "英伟达 2027 财年第一季度增长的主要驱动因素是什么？",
        "英伟达 2027 财年第一季度的增长，主要驱动因素是什么？",
        "英伟达 2027 财年第一季度的主要增长动力是什么？",
        "英伟达 2027 财年第一季度增长的核心原因是什么？",
    )

    for question in questions:
        assert classify_query_scope(question) is QueryScope.ANALYSIS
        assert is_explicit_growth_driver_question(question)
        assert is_growth_driver_question(question)


def test_filing_cover_growth_company_checkbox_is_not_driver_evidence():
    cover_boilerplate = (
        "Indicate by check mark whether the Registrant is a large accelerated filer, "
        "an accelerated filer, a non-accelerated filer, a smaller reporting company, "
        "or an emerging growth company."
    )
    reported_driver = (
        "Services net sales increased during the second quarter primarily due to "
        "higher net sales from advertising, the App Store, and cloud services."
    )

    assert not has_growth_driver_evidence(cover_boilerplate)
    assert has_growth_driver_evidence(reported_driver)


def test_explicit_driver_extraction_keeps_later_segment_driver_passages():
    from agent.reasoning_models import Evidence
    from core.growth_driver_evidence import extract_growth_driver_passages

    rows = [
        Evidence(
            content=(
                "iPhone net sales increased due to higher net sales of Pro models. "
                "Mac net sales increased due to higher net sales of laptops."
            ),
            company="Apple",
            metadata={"quarter": "Q2_FY2026"},
        ),
        Evidence(
            content=(
                "Services net sales increased during the second quarter primarily "
                "due to higher net sales from advertising, the App Store, and cloud services."
            ),
            company="Apple",
            metadata={"quarter": "Q2_FY2026"},
        ),
    ]

    passages = extract_growth_driver_passages(
        "What major business drivers are described in Apple's Q2 2026 report?",
        rows,
    )

    text = " ".join(item.text for item in passages)
    assert "Pro models" in text
    assert "advertising" in text
    assert "cloud services" in text


def test_multi_company_business_factor_probes_are_issuer_scoped():
    from core.retrieval_probes import retrieval_probe_queries

    question = (
        "Compare NVIDIA, Apple and Tesla in terms of the business factors "
        "driving their reported performance."
    )
    probes = set(retrieval_probe_queries(question, classify_query_scope(question)))

    assert "NVIDIA business growth drivers" in probes
    assert "Apple business growth drivers" in probes
    assert "Tesla business growth drivers" in probes


def test_multi_company_driver_extraction_covers_each_named_issuer():
    from agent.reasoning_models import Evidence
    from core.growth_driver_evidence import extract_growth_driver_passages

    rows = [
        Evidence(
            content="Apple Services net sales increased due to higher advertising sales.",
            company="Apple",
            metadata={"quarter": "Q2_FY2026"},
        ),
        Evidence(
            content="NVIDIA AI factory buildout is accelerating at extraordinary speed.",
            company="NVIDIA",
            metadata={"quarter": "Q1_FY2027"},
        ),
        Evidence(
            content="Tesla energy storage growth provided a positive offset to revenue.",
            company="Tesla",
            metadata={"quarter": "Q4_2025"},
        ),
    ]

    passages = extract_growth_driver_passages(
        "Compare Apple, NVIDIA and Tesla business growth drivers.", rows
    )

    assert {item.company for item in passages} == {"apple", "nvidia", "tesla"}
