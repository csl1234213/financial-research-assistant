from dataclasses import replace

import pytest

from core.answer_synthesis_contracts import AnswerType
from core.answer_synthesis_narrative import NARRATIVE_TYPES, assemble_narrative
from core.answer_synthesis_narrative_strategy import (
    NARRATIVE_STRATEGIES,
    build_narrative_prompt,
    parse_narrative_json,
)
from tests.test_answer_synthesis_narrative import narrative_inputs


def test_all_narrative_types_have_distinct_strategy_and_source_bound_prompt():
    assert set(NARRATIVE_STRATEGIES) == set(NARRATIVE_TYPES)
    assert len(set(NARRATIVE_STRATEGIES.values())) == len(NARRATIVE_TYPES)
    for kind in NARRATIVE_TYPES:
        source, _ = narrative_inputs(kind)
        instruction, payload = build_narrative_prompt(source)
        assert NARRATIVE_STRATEGIES[kind] in instruction
        assert source.evidence[0].evidence_id in payload
        assert "Simplified Chinese" in instruction
    with pytest.raises(TypeError):
        NARRATIVE_STRATEGIES[AnswerType.FACT] = "unsafe"


@pytest.mark.parametrize("text", ['{"claims":[],"claims":[]}', '{"claims":[{"text":"a","text":"b"}]}',
                                 '{"claims":NaN}', '```json\n{"claims":[]}\n```'])
def test_ambiguous_or_non_json_provider_output_is_rejected(text):
    with pytest.raises(ValueError):
        parse_narrative_json(text)


def test_cross_section_requires_distinct_identified_sections():
    source, candidate = narrative_inputs(AnswerType.CROSS_SECTION)
    with pytest.raises(ValueError, match="CROSS_SECTION_EVIDENCE_REQUIRED"):
        assemble_narrative(source, candidate)
    source = replace(source, answer_type=AnswerType.EXHAUSTIVE_LIST, locale="zh-TW", coverage={"complete": False})
    assert "並非完整清單" in assemble_narrative(source, candidate).text


def test_oversized_evidence_is_rejected_not_silently_truncated():
    source, _ = narrative_inputs()
    evidence = replace(source.evidence[0], payload={"text": "x" * 20000})
    with pytest.raises(ValueError, match="INPUT_BUDGET_EXCEEDED"):
        build_narrative_prompt(replace(source, evidence=(evidence,)))
