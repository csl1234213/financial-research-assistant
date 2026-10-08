from agent.reasoning_models import Evidence
from core.fact_ledger import build_evidence_first_context
from core.required_fact_plan import infer_required_fact_plan


def test_context_budget_keeps_required_fact_chunk_before_narrative_overflow() -> None:
    required = Evidence(
        content="NVIDIA Q1 FY2027 total revenue was $81.6 billion.",
        source="NVIDIA.pdf",
        company="NVIDIA",
        confidence=1.0,
        metadata={
            "chunk_id": "required-revenue",
            "quarter": "Q1_FY2027",
            "periods": "Q1_FY2027",
            "metrics": "revenue",
            "source_authority": "tenant_upload",
        },
    )
    noise = Evidence(
        content=("Unrelated narrative " * 1200),
        source="NVIDIA.pdf",
        company="NVIDIA",
        confidence=1.0,
        metadata={
            "chunk_id": "overflow-narrative",
            "quarter": "Q1_FY2027",
            "periods": "Q1_FY2027",
            "metrics": "revenue",
            "source_authority": "tenant_upload",
        },
    )
    question = "What was NVIDIA revenue in Q1 FY2027?"
    plan = infer_required_fact_plan(question, [required, noise])
    context, _ = build_evidence_first_context(
        question,
        [required, noise],
        plan,
        max_context_tokens=1200,
    )

    assert "required-revenue" in context
    assert "overflow-narrative" not in context
    assert len(context) // 2 <= 1200


def test_context_budget_renders_required_ledger_facts_only() -> None:
    revenue = Evidence(
        content="NVIDIA Q1 FY2027 total revenue was $81.6 billion.",
        source="NVIDIA.pdf",
        company="NVIDIA",
        confidence=1.0,
        metadata={
            "chunk_id": "revenue-fact",
            "quarter": "Q1_FY2027",
            "periods": "Q1_FY2027",
            "metrics": "revenue",
        },
    )
    unrelated = Evidence(
        content="NVIDIA Q1 FY2027 net income was $58.3 billion.",
        source="NVIDIA.pdf",
        company="NVIDIA",
        confidence=1.0,
        metadata={
            "chunk_id": "net-income-fact",
            "quarter": "Q1_FY2027",
            "periods": "Q1_FY2027",
            "metrics": "net_income",
        },
    )
    question = "What was NVIDIA revenue in Q1 FY2027?"
    plan = infer_required_fact_plan(question, [revenue, unrelated])
    context, _ = build_evidence_first_context(
        question,
        [revenue, unrelated],
        plan,
        max_context_tokens=1200,
    )

    assert "revenue" in context
    assert "net_income" not in context
