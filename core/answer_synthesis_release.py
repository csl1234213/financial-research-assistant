"""Buffer complete answers and independently verify before releasing any text."""

from collections.abc import Iterator

from core.answer_synthesis_analysis import AnalyticalAnswer, AnalyticalAnswerRenderer
from core.answer_synthesis_contracts import AnswerPlan, SynthesisInput
from core.answer_synthesis_draft_verifier import ControlledFactDraftVerifier
from core.answer_synthesis_renderer import RenderedAnswer, RestrictedOutputVerifier
from core.answer_synthesis_workflow import SynthesisOutcome


def verified_answer_chunks(
    source: SynthesisInput,
    plan: AnswerPlan,
    outcome: SynthesisOutcome,
    *,
    chunk_size: int = 128,
) -> Iterator[str]:
    """No token is released until the entire buffered answer passes its verifier.

    This is an opt-in output port, not a production SSE route. Model token
    streams must never be passed directly into this function.
    """
    if type(chunk_size) is not int or not 1 <= chunk_size <= 4096:
        raise ValueError("bounded positive chunk size required")
    answer = outcome.answer
    if isinstance(answer, AnalyticalAnswer):
        passed = AnalyticalAnswerRenderer().verify(source, plan, answer)
    elif isinstance(answer, RenderedAnswer):
        if outcome.mode == "VERIFIED_FACT_DRAFT":
            result = ControlledFactDraftVerifier().verify(source, plan, answer.text)
            passed = result.passed and set(result.reviewed_claim_ids) == {
                claim.claim_id for claim in plan.claims
            }
            # Citation metadata is locked independently of prose verification.
            passed = passed and answer.citation_evidence_ids == tuple(
                dict.fromkeys(eid for claim in plan.claims for eid in claim.evidence_ids)
            )
        else:
            passed = RestrictedOutputVerifier().verify(source, plan, answer).passed
    else:
        passed = False
    if not passed:
        raise ValueError("final answer verification failed; no output released")
    for offset in range(0, len(answer.text), chunk_size):
        yield answer.text[offset : offset + chunk_size]
