from unittest.mock import Mock

import pytest

from core.answer_synthesis_contracts import AnswerType
from services.ready_fact_synthesis_source import ReadyFactSynthesisSource
from services.ready_narrative_synthesis_source import narrative_answer_type


@pytest.mark.parametrize("question,expected", [
    ("解释贵州茅台净利润", AnswerType.EXPLANATION),
    ("贵州茅台净利润下降的原因是什么？", AnswerType.CAUSAL_ANALYSIS),
    ("为什么会有这些风险？", AnswerType.CAUSAL_ANALYSIS),
    ("列出所有风险", AnswerType.EXHAUSTIVE_LIST),
    ("跨章节说明风险", AnswerType.CROSS_SECTION),
    ("Explain net income", AnswerType.EXPLANATION),
    ("Why did net income fall?", AnswerType.CAUSAL_ANALYSIS),
    ("贵州茅台2025年总资产是多少？", None),
    ("比较2024和2025年总资产", None),
])
def test_explicit_answer_shape_is_shared(question, expected):
    assert narrative_answer_type(question) == expected


def test_metric_in_explanation_does_not_force_fact_lookup():
    narrative = Mock(return_value="server-source")
    resolver = ReadyFactSynthesisSource(Mock(), fallback_resolver=narrative)
    resolver.facts = Mock()
    parameters = dict(question="解释贵州茅台净利润", locale="zh-CN", tenant_id=1, user_id=2,
                      ingestion_job_id="ready", manifest={"document_id": 42})
    assert resolver(**parameters) == "server-source"
    narrative.assert_called_once_with(**parameters)
    resolver.facts.retrieve.assert_not_called()


def test_failed_precise_fact_read_never_falls_back_to_narrative():
    narrative = Mock()
    resolver = ReadyFactSynthesisSource(Mock(), fallback_resolver=narrative)
    resolver.facts = Mock()
    resolver.facts.retrieve.side_effect = PermissionError("not authorized")
    with pytest.raises(PermissionError):
        resolver(question="贵州茅台2025年总资产是多少？", locale="zh-CN", tenant_id=1,
                 user_id=2, ingestion_job_id="ready", manifest={"document_id": 42})
    narrative.assert_not_called()
