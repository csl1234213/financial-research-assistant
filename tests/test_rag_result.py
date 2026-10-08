from unittest.mock import MagicMock

from core.rag_result import RAGResult


def test_rag_result_exposes_named_fields_and_legacy_tuple_contract():
    plan = MagicMock()
    result = RAGResult(
        report="report",
        citations=[{"source": "Tesla_Q2_2025.pdf"}],
        context="context",
        research_mode="default",
        intent={"intent": "SINGLE_COMPANY"},
        evidence=[],
        plan=plan,
        routing={"provider": "deepseek"},
        planning={"task_type": "document_qa"},
        execution={"strategy": "rag"},
        workflow={"type": "rag"},
    )

    (
        report,
        citations,
        context,
        research_mode,
        intent,
        evidence,
        unpacked_plan,
        routing,
        planning,
        execution,
        workflow,
    ) = result

    assert result.report == report == "report"
    assert result.citations == citations
    assert result.context == context
    assert result.research_mode == research_mode
    assert result.intent == intent
    assert result.evidence == evidence
    assert result.plan is unpacked_plan is plan
    assert result.routing == routing
    assert result.planning == planning
    assert result.execution == execution
    assert result.workflow == workflow
    assert result[0] == "report"
    assert len(result) == 11
