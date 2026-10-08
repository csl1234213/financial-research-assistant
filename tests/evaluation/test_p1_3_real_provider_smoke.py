from evaluation.p1_3_real_provider_smoke import (
    _core_quality,
    _critical_scope_violations,
    _evidence_utilization,
    _is_insufficient_evidence_response,
)


def test_insufficient_evidence_classifier_accepts_production_refusal_wording():
    report = (
        "No relevant uploaded-filing evidence was retrieved for this question, "
        "so I can't answer it reliably."
    )

    assert _is_insufficient_evidence_response(report)
    quality, _ = _core_quality({"id": "EN-033"}, report, [])
    assert quality == "CORRECT"
    utilization, _ = _evidence_utilization({"id": "EN-033"}, report, [])
    assert utilization == "FULL"


def test_direct_concept_examples_are_not_financial_citation_failures():
    report = "毛利率就是（20 - 8）÷ 20 = 60%。"

    quality, _ = _core_quality({"id": "ZH-044"}, report, [])
    assert quality == "CORRECT"
    utilization, _ = _evidence_utilization({"id": "ZH-044"}, report, [])
    assert utilization == "FULL"


def test_rejected_unused_candidate_does_not_become_final_scope_error():
    final_grounding = {
        "unsupported_count": 0,
        "judgments": [{"reason": "period scope mismatch"}],
    }

    assert _critical_scope_violations(final_grounding) == (0, 0)
