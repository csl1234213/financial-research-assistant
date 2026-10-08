from datetime import datetime, timezone

import httpx

from evaluation.live_100 import (
    actual_cost,
    application_success,
    response_data,
    response_failure,
)
from evaluation.semantic_review import (
    SYSTEM,
    main_answer,
    normalize_grade,
    normalized,
    validate_citation_annotation,
)


def test_supplementary_agent_evidence_is_not_the_main_answer():
    assert main_answer("actual answer\n## Agent Evidence Analysis\nother facts") == "actual answer\n"


def test_bare_evidence_list_is_not_treated_as_an_answer_citation():
    report = "Claim without inline citation.\nEvidence Used\n[Evidence 1]\n"
    answer = main_answer(report)
    assert "[Evidence 1]" not in answer


def test_quote_normalization_does_not_change_numbers():
    assert normalized("Net   sales\n111,184") == "Net sales 111,184"


def test_non_json_http_500_is_recorded_instead_of_crashing_batch():
    result = response_data(httpx.Response(500, text="Internal Server Error"))
    assert result["error_type"] == "NON_JSON_HTTP_RESPONSE"


def test_actual_cache_usage_uses_verified_peak_prices():
    usage = {
        "complete": True,
        "calls": [
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cached_tokens": 500,
            }
        ],
    }
    assert actual_cost(usage, datetime(2026, 9, 14, 2, tzinfo=timezone.utc)) == 0.000273


def test_unavailable_cache_or_token_usage_keeps_cost_unknown():
    assert actual_cost({"complete": False}, datetime.now(timezone.utc)) is None


def test_runtime_fallback_is_failure_even_when_http_status_is_200():
    assert response_failure(200, {"report": "[Agent Runtime Fallback] Unable to process"}) == "RUNTIME_FALLBACK"


def test_provider_error_is_not_mislabelled_as_runtime_fallback():
    assert response_failure(200, {"report": "[Provider Error] Upstream unavailable"}) == "PROVIDER_ERROR"


def test_empty_model_body_is_failure_even_with_supplementary_evidence():
    assert response_failure(200, {"report": "当前模型未返回可用内容。\n## 关键事实\nRevenue"}) == "EMPTY_MODEL_CONTENT"


def test_regular_response_is_not_failure():
    assert response_failure(200, {"report": "Grounded answer"}) is None


def test_semantic_grade_normalization_keeps_valid_labels():
    assert normalize_grade(" correct ") == "CORRECT"
    assert normalize_grade("unknown label") == "UNKNOWN_REVIEW_FAILED"


def test_semantic_review_respects_explicit_source_restrictions():
    assert "explicit source restrictions in the user's question" in SYSTEM
    assert "different uploaded company's filing as permitted evidence" in SYSTEM
    assert "Do not let benchmark company metadata or expected_sources override" in SYSTEM


def test_local_support_is_not_conflated_with_query_relevance():
    answer = "Apple Services gross margin increased to 75.0% [Evidence 1]."
    chunk = "Apple Services gross margin increased to 75.0% in the quarter."
    result = validate_citation_annotation(
        {"rank": 1, "chunk_text": chunk},
        {
            "grade": "VALID_SUPPORTED",
            "query_relevance": "CONTEXTUAL",
            "evidence_quote": chunk,
            "answer_claim": "Apple Services gross margin increased to 75.0%",
        },
        answer,
        source_valid=True,
    )
    assert result["grade"] == "VALID_SUPPORTED"
    assert result["query_relevance"] == "CONTEXTUAL"


def test_unreferenced_candidate_is_not_counted_as_an_unsupported_answer_citation():
    result = validate_citation_annotation(
        {"rank": 2, "chunk_text": "A valid retrieved passage."},
        {"grade": "VALID_BUT_NOT_SUPPORTED", "reason": "not used"},
        "The answer cites another passage [Evidence 1].",
        source_valid=True,
    )
    assert result["grade"] == "UNUSED_RETRIEVED_CONTEXT"
    assert result["answer_claim"] == ""


def test_invalid_review_annotation_is_indeterminate_not_a_false_unsupported_claim():
    result = validate_citation_annotation(
        {"rank": 1, "chunk_text": "Apple reported services revenue of $26 billion this quarter."},
        {
            "grade": "VALID_SUPPORTED",
            "evidence_quote": "Apple reported services revenue of $99 billion this quarter.",
            "answer_claim": "Services revenue was $99 billion",
        },
        "Services revenue was $99 billion [Evidence 1].",
        source_valid=True,
    )
    assert result["grade"] == "REVIEW_INDETERMINATE"
    assert result["quote_validation_failed"] is True
    assert result["annotation_validation_issues"] == ["evidence_quote_not_exact_in_cited_chunk"]


def test_explicit_unsupported_judgment_is_preserved_when_spans_are_verifiable():
    chunk = "Apple reported services revenue of $26 billion for the quarter ended March 28."
    claim = "Services revenue was $99 billion this quarter"
    result = validate_citation_annotation(
        {"rank": 1, "chunk_text": chunk},
        {
            "grade": "VALID_BUT_NOT_SUPPORTED",
            "evidence_quote": chunk,
            "answer_claim": claim,
            "reason": "The exact cited table reports a different value.",
        },
        f"{claim} [Evidence 1].",
        source_valid=True,
    )
    assert result["grade"] == "VALID_BUT_NOT_SUPPORTED"
    assert "annotation_validation_issues" not in result


def test_claim_cannot_borrow_an_evidence_marker_from_another_sentence():
    tesla_chunk = "Tesla Q2 revenue was $22 billion, according to the report."
    answer = (
        "Tesla Q2 revenue was $22 billion [Evidence 1]. "
        "NVIDIA Q1 revenue was $81.6 billion [Evidence 2]."
    )

    result = validate_citation_annotation(
        {"rank": 1, "chunk_text": tesla_chunk},
        {
            "grade": "VALID_SUPPORTED",
            "query_relevance": "DIRECT",
            "evidence_quote": tesla_chunk,
            "answer_claim": "NVIDIA Q1 revenue was $81.6 billion",
        },
        answer,
        source_valid=True,
    )

    assert result["grade"] == "REVIEW_INDETERMINATE"
    assert result["annotation_validation_issues"] == [
        "answer_claim_not_attached_to_citation_rank"
    ]


def test_missing_cited_claim_annotation_is_indeterminate():
    chunk = "Apple reported services revenue of $26 billion for the quarter ended March 28."
    result = validate_citation_annotation(
        {"rank": 1, "chunk_text": chunk},
        {"grade": "VALID_BUT_NOT_SUPPORTED", "reason": "No supported claim annotated"},
        "Services revenue was $26 billion [Evidence 1].",
        source_valid=True,
    )
    assert result["grade"] == "REVIEW_INDETERMINATE"
    assert "answer_claim_too_short_or_missing" in result["annotation_validation_issues"]


def test_invalid_source_remains_invalid_even_if_claim_is_annotated():
    result = validate_citation_annotation(
        {"rank": 1, "chunk_text": "A sufficiently long quoted passage for validation."},
        {"grade": "VALID_SUPPORTED", "query_relevance": "DIRECT"},
        "A claim [Evidence 1].",
        source_valid=False,
    )
    assert result["grade"] == "INVALID_SOURCE"


def test_application_success_requires_complete_runtime_envelope():
    complete = {
        "report": "Grounded answer",
        "execution": {"strategy": "rag"},
        "workflow": {"type": "rag", "status": "done"},
    }
    assert application_success(200, complete) is True
    assert application_success(200, {"report": "Grounded answer"}) is False
    assert application_success(200, {**complete, "report": "[Provider Error] unavailable"}) is False
