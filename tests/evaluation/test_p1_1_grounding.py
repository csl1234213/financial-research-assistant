from decimal import Decimal

from agent.planning.entity_extractor import extract_companies
from core.financial_grounding import (
    NormalizedNumber,
    canonical_metric,
    derived_growth,
    extract_normalized_numbers,
    metric_matches,
    numbers_equivalent,
)
from core.query_scope import QueryScope, classify_query_scope
from core.required_fact_plan import infer_required_fact_plan
from evaluation.p1_1_grounding import _resolved_evaluation_question
from evaluation.replay_formal_100_offline import _resolved_evidence_question, replay_one
from retrieval.hybrid_retriever import HybridRetriever
from storage.vector_models import SearchResult


def test_chinese_followup_evaluation_query_inherits_the_recorded_setup_company():
    case = {
        "question": "现在把它跟特斯拉比较一下。",
        "setup_question": "分析一下苹果这份财报。",
    }

    resolved = _resolved_evaluation_question(case)

    assert "苹果这份财报" in resolved
    assert set(extract_companies(resolved)) == {"Tesla", "Apple"}


def test_historical_grounding_replay_uses_latest_followup_intent_and_guarded_context():
    row = {
        "question": "Focus only on the business growth drivers.",
        "original_question": "Compare Apple and NVIDIA.\nFocus only on the business growth drivers.",
        "setup_question": "Compare Apple and NVIDIA.",
    }

    resolved = _resolved_evidence_question(row)

    assert resolved.startswith("Focus only on the business growth drivers.")
    assert "Relevant prior user request for reference resolution: Compare Apple and NVIDIA." in resolved
    assert classify_query_scope(resolved) is QueryScope.ANALYSIS


def test_formal_replay_does_not_reclassify_direct_chat_examples_as_financial_claims():
    result = replay_one(
        {
            "id": "ZH-044",
            "language": "zh",
            "question": "什么叫毛利率？",
            "actual_answer": "毛利率是收入扣除直接成本后占收入的比例。例如收入100元、成本60元时为40%。",
            "citations": [],
        },
        {},
        {},
    )

    assert classify_query_scope(result["evidence_question"]) is QueryScope.GENERAL_CONCEPT
    assert result["final_unsupported_numeric_claims"] == 0
    assert result["final_claim_dispositions"].get("UNSUPPORTED", 0) == 0


def test_bilingual_driver_followups_do_not_inherit_numeric_plan_from_prior_turn():
    english = _resolved_evidence_question({
        "question": "Focus only on the business growth drivers.",
        "setup_question": "Compare Apple and NVIDIA.",
    })
    chinese = _resolved_evidence_question({
        "question": "只重点比较它们的业务增长动力。",
        "setup_question": "比较苹果和英伟达的财务表现。",
    })

    english_plan = infer_required_fact_plan(english, [])
    chinese_plan = infer_required_fact_plan(chinese, [])

    assert english_plan.scope == QueryScope.ANALYSIS.value
    assert chinese_plan.scope == QueryScope.COMPARE.value
    assert english_plan.required == chinese_plan.required == ()


def test_numeric_normalization_handles_financial_scales_and_parentheses():
    values = extract_normalized_numbers("$81.6B, 81.6 billion USD, $81,600 million, 81,600M")
    assert len(values) == 4
    assert all(value.value == Decimal("81600000000") for value in values)
    assert numbers_equivalent(values[0], values[1])
    assert numbers_equivalent(values[1], values[2])
    assert numbers_equivalent(values[2], values[3])

    negative = extract_normalized_numbers("(200) million USD")[0]
    assert negative.value == Decimal("-200000000")
    assert extract_normalized_numbers("$81.6M")[0].value != values[0].value


def test_rounded_financial_claim_matches_only_within_its_display_precision():
    rounded = extract_normalized_numbers("$81.6B")[0]
    exact_millions = extract_normalized_numbers("81,615 million USD")[0]
    adjacent_tenth = extract_normalized_numbers("$81.7B")[0]
    wrong_scale = extract_normalized_numbers("$81.6M")[0]

    assert numbers_equivalent(rounded, exact_millions)
    assert not numbers_equivalent(rounded, adjacent_tenth)
    assert not numbers_equivalent(rounded, wrong_scale)


def test_numeric_normalization_keeps_percent_and_basis_amounts_distinct():
    percent = extract_normalized_numbers("74.9%")[0]
    amount = extract_normalized_numbers("74.9 million USD")[0]
    basis_points = extract_normalized_numbers("50 basis points")[0]
    assert percent.kind == "percent"
    assert amount.kind == "amount"
    assert basis_points.kind == "basis_points"
    assert not numbers_equivalent(percent, amount)


def test_numeric_normalization_ignores_pdf_footer_numbers():
    assert extract_normalized_numbers("Apple Inc. | Q2 2026 Form 10-Q | 16") == []


def test_metric_aliases_do_not_merge_distinct_financial_measures():
    assert canonical_metric("total revenues") == "revenue"
    assert canonical_metric("automotive revenue") == "automotive_revenue"
    assert canonical_metric("income from operations") == "operating_income"
    assert metric_matches("What was total revenue?", "Total revenue was $10 billion.")
    assert not metric_matches("What was total revenue?", "Automotive revenue was $10 billion.")


def test_derived_growth_is_deterministic():
    result = derived_growth(
        NormalizedNumber(Decimal("22496")),
        NormalizedNumber(Decimal("19335")),
    )
    assert result is not None
    assert result.kind == "percent"
    assert round(result.value, 1) == Decimal("16.3")


def _result(chunk_id: str, score: float, content: str, **metadata) -> SearchResult:
    return SearchResult(
        document_id="doc",
        chunk_id=chunk_id,
        score=score,
        content=content,
        metadata={"company": "Tesla", "source": "Tesla_Q2_2025.pdf", **metadata},
    )


def test_coverage_aware_rerank_preserves_company_period_metric_when_available():
    results = [
        _result("semantic", 1.0, "A generic performance discussion."),
        _result("period", 0.99, "Q2-2025 revenue was reported.", quarter="Q2_2025"),
        _result("metric", 0.98, "Revenue and gross margin were reported."),
    ]
    ranked = HybridRetriever.coverage_aware_rerank(
        results,
        "Tesla Q2 2025 revenue",
        top_k=2,
    )
    assert {item.chunk_id for item in ranked} == {"period", "metric"}


def test_fact_ledger_does_not_treat_share_counts_as_eps():
    from agent.reasoning_models import Evidence
    from core.fact_ledger import FactLedger

    evidence = Evidence(
        content=(
            "Shares used in computing earnings per share: "
            "Basic 14,673,278 14,994,082; Diluted 14,725,873 15,056,133"
        ),
        source="Apple_Q2_2026.pdf",
        company="Apple",
        metadata={"chunk_id": "shares", "quarter": "Q2_2026"},
    )

    assert not FactLedger.from_evidence([evidence]).facts


def test_period_matched_public_filing_beats_unversioned_tenant_duplicate():
    results = [
        _result(
            "tenant-copy",
            0.95,
            "Tesla revenue was reported.",
            tenant_id=7,
            source_authority="tenant_upload",
        ),
        _result(
            "public-filing",
            0.88,
            "Tesla Q2-2025 total revenue was $22,496 million.",
            tenant_id=0,
            source_authority="public_filing",
            periods="Q2_2025",
            quarter="Q2_2025",
        ),
    ]

    ranked = HybridRetriever.coverage_aware_rerank(
        results,
        "Tesla Q2 2025 revenue",
        top_k=1,
    )

    assert ranked[0].chunk_id == "public-filing"
