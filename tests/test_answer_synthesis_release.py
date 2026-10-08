from dataclasses import replace

import pytest

from core.answer_synthesis_draft_verifier import factual_sentence_variants
from core.answer_synthesis_release import verified_answer_chunks
from core.answer_synthesis_workflow import BoundedSynthesisWorkflow, DraftCandidate
from tests.test_answer_synthesis_analysis import incoming
from tests.test_answer_synthesis_workflow import Generator, inputs


def test_buffered_release_preserves_complete_verified_text():
    source, plan = inputs()
    outcome = BoundedSynthesisWorkflow().run(source, plan)
    assert "".join(verified_answer_chunks(source, plan, outcome, chunk_size=7)) == outcome.answer.text


def test_fact_paraphrase_survives_final_release_verification():
    source, plan = inputs()
    text = factual_sentence_variants(source, plan)[0][1]
    outcome = BoundedSynthesisWorkflow().run(
        source, plan, enabled=True, generator=Generator([DraftCandidate(text, 15)])
    )
    assert outcome.mode == "VERIFIED_FACT_DRAFT"
    assert "".join(verified_answer_chunks(source, plan, outcome)) == text
    corrupted = replace(outcome, answer=replace(outcome.answer, citation_evidence_ids=("other",)))
    with pytest.raises(ValueError, match="no output released"):
        next(verified_answer_chunks(source, plan, corrupted))


def test_analysis_audit_and_text_are_rechecked_before_first_chunk():
    source, plan = incoming()
    outcome = BoundedSynthesisWorkflow().run(source, plan, analysis_enabled=True)
    assert "".join(verified_answer_chunks(source, plan, outcome)) == outcome.answer.text
    corrupted = replace(outcome, answer=replace(outcome.answer, text=outcome.answer.text + " unsupported"))
    with pytest.raises(ValueError, match="no output released"):
        next(verified_answer_chunks(source, plan, corrupted))


@pytest.mark.parametrize("mutation", ["number", "citation", "text"])
def test_final_verifier_failure_releases_zero_chunks(mutation):
    source, plan = inputs()
    outcome = BoundedSynthesisWorkflow().run(source, plan)
    if mutation == "citation":
        answer = replace(outcome.answer, citation_evidence_ids=("wrong-source",))
    else:
        answer = replace(outcome.answer, text="unsafe 999 [999]" if mutation == "number" else "caused profit decline")
    stream = verified_answer_chunks(source, plan, replace(outcome, answer=answer))
    received = []
    with pytest.raises(ValueError, match="no output released"):
        for chunk in stream:
            received.append(chunk)
    assert received == []


@pytest.mark.parametrize("size", [True, 0, -1, 4097])
def test_invalid_chunk_size_is_rejected(size):
    source, plan = inputs()
    outcome = BoundedSynthesisWorkflow().run(source, plan)
    with pytest.raises(ValueError):
        list(verified_answer_chunks(source, plan, outcome, chunk_size=size))
