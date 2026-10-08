from agent.reasoning_models import Evidence
from core.core_engine import (
    _prioritize_explicit_audit_disclosure,
    _project_explicit_audit_answer,
)


def _evidence(chunk_id: str, content: str) -> Evidence:
    return Evidence(
        content=content,
        source="annual-report.pdf",
        company="贵州茅台",
        confidence=0.9,
        metadata={"chunk_id": chunk_id},
    )


def test_audit_answer_context_prioritizes_explicit_firm_and_opinion_evidence():
    report_body = _evidence(
        "report-body",
        "审计报告认为财务报表在所有重大方面按照企业会计准则编制并公允反映。",
    )
    negated_opinion = _evidence(
        "negated-opinion",
        "天健会计师事务所如发现重大问题可能发表非无保留意见。",
    )
    explicit_disclosure = _evidence(
        "explicit-disclosure",
        "天健会计师事务所（特殊普通合伙）出具标准无保留意见的审计报告。",
    )

    prioritized = _prioritize_explicit_audit_disclosure(
        "贵州茅台2025年度财务报表由哪家会计师事务所审计？审计意见是什么？",
        [report_body, negated_opinion, explicit_disclosure],
    )

    assert [item.metadata["chunk_id"] for item in prioritized] == [
        "explicit-disclosure",
        "report-body",
        "negated-opinion",
    ]


def test_audit_evidence_priority_does_not_change_unrelated_questions():
    evidence = [
        _evidence("first", "General annual report text."),
        _evidence("second", "天健会计师事务所出具标准无保留意见。"),
    ]

    assert _prioritize_explicit_audit_disclosure("What is the revenue?", evidence) == evidence


def test_audit_answer_is_projected_only_from_explicit_source_facts():
    evidence = [
        _evidence(
            "cover-summary",
            "天健会计师事务所(特殊普通合伙)为本公司出具了标准无保留意见的审计报告。",
        )
    ]

    projected = _project_explicit_audit_answer(
        "贵州茅台2025年度财务报表由哪家会计师事务所审计？审计意见是什么？",
        evidence,
        "zh-CN",
    )

    assert projected == (
        "审计机构为天健会计师事务所(特殊普通合伙)；审计意见为标准无保留意见 [Evidence 1]。"
    )


def test_audit_answer_projection_rejects_negated_opinion_evidence():
    evidence = [
        _evidence(
            "conditional-audit-body",
            "如披露不充分，可能需要发表非无保留意见。",
        )
    ]

    assert _project_explicit_audit_answer(
        "哪家会计师事务所审计？审计意见是什么？",
        evidence,
        "zh-CN",
    ) is None
