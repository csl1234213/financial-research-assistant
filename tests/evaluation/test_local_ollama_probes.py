from __future__ import annotations

import json


def test_local_probe_prefers_canonical_utf8_question_over_audit_copy():
    from evaluation.local_ollama_quality_probe import _canonical_question

    question = _canonical_question(
        "ZH-008",
        {
            "question": "Ӣΰ�� 2027 �����һ���ȵ���������ҵ�������Σ�",
            "resolved_question": "Ӣΰ�� 2027 �����һ���ȵ���������ҵ�������Σ�",
        },
    )

    assert "英伟达" in question
    assert "数据中心业务表现" in question
    assert "Ӣΰ" not in question


def test_local_probe_keeps_audit_question_when_frozen_dataset_row_is_missing():
    from evaluation.local_ollama_quality_probe import _canonical_question

    question = _canonical_question(
        "UNKNOWN-CASE",
        {"resolved_question": "A valid fallback question"},
    )

    assert question == "A valid fallback question"


def test_local_probe_restores_expected_document_identity_for_historical_table_column():
    from agent.reasoning_models import Evidence
    from core.fact_ledger import FactLedger
    from core.required_fact_plan import infer_required_fact_plan
    from evaluation.local_ollama_quality_probe import _evidence_for_row

    source_rows = {
        "tesla-table": Evidence(
            content=(
                "Structured financial table row | Metric: Total revenues | "
                "Q4 2024: 25,707 | Q1 2025: 19,335 | Q2 2025: 22,496 | "
                "Q4 2025: 24,901"
            ),
            source="Tesla_sample.pdf",
            company="Tesla",
            metadata={
                "chunk_id": "tesla-table",
                "quarter": "Q4_2025",
                "content_type": "table",
            },
        ),
        "nvidia": Evidence(
            content="NVIDIA Q1 FY2027 revenue was $81.6 billion.",
            source="NVIDIA_sample.pdf",
            company="NVIDIA",
            metadata={"chunk_id": "nvidia", "quarter": "Q1_FY2027"},
        ),
    }
    enriched = _evidence_for_row(
        {"retrieved_chunk_ids": ["tesla-table", "nvidia"]},
        source_rows,
        ["Tesla_Q2_2025.pdf", "NVIDIA_Q1_FY2027.pdf"],
    )

    assert enriched[0].metadata["document_id"] == "tesla_q2_2025"
    plan = infer_required_fact_plan(
        "Compare Tesla and NVIDIA revenue performance.",
        enriched,
        FactLedger.from_evidence(enriched),
    )
    expected = [
        ("tesla", "Q2_2025"),
        ("nvidia", "Q1_FY2027"),
    ]
    assert [(item.company, item.period) for item in plan.required] == expected
    chinese_plan = infer_required_fact_plan(
        "比较特斯拉和英伟达的营收表现。",
        enriched,
        FactLedger.from_evidence(enriched),
    )
    assert [(item.company, item.period) for item in chinese_plan.required] == expected


def test_no_evidence_replay_uses_the_production_non_empty_refusal():
    from core.answer_policy import finalize_grounded_answer

    result = finalize_grounded_answer(
        "分析阿里巴巴最新季度财务表现。",
        "",
        [],
    )

    assert result.answer.strip()
    assert "证据" in result.answer
    assert result.grounded.unsupported_count == 0


def test_semantic_regrade_loads_current_policy_rows_from_replay_summary(tmp_path):
    from evaluation.local_ollama_semantic_regrade import _load_replay

    replay = tmp_path / "replay"
    replay.mkdir()
    (replay / "summary.json").write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "id": "EN-001",
                        "raw_answer": "raw",
                        "answer_after_current_retrieval_grounding": "final",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = _load_replay(replay)

    assert rows["EN-001"]["raw_answer"] == "raw"
    assert rows["EN-001"]["final_answer"] == "final"
