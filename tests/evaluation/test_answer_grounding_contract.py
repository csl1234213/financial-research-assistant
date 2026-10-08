"""Provider-free production answer-grounding contract tests."""

from agent.reasoning_models import Evidence
from core.answer_grounding import sanitize_answer
from core.answer_policy import no_evidence_response


def _evidence(
    content: str,
    company: str = "NVIDIA",
    period: str = "Q1_FY2027",
    metrics: str = "revenue",
) -> Evidence:
    return Evidence(
        content=content,
        source=f"{company}_{period}.pdf",
        company=company,
        metadata={"company": company, "periods": period, "metrics": metrics},
    )


def test_supported_numeric_claim_is_retained() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA revenue was $81.6B.",
        [_evidence("NVIDIA Q1 FY2027 total revenue was $81.6 billion USD.")],
    )
    assert "$81.6B" in result.answer
    assert result.claims[0].disposition == "SUPPORTED"


def test_chinese_annual_revenue_claim_uses_fy_period_instead_of_report_date_metadata() -> None:
    evidence = Evidence(
        content=(
            "贵州茅台酒股份有限公司2025年年度报告。2025年度，贵州茅台公司的营业收入"
            "为人民币16,883,810.25万元。其中主营业务收入为人民币16,877,458.52万元，"
            "占营业收入的99.96%。"
        ),
        source="贵州茅台_2025年度报告.pdf",
        company="贵州茅台",
        metadata={
            "chunk_id": "moutai-fy2025-revenue",
            "quarter": "2025-12-31",
            "page": 6,
            "metrics": "revenue",
        },
    )
    result = sanitize_answer(
        "贵州茅台2025年度营业收入是多少？",
        "贵州茅台2025年度营业收入为人民币16,883,810.25万元 [Evidence 1]。",
        [evidence],
    )

    assert "16,883,810.25万元" in result.answer
    assert "证据不足" not in result.answer
    assert result.claims[0].disposition == "SUPPORTED"


def test_main_business_revenue_is_not_duplicated_as_consolidated_revenue() -> None:
    from core.fact_ledger import FactLedger

    evidence = Evidence(
        content=(
            "2025年度，贵州茅台公司的营业收入为人民币16,883,810.25万元。"
            "其中主营业务收入为人民币16,877,458.52万元，占营业收入的99.96%。"
        ),
        source="贵州茅台_2025年度报告.pdf",
        company="贵州茅台",
        metadata={"chunk_id": "moutai-fy2025-revenue", "quarter": "FY2025"},
    )
    ledger = FactLedger.from_evidence([evidence])

    assert [fact.normalized_value for fact in ledger.lookup(metric_id="revenue")] == [
        168_838_102_500
    ]
    assert [
        fact.normalized_value
        for fact in ledger.lookup(metric_id="main_business_revenue")
    ] == [168_774_585_200]


def test_guizhou_moutai_alias_enforces_company_scope() -> None:
    from agent.planning.entity_extractor import extract_companies
    from core.citation_gate import filter_evidence_for_query

    question = "贵州茅台2025年度营业收入是多少？"
    target = _evidence(
        "贵州茅台2025年度营业收入为人民币16,883,810.25万元。",
        company="贵州茅台",
        period="FY2025",
    )
    unrelated = _evidence(
        "苹果公司2025年度营业收入为人民币1元。",
        company="Apple",
        period="FY2025",
    )

    assert extract_companies(question) == ["贵州茅台"]
    accepted = filter_evidence_for_query(question, [target, unrelated])
    assert [item.company for item in accepted] == ["贵州茅台"]


def test_chinese_iphone_category_claim_matches_filing_native_structured_row() -> None:
    from pathlib import Path

    from document_loader import get_document_period, load_pdf_chunks

    source = Path(__file__).resolve().parents[2] / "demo" / "documents" / "Apple_sample.pdf"
    chunks = load_pdf_chunks(source, ocr_enabled=False)
    chunk = next(chunk for chunk in chunks if "Metric: iPhone®" in str(chunk.text or ""))
    result = sanitize_answer(
        "总结苹果公司 2026 年第二季度的财务表现。",
        "苹果 Q2 FY2026 iPhone收入: 56.994 billion USD [Evidence 1].",
        [
            Evidence(
                content=str(chunk.text or ""),
                source=source.name,
                company="Apple",
                metadata={
                    "chunk_id": "apple-iphone",
                    "quarter": get_document_period(chunks),
                    "periods": get_document_period(chunks),
                    "metrics": "iphone_revenue",
                    "content_type": chunk.content_type,
                    "table_context": str(getattr(chunk, "table_context", "") or ""),
                },
            )
        ],
    )

    assert "56.994 billion" in result.answer
    assert result.unsupported_count == 0


def test_derived_numeric_claim_cites_only_operand_sources_not_the_whole_context() -> None:
    result = sanitize_answer(
        "How did NVIDIA revenue grow from Q1 FY2026 to Q1 FY2027?",
        "NVIDIA revenue grew 36% from $60B in Q1 FY2026 to $81.6B in Q1 FY2027.",
        [
            _evidence("NVIDIA Q1 FY2026 revenue was $60B.", period="Q1_FY2026"),
            _evidence("NVIDIA Q1 FY2027 revenue was $81.6B."),
            _evidence(
                "NVIDIA Q1 FY2027 gross margin was 70%.", metrics="gross_margin"
            ),
        ],
    )

    assert "36%" in result.answer
    assert "[Evidence 1]" in result.answer
    assert "[Evidence 2]" in result.answer
    assert "[Evidence 3]" not in result.answer
    assert result.unsupported_count == 0


def test_total_revenue_cannot_answer_data_center_performance_question() -> None:
    question = "What does NVIDIA report about Data Center performance in Q1 FY2027?"
    evidence = _evidence(
        "NVIDIA Q1 FY2027 total revenue was $81.615 billion USD. "
        "Data Center revenue was $75.2 billion USD, up 92% year over year.",
        metrics="revenue|data_center_revenue",
    )

    wrong_metric = sanitize_answer(
        question,
        "NVIDIA Q1 FY2027 revenue was $81.615 billion [Evidence 1].",
        [evidence],
    )
    assert "$81.615 billion" not in wrong_metric.answer
    assert wrong_metric.unsupported_count == 1

    correct_metric = sanitize_answer(
        question,
        "NVIDIA Q1 FY2027 Data Center revenue was $75.2 billion [Evidence 1].",
        [evidence],
    )
    assert "$75.2 billion" in correct_metric.answer
    assert correct_metric.unsupported_count == 0


def test_company_heading_context_blocks_wrong_issuer_numeric_bullet() -> None:
    """An implicit Apple bullet must not borrow Tesla's cited value."""

    rows = [
        _evidence(
            "Apple Q2 FY2026 net sales were $111.184 billion USD.",
            company="Apple",
            period="Q2_FY2026",
        ),
        _evidence(
            "Tesla Q4 2025 total quarterly revenue decreased 3% YoY to $24.9B.",
            company="Tesla",
            period="Q4_2025",
        ),
    ]
    result = sanitize_answer(
        "Which of Apple, NVIDIA and Tesla reports the strongest growth narrative?",
        "### 2. Apple: Moderate growth\n"
        "Revenue declined 3% YoY to $24.9B [Evidence 2].",
        rows,
        require_qualitative_citations=True,
    )

    assert "$24.9B" not in result.answer
    assert result.unsupported_count >= 1


def test_growth_ranking_inference_requires_growth_evidence_for_every_issuer() -> None:
    rows = [
        _evidence(
            "Apple Q2 FY2026 Services net sales increased due to higher advertising and App Store sales.",
            company="Apple",
            period="Q2_FY2026",
            metrics="revenue",
        ),
        _evidence(
            "NVIDIA Q1 FY2027 revenue was $81.6 billion, up 85% year over year. "
            "The buildout of AI factories is accelerating at extraordinary speed.",
            company="NVIDIA",
            period="Q1_FY2027",
            metrics="revenue",
        ),
        _evidence(
            "Tesla Q4 2025 total revenue decreased 3% YoY due to lower vehicle deliveries.",
            company="Tesla",
            period="Q4_2025",
            metrics="revenue",
        ),
    ]
    result = sanitize_answer(
        "Which of Apple, NVIDIA and Tesla reports the strongest growth narrative?",
        "NVIDIA reports the strongest growth narrative. [Evidence 2].",
        rows,
        require_qualitative_citations=True,
    )

    assert "strongest growth narrative" in result.answer.casefold()
    assert result.unsupported_count == 0
    assert result.answer.count("[Evidence") >= 3


def test_growth_ranking_rescue_does_not_validate_long_period_mixed_paragraph() -> None:
    rows = [
        _evidence(
            "Apple Q2 FY2026 Services net sales increased due to higher advertising and App Store sales.",
            company="Apple",
            period="Q2_FY2026",
            metrics="revenue",
        ),
        _evidence(
            "NVIDIA Q1 FY2027 revenue was $81.6 billion, up 85% year over year. "
            "The buildout of AI factories is accelerating at extraordinary speed.",
            company="NVIDIA",
            period="Q1_FY2027",
            metrics="revenue",
        ),
        _evidence(
            "Tesla Q4 2025 total revenue decreased 3% YoY due to lower vehicle deliveries.",
            company="Tesla",
            period="Q4_2025",
            metrics="revenue",
        ),
    ]
    result = sanitize_answer(
        "Which of Apple, NVIDIA and Tesla reports the strongest growth narrative?",
        (
            "Based on filings through early 2024, NVIDIA reports the strongest growth "
            "narrative by a wide margin, with an AI transformation and explosive results. "
            "[Evidence 1] [Evidence 2] [Evidence 3]"
        ),
        rows,
        require_qualitative_citations=True,
    )

    assert "through early 2024" not in result.answer
    assert "explosive results" not in result.answer
    assert result.unsupported_count >= 1


def test_query_metric_scope_allows_separate_metrics_in_comparison_questions() -> None:
    result = sanitize_answer(
        "Compare NVIDIA Q1 FY2027 revenue and net income.",
        "Revenue was $81.615 billion [Evidence 1]. Net income was $58.321 billion [Evidence 1].",
        [_evidence("NVIDIA Q1 FY2027 revenue $81.615 billion; net income $58.321 billion.")],
    )

    assert "$81.615 billion" in result.answer
    assert "$58.321 billion" in result.answer
    assert result.unsupported_count == 0


def test_wrong_value_is_replaced_with_insufficient_evidence() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA revenue was $91B.",
        [_evidence("NVIDIA Q1 FY2027 total revenue was $81.6 billion USD.")],
    )
    assert "$91B" not in result.answer
    assert "Insufficient evidence" in result.answer
    assert result.unsupported_count == 1


def test_repeated_sanitizer_refusals_are_compacted_without_hiding_claim_failures() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA Q1 FY2027 revenue was $91B.\nNVIDIA Q1 FY2027 revenue was $92B.",
        [_evidence("NVIDIA Q1 FY2027 total revenue was $81.6 billion USD.")],
    )

    assert result.answer.count("Insufficient evidence to support this numeric claim.") == 1
    assert result.unsupported_count == 2


def test_repeated_chinese_qualitative_refusals_are_compacted() -> None:
    result = sanitize_answer(
        "英伟达 Q1 FY2027 报告提到了哪些具体风险？",
        "报告披露了管理层观点 [Evidence 1]。\n报告披露了竞争优势 [Evidence 1]。",
        [_evidence("NVIDIA Q1 FY2027 total revenue was $81.6 billion USD.", metrics="revenue")],
        require_qualitative_citations=True,
    )

    assert result.answer.count("所引财报证据不足以支持该表述。") == 1
    assert result.unsupported_count == 2


def test_product_identifier_in_qualitative_risk_claim_is_not_numeric_refusal() -> None:
    result = sanitize_answer(
        "What risks or challenges are mentioned in Tesla's Q2 2025 report?",
        "Tesla faces supply-chain challenges caused by trade barriers and tariff risks, "
        "including battery packs with 4680 cells [Evidence 1].",
        [
            _evidence(
                "Tesla faces supply-chain challenges caused by trade barriers and tariff risks, "
                "including battery packs with 4680 cells.",
                company="Tesla",
                period="Q2_2025",
                metrics="",
            )
        ],
        require_qualitative_citations=True,
    )

    assert "4680 cells" in result.answer
    assert "Insufficient evidence to support this numeric claim." not in result.answer
    assert result.unsupported_count == 0


def test_wrong_period_cannot_support_claim() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA revenue was $90B.",
        [_evidence("NVIDIA Q2 FY2027 guidance was $90 billion USD.", period="Q2_FY2027")],
    )
    assert "$90B" not in result.answer
    assert result.evidence == []


def test_outlook_revenue_cannot_be_represented_as_reported_performance() -> None:
    result = sanitize_answer(
        "Compare Tesla and NVIDIA revenue performance.",
        "NVIDIA Q2 FY2027 revenue was $91 billion [Evidence 1].",
        [
            _evidence(
                "NVIDIA's outlook for Q2 FY2027: revenue is expected to be $91 billion.",
                period="Q2_FY2027",
            )
        ],
    )

    assert "$91 billion" not in result.answer
    assert "insufficient" in result.answer.casefold()
    assert result.unsupported_count == 1


def test_explicit_outlook_question_can_use_explicitly_labeled_guidance() -> None:
    result = sanitize_answer(
        "What was NVIDIA's Q2 FY2027 revenue outlook?",
        "NVIDIA expected Q2 FY2027 revenue to be $91 billion [Evidence 1].",
        [
            _evidence(
                "NVIDIA's outlook for Q2 FY2027: revenue is expected to be $91 billion.",
                period="Q2_FY2027",
            )
        ],
    )

    assert "$91 billion" in result.answer
    assert result.unsupported_count == 0


def test_actual_claim_can_use_actual_fact_from_chunk_that_also_contains_outlook() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA reported Q1 FY2027 revenue of $81.6 billion [Evidence 1].",
        [
            _evidence(
                "NVIDIA reported Q1 FY2027 revenue of $81.6 billion. "
                "Its Q2 FY2027 outlook says revenue is expected to be $91 billion.",
                period="Q1_FY2027",
            )
        ],
    )

    assert "$81.6 billion" in result.answer
    assert "$91 billion" not in result.answer
    assert result.unsupported_count == 0


def test_spelled_out_fiscal_quarter_rejects_following_quarter_guidance():
    result = sanitize_answer(
        "What drove the chip company's data-center business in its first fiscal quarter of 2027?",
        "NVIDIA Q2 FY2027 revenue was 91 billion USD [Evidence 1].",
        [
            _evidence(
                "NVIDIA Q2 FY2027 outlook: revenue is expected to be $91 billion USD.",
                period="Q2_FY2027",
            )
        ],
    )

    assert "91 billion" not in result.answer
    assert result.evidence == []
    assert result.unsupported_count == 1


def test_wrong_company_cannot_support_claim() -> None:
    result = sanitize_answer(
        "What was Apple revenue in Q1 FY2027?",
        "Apple revenue was $81.6B.",
        [_evidence("NVIDIA Q1 FY2027 total revenue was $81.6 billion USD.")],
    )
    assert "$81.6B" not in result.answer
    assert result.evidence == []


def test_wrong_company_qualitative_clause_is_removed_without_citation_marker() -> None:
    question = (
        "What did it say about margins?\n"
        "Relevant prior user request for reference resolution: "
        "Tell me about Tesla's Q2 2025 performance."
    )
    result = sanitize_answer(
        question,
        "Apple Inc.'s Q2 2026 Services gross margin percentage increased "
        "compared with Q2 2025, partly due to service mix [Evidence 1].",
        [_evidence("Tesla Q2 2025 gross margin was 17.2%.", "Tesla", "Q2_2025", "gross_margin")],
    )

    assert "Apple" not in result.answer
    assert "Services gross margin percentage increased" not in result.answer
    assert "insufficient" in result.answer.casefold()
    assert result.claims[0].disposition == "UNSUPPORTED"


def test_wrong_period_qualitative_clause_is_removed() -> None:
    result = sanitize_answer(
        "What did Tesla report about gross margin in Q2 2025?",
        "In Q4 2025, Tesla's gross margin improved according to the filing [Evidence 1].",
        [_evidence("Tesla Q2-2025 gross margin was 17.2%.", "Tesla", "Q2_2025", "gross_margin")],
    )

    assert "Q4 2025" not in result.answer
    assert "gross margin improved" not in result.answer
    assert "insufficient" in result.answer.casefold()
    assert result.claims[0].disposition == "UNSUPPORTED"


def test_period_specific_prose_cannot_cite_later_filing_risk_disclosure() -> None:
    later_filing = _evidence(
        "Tesla Q4 FY2025 risk factors include export controls and regulatory changes.",
        company="Tesla",
        period="Unknown",
        metrics="risk",
    )
    result = sanitize_answer(
        "What risks or challenges are mentioned in Tesla's Q2 2025 report?",
        "Tesla's Q2 2025 report identifies export controls and regulatory changes as risks [Evidence 1].",
        [later_filing],
    )

    assert "export controls" not in result.answer
    assert "regulatory changes" not in result.answer
    assert "Evidence 1" not in result.answer
    assert "insufficient" in result.answer.casefold()
    assert result.claims[0].disposition == "UNSUPPORTED"


def test_period_specific_prose_keeps_same_period_source() -> None:
    same_period = _evidence(
        "Tesla Q2 2025 risk discussion identifies production ramp challenges.",
        company="Tesla",
        period="Unknown",
        metrics="risk",
    )
    result = sanitize_answer(
        "What risks or challenges are mentioned in Tesla's Q2 2025 report?",
        "Tesla's Q2 2025 risk discussion identifies production ramp challenges [Evidence 1].",
        [same_period],
    )

    assert "production ramp challenges" in result.answer
    assert "[Evidence 1]" in result.answer
    assert result.claims[0].disposition == "NON_NUMERIC"


def test_multi_metric_amounts_cannot_be_validated_against_a_union_of_values() -> None:
    row = _evidence(
        "NVIDIA Q1 FY2027 revenue was $81.6 billion; net income was $58.3 billion.",
        metrics="revenue|net_income",
    )
    result = sanitize_answer(
        "Summarize NVIDIA Q1 FY2027 revenue and net income.",
        "NVIDIA Q1 FY2027 revenue was $58.3 billion and net income was $81.6 billion [Evidence 1].",
        [row],
    )

    assert "$58.3 billion" not in result.answer
    assert "$81.6 billion" not in result.answer
    assert result.unsupported_count == 1


def test_equivalent_units_are_supported() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA revenue was 81,600 million USD.",
        [_evidence("NVIDIA Q1 FY2027 total revenue was $81.6B.")],
    )
    assert result.claims[0].disposition == "SUPPORTED"


def test_derived_growth_is_retained_only_when_deterministic() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue growth?",
        "Revenue grew 20.0% year over year.",
        [_evidence("Current revenue $120B; prior revenue $100B.")],
    )
    assert "20.0%" in result.answer
    assert result.claims[0].disposition == "DERIVABLE"


def test_multi_company_claims_require_matching_company_evidence() -> None:
    result = sanitize_answer(
        "Compare Apple and NVIDIA revenue in Q1 FY2027.",
        "Apple revenue was $100B. NVIDIA revenue was $81.6B.",
        [
            _evidence("Apple Q1 FY2027 total revenue was $100B.", "Apple"),
            _evidence("NVIDIA Q1 FY2027 total revenue was $81.6B.", "NVIDIA"),
        ],
    )
    assert "Apple revenue was $100B [Evidence 1]." in result.answer
    assert "NVIDIA revenue was $81.6B [Evidence 2]." in result.answer
    assert result.unsupported_count == 0


def test_chinese_citation_comma_keeps_each_supported_clause() -> None:
    evidence = [
        _evidence(
            "NVIDIA Q1 FY2027 revenue $75.2B, up 92%.",
            metrics="revenue",
        ),
        _evidence(
            "NVIDIA Q1 FY2027 revenue $60.4B, up 77%.",
            metrics="revenue",
        ),
    ]
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "Revenue was $75.2B, up 92% [Evidence 1]，Revenue was $60.4B, up 77% [Evidence 2].",
        evidence,
    )
    assert "$75.2B" in result.answer
    assert "$60.4B" in result.answer
    assert result.unsupported_count == 0


def test_spaced_decimal_and_explanatory_parentheses_normalize() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "Revenue was $81.6B (i.e., 81,600 million USD).",
        [_evidence("NVIDIA Q1 FY2027 revenue was $81. 6 billion USD.")],
    )
    assert result.unsupported_count == 0
    assert "$81.6B" in result.answer


def test_page_numbers_and_citation_labels_are_not_numeric_claims() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "See page 3 [Evidence 1]. Revenue was $81.6B [Evidence 1].",
        [_evidence("NVIDIA Q1 FY2027 revenue was $81.6 billion USD.")],
    )
    assert result.unsupported_count == 0
    assert "$81.6B" in result.answer


def test_filing_calendar_date_is_not_mistaken_for_an_unsupported_financial_amount() -> None:
    row = _evidence(
        "NVIDIA CORPORATION\nThree Months Ended April 26, 2026, "
        "April 27, 2025\nRevenue $81,615 $44,062"
    )
    row.metadata["quarter"] = "Q1_FY2027"
    row.metadata["chunk_id"] = "nvidia-q1-income-statement"
    result = sanitize_answer(
        "Summarize NVIDIA's financial performance in Q1 FY2027.",
        "NVIDIA reported results for the three months ended April 26, 2026, "
        "its first quarter of fiscal 2027 (Q1 FY2027) [Evidence 1].",
        [row],
    )

    assert "reported results for the three months ended April 26, 2026" in result.answer
    assert "[Evidence 1]" in result.answer
    assert result.unsupported_count == 0


def test_explicit_citations_are_pruned_to_numeric_supporting_chunks() -> None:
    result = sanitize_answer(
        "What was NVIDIA revenue in Q1 FY2027?",
        "Revenue was $81.6B [Evidence 1] [Evidence 2].",
        [
            _evidence("NVIDIA Q1 FY2027 revenue was $81.6 billion USD."),
            _evidence("NVIDIA Q2 FY2027 outlook discusses gross margin only."),
        ],
    )
    assert "[Evidence 1]" in result.answer
    assert "[Evidence 2]" not in result.answer


def test_explicit_citation_with_unverified_period_cannot_support_prose_claim() -> None:
    stale_file_period = Evidence(
        content=(
            "FORWARD-LOOKING STATEMENTS: risks relating to regulations, indebtedness, "
            "financing strategies, and adverse foreign exchange movements."
        ),
        source="Tesla_Q2_2025.pdf",
        company="Tesla",
        metadata={"company": "Tesla", "quarter": "Unknown", "chunk_id": "tesla-risk"},
    )
    result = sanitize_answer(
        "What risks are disclosed in Tesla's Q2 2025 report?",
        "Tesla's Q2 2025 report disclosed regulatory and financing risks [Evidence 1].",
        [stale_file_period],
    )

    assert "regulatory and financing risks" not in result.answer
    assert "insufficient" in result.answer.casefold()
    assert "[Evidence" not in result.answer
    assert result.claims[0].disposition == "UNSUPPORTED"


def test_no_evidence_response_is_localized_and_does_not_invent_company_facts() -> None:
    chinese = no_evidence_response("分析阿里巴巴最新季度的财务表现。")
    english = no_evidence_response("Analyze Alibaba's latest quarterly performance.")

    assert "没有找到足以支持该问题的证据" in chinese
    assert "请上传相关公司及报告期的财报" in chinese
    assert "Alibaba" not in chinese
    assert "No relevant uploaded-filing evidence was retrieved" in english
    assert "Upload the relevant company's filing" in english


def test_safe_policy_refusals_are_not_classified_as_unsupported_claims() -> None:
    responses = (
        (
            "What was Tesla's market share?",
            "The available filing evidence does not establish the requested metric: market share.",
        ),
        (
            "特斯拉市场份额是多少？",
            "现有财报证据未能证明所询市场份额，无法可靠作答。",
        ),
    )
    for question, answer in responses:
        result = sanitize_answer(question, answer, [], require_qualitative_citations=True)
        assert result.answer == answer
        assert result.unsupported_count == 0


def test_strict_qualitative_mode_treats_blank_lines_as_layout_not_claims() -> None:
    source = "The buildout of AI factories is accelerating at extraordinary speed."
    result = sanitize_answer(
        "Why did NVIDIA's business grow in Q1 FY2027?",
        "### Source excerpt\n\n“" + source + "” [Evidence 1]",
        [_evidence(source)],
        require_qualitative_citations=True,
    )

    assert source in result.answer
    assert result.unsupported_count == 0


def test_qualitative_citation_cannot_substitute_operating_margin_for_gross_margin() -> None:
    question = "Summarize Tesla profitability in Q2 2025."
    claim = "Tesla Q2 2025 gross margin improved [Evidence 1]."
    operating_margin = sanitize_answer(
        question,
        claim,
        [_evidence(
            "Tesla Q2 2025 operating margin improved as operating expenses declined.",
            company="Tesla",
            period="Q2_2025",
            metrics="operating_margin",
        )],
        require_qualitative_citations=True,
    )
    gross_margin = sanitize_answer(
        question,
        claim,
        [_evidence(
            "Tesla Q2 2025 gross margin improved as production costs declined.",
            company="Tesla",
            period="Q2_2025",
            metrics="gross_margin",
        )],
        require_qualitative_citations=True,
    )

    assert "gross margin improved" not in operating_margin.answer
    assert operating_margin.unsupported_count == 1
    assert "gross margin improved" in gross_margin.answer
    assert gross_margin.unsupported_count == 0


def test_multi_metric_prose_can_be_supported_by_complementary_evidence_chunks() -> None:
    result = sanitize_answer(
        "Summarize NVIDIA's Q1 FY2027 financial performance.",
        "Revenue increased and gross margin improved [Evidence 1] [Evidence 2].",
        [
            _evidence("NVIDIA Q1 FY2027 revenue increased year over year."),
            _evidence("NVIDIA Q1 FY2027 gross margin improved."),
        ],
        require_qualitative_citations=True,
    )

    assert "Revenue increased" in result.answer
    assert "gross margin improved" in result.answer
    assert "[Evidence 1]" in result.answer
    assert "[Evidence 2]" in result.answer
    assert result.unsupported_count == 0


def test_multi_metric_prose_is_rejected_when_one_metric_lacks_matching_evidence() -> None:
    result = sanitize_answer(
        "Summarize NVIDIA's Q1 FY2027 financial performance.",
        "Revenue increased and gross margin improved [Evidence 1] [Evidence 2].",
        [
            _evidence("NVIDIA Q1 FY2027 revenue increased year over year."),
            _evidence("NVIDIA Q1 FY2027 operating margin improved."),
        ],
        require_qualitative_citations=True,
    )

    assert "Revenue increased and gross margin improved" not in result.answer
    assert "[Evidence" not in result.answer
    assert result.unsupported_count == 1


def test_headerless_comparative_financial_table_requires_periods_on_each_row() -> None:
    row = _evidence(
        "Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025 YoY\n"
        "Total automotive revenues 19,798 13,967 16,661 21,205 17,693 -11%",
        company="Tesla",
        period="Q4_2025",
        metrics="revenue",
    )
    row.metadata["periods"] = "Q4_2024|Q1_2025|Q2_2025|Q3_2025|Q4_2025"
    row.metadata["table_context"] = (
        "(USD in millions); Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025 YoY"
    )
    row.metadata["content_type"] = "table"

    result = sanitize_answer(
        "Tesla Q1 2025 revenue growth trend?",
        "| Automotive revenue | $19,798 million | $13,967 million | "
        "-$5,831 million, -29.5% | [Evidence 1]",
        [row],
    )

    assert "$19,798 million" not in result.answer
    assert "$13,967 million" not in result.answer
    assert "-29.5%" not in result.answer
    assert result.unsupported_count == 1
