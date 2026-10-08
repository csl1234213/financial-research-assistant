from agent.reasoning_models import Evidence
from core.answer_grounding import sanitize_answer
from core.citation_gate import filter_evidence_for_query, validate_answer_evidence
from core.context_builder import build_context_from_evidence
from core.core_engine import _evidence_cited_by_answer, _project_answer_citations


def test_gate_rejects_wrong_company_and_period_evidence():
    evidence = [
        Evidence(
            content="Apple Q2 2026 revenue was $111,184 million.",
            source="Apple_Q2_2026.pdf",
            company="Apple",
            metadata={"page": 14},
        ),
        Evidence(
            content="Tesla FINANCIAL SUMMARY Q1-2025 Q2-2025 Total revenues 22,496.",
            source="Tesla_Q2_2025.pdf",
            company="Tesla",
            metadata={"page": 4},
        ),
    ]
    filtered = filter_evidence_for_query(
        "What was Tesla revenue in Q2 2025?",
        evidence,
    )
    assert [item.source for item in filtered] == ["Tesla_Q2_2025.pdf"]


def test_explicit_source_only_constraint_fails_closed_on_disallowed_company():
    evidence = [
        Evidence(
            content="NVIDIA Q1 FY2027 revenue was $81.6 billion.",
            source="NVIDIA_Q1_FY2027.pdf",
            company="NVIDIA",
            metadata={"page": 1},
        ),
        Evidence(
            content="Apple Q2 FY2026 net sales were $111,184 million.",
            source="Apple_Q2_2026.pdf",
            company="Apple",
            metadata={"page": 1},
        ),
    ]

    filtered = filter_evidence_for_query(
        "What was NVIDIA's Q1 FY2027 revenue? Use only Apple's financial reports.",
        evidence,
    )

    assert filtered == []


def test_gate_keeps_an_explicit_unverified_fallback_instead_of_empty_context():
    evidence = [
        Evidence(
            content="Tesla operational summary for 2025.",
            source="Tesla_Q2_2025.pdf",
            company="Tesla",
            metadata={"page": 6},
        )
    ]
    filtered = filter_evidence_for_query("Tesla Q2 2025 gross margin", evidence)
    assert len(filtered) == 1
    assert filtered[0].metadata["semantic_support"] == "unverified"


def test_risk_question_keeps_document_level_risk_context_with_period_caveat():
    evidence = [
        Evidence(
            content=(
                "Forward-looking statements identify risks relating to tariffs, "
                "regulations, indebtedness and adverse foreign exchange movements."
            ),
            source="Tesla_Q4_FY2025_Update.pdf",
            company="Tesla",
            metadata={"page": 34, "chunk_id": "tesla-risk-factors"},
        )
    ]

    filtered = filter_evidence_for_query(
        "What risks or challenges are mentioned in Tesla's Q2 2025 report?",
        evidence,
    )

    assert len(filtered) == 1
    assert filtered[0].metadata["semantic_support"] == "related_context"
    assert "requested reporting period" in filtered[0].metadata["semantic_support_reason"]


def test_risk_question_keeps_known_period_document_context_without_filename_period():
    evidence = [
        Evidence(
            content=(
                "Forward-looking statements identify risks relating to tariffs, "
                "regulations, indebtedness and adverse foreign exchange movements."
            ),
            source="Tesla_sample.pdf",
            company="Tesla",
            metadata={"page": 34, "chunk_id": "tesla-risk-factors", "quarter": "Q4_2025"},
        )
    ]

    filtered = filter_evidence_for_query(
        "What risks or challenges are mentioned in Tesla's Q2 2025 report?",
        evidence,
    )

    assert len(filtered) == 1
    assert filtered[0].metadata["semantic_support"] == "related_context"


def test_risk_context_answer_discloses_that_period_is_not_specific():
    from core.answer_policy import finalize_grounded_answer

    row = Evidence(
        content=(
            "Forward-looking statements identify risks relating to tariffs, "
            "regulations, indebtedness and adverse foreign exchange movements."
        ),
        source="Tesla_Q4_FY2025_Update.pdf",
        company="Tesla",
        metadata={"page": 34, "chunk_id": "tesla-risk-factors"},
    )
    filtered = filter_evidence_for_query(
        "What risks or challenges are mentioned in Tesla's Q2 2025 report?",
        [row],
    )
    result = finalize_grounded_answer(
        "What risks or challenges are mentioned in Tesla's Q2 2025 report?",
        "The report mentions risks relating to tariffs and regulations [Evidence 1].",
        filtered,
    )

    assert "general risk disclosures" in result.answer
    assert "not identify risks specific" in result.answer
    assert result.grounded.unsupported_count == 0


def test_risk_context_wrong_language_rebuilds_a_cited_source_excerpt():
    from core.answer_policy import finalize_grounded_answer

    row = Evidence(
        content=(
            "Forward-looking statements identify risks relating to tariffs, "
            "regulations, indebtedness and adverse foreign exchange movements."
        ),
        source="Tesla_Q4_FY2025_Update.pdf",
        company="Tesla",
        metadata={"page": 34, "chunk_id": "tesla-risk-factors"},
    )
    question = "What risks or challenges are mentioned in Tesla's Q2 2025 report?"
    filtered = filter_evidence_for_query(question, [row])
    result = finalize_grounded_answer(
        question,
        "财报提到监管、关税和融资风险。[Evidence 1]",
        filtered,
    )

    assert "Related general risk disclosures" in result.answer
    assert "tariffs" in result.answer
    assert "not period-specific" in result.answer
    assert result.grounded.unsupported_count == 0


def test_related_risk_context_keeps_excerpt_when_chinese_model_draft_cannot_be_grounded():
    from core.answer_policy import finalize_grounded_answer

    row = Evidence(
        content=(
            "Forward-looking statements identify risks relating to tariffs, "
            "regulations, indebtedness and adverse foreign exchange movements."
        ),
        source="Tesla_Q4_FY2025_Update.pdf",
        company="Tesla",
        metadata={
            "page": 34,
            "chunk_id": "tesla-related-risk",
            "semantic_support": "related_context",
        },
    )
    question = "特斯拉 2025 年第二季度财报提到了哪些风险或挑战？"
    result = finalize_grounded_answer(
        question,
        "Evidence-grounded risk answer: 监管、关税、融资和汇率风险。",
        [row],
    )

    assert "财报风险背景" in result.answer
    assert "tariffs" in result.answer
    assert result.grounded.unsupported_count == 0


def test_stale_document_period_cannot_ground_a_conflicting_quarter_claim():
    evidence = [
        Evidence(
            content="Tesla Q4 2025 highlights: total revenue was $24.9 billion.",
            source="Tesla_Q2_2025.pdf",
            company="Tesla",
            metadata={
                "company": "Tesla",
                "quarter": "Q2_2025",
                "periods": "Q4_2025",
                "chunk_id": "tesla-q4-highlights",
            },
        )
    ]

    filtered = filter_evidence_for_query("What was Tesla revenue in Q2 2025?", evidence)
    assert filtered[0].metadata["semantic_support"] == "unverified"

    result = sanitize_answer(
        "What was Tesla revenue in Q2 2025?",
        "Tesla's Q2 2025 revenue was $24.9 billion [Evidence 1].",
        evidence,
    )
    assert "$24.9 billion" not in result.answer
    assert "[Evidence" not in result.answer
    assert result.unsupported_count == 1


def test_comparative_table_containing_requested_period_remains_eligible():
    evidence = [
        Evidence(
            content=(
                "Tesla financial summary Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025 "
                "Total revenues 25,707 19,335 22,496 28,095 24,901 million."
            ),
            source="Tesla_Q2_2025.pdf",
            company="Tesla",
            metadata={"company": "Tesla", "quarter": "Q2_2025", "chunk_id": "tesla-summary-table"},
        )
    ]

    filtered = filter_evidence_for_query("What was Tesla revenue in Q2 2025?", evidence)
    assert len(filtered) == 1
    assert filtered[0].metadata["semantic_support"] == "supported"


def test_unverified_flattened_financial_table_never_enters_context_or_fallback():
    evidence = [
        Evidence(
            content=(
                "Tesla Q4-2024 Q1-2025 Q2-2025 revenue 25,707 19,335 22,496. "
                "Gross margin 16.3% 16.3% 17.2%."
            ),
            source="Tesla_sample.pdf",
            company="Tesla",
            confidence=0.99,
            metadata={"page": 4, "content_type": "unverified_table"},
        )
    ]

    assert filter_evidence_for_query("Tesla Q2 2025 revenue", evidence) == []


def test_claim_gate_does_not_accept_numeric_claim_absent_from_evidence():
    evidence = [
        Evidence(
            content="NVIDIA Q1 FY2027 revenue was $81.6 billion.",
            source="NVIDIA_Q1_FY2027.pdf",
            company="NVIDIA",
            metadata={"page": 1},
        )
    ]
    checked = validate_answer_evidence(
        "What was NVIDIA revenue in Q1 FY2027?",
        "NVIDIA revenue was $91.0 billion.",
        evidence,
    )
    assert checked[0].metadata["claim_support"] == "unverified"


def test_public_filing_replaces_byte_equivalent_tenant_upload():
    tenant = Evidence(
        content="Tesla Q2 2025 total revenues 22,496 million.",
        source="Tesla_sample.pdf",
        company="Tesla",
        confidence=0.99,
        metadata={"source_authority": "tenant_upload", "tenant_id": 7},
    )
    public = Evidence(
        content="Tesla Q2 2025 total revenues 22,496 million.",
        source="Tesla_Q2_2025.pdf",
        company="Tesla",
        confidence=0.80,
        metadata={"source_authority": "public_filing", "tenant_id": 0},
    )
    filtered = filter_evidence_for_query(
        "What was Tesla revenue in Q2 2025?", [tenant, public]
    )
    assert [item.source for item in filtered] == ["Tesla_Q2_2025.pdf"]
    assert filtered[0].metadata["source_authority_selection"] == "public_filing_preferred"


def test_non_duplicate_tenant_upload_is_preserved():
    tenant = Evidence(
        content="Tesla management discussion for Q3 2025.",
        source="Tesla_private_notes.pdf",
        company="Tesla",
        metadata={"source_authority": "tenant_upload", "tenant_id": 7},
    )
    filtered = filter_evidence_for_query("Tesla Q3 2025 outlook", [tenant])
    assert filtered[0].source == "Tesla_private_notes.pdf"


def test_all_chunks_of_duplicate_tenant_document_are_suppressed():
    public = Evidence(
        content="Public filing Q2 2025 narrative.",
        source="Tesla_Q2_2025.pdf",
        company="Tesla",
        metadata={
            "source_authority": "public_filing",
            "tenant_id": 0,
            "content_sha256": "a" * 64,
            "chunk_id": "public_" + "a" * 64 + "_5",
        },
    )
    tenant = Evidence(
        content="Private parser produced a different Q2 2025 chunk boundary.",
        source="Tesla_sample.pdf",
        company="Tesla",
        metadata={
            "source_authority": "tenant_upload",
            "tenant_id": 7,
            "content_sha256": "a" * 64,
            "chunk_id": "tenant_7_" + "a" * 64 + "_56",
        },
    )
    filtered = filter_evidence_for_query("Tesla Q2 2025 outlook", [tenant, public])
    assert [item.source for item in filtered] == ["Tesla_Q2_2025.pdf"]


def test_api_citations_only_include_chunks_bound_to_final_answer():
    evidence = [
        Evidence(content="Claim source", source="used.pdf", company="Tesla", metadata={"chunk_id": "used"}),
        Evidence(content="Unused retrieval result", source="unused.pdf", company="Tesla", metadata={"chunk_id": "unused"}),
    ]

    assert _evidence_cited_by_answer("Tesla reported the supported fact. [Evidence 1]", evidence) == [evidence[0]]
    assert _evidence_cited_by_answer("Tesla reported an uncited statement.", evidence) == []
    assert _evidence_cited_by_answer("Tesla reported this. [Evidence 9]", evidence) == []


def test_api_citation_projection_compacts_answer_ranks_after_unused_chunks_are_removed():
    evidence = [
        Evidence(content=f"Evidence {index}", source=f"source-{index}.pdf", company="Tesla",
                 metadata={"chunk_id": str(index)})
        for index in range(1, 5)
    ]

    answer, projected = _project_answer_citations(
        "First claim [Evidence 2]. Second claim [Evidence 4].", evidence
    )

    assert [item.metadata["chunk_id"] for item in projected] == ["2", "4"]
    assert answer == "First claim [Evidence 1]. Second claim [Evidence 2]."
    context, citations = build_context_from_evidence(projected)
    assert [citation["rank"] for citation in citations] == [1, 2]
    assert "[Evidence 1]" in context and "[Evidence 2]" in context
    assert "[Evidence 3]" not in answer


def test_api_citation_projection_removes_invalid_reference_and_handles_no_references():
    evidence = [Evidence(content="Evidence", source="source.pdf", company="Tesla", metadata={"chunk_id": "1"})]

    answer, projected = _project_answer_citations("Claim [Evidence 8].", evidence)
    assert answer == "Claim ."
    assert projected == []

    answer, projected = _project_answer_citations("A plain answer.", evidence)
    assert answer == "A plain answer."
    assert projected == []
