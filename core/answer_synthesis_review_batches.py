"""Offline, lossless narrative review admission; no Provider or release authority."""

from dataclasses import dataclass, replace

from core.answer_synthesis_contracts import AnswerPlan
from core.answer_synthesis_narrative import assemble_narrative
from core.answer_synthesis_reference_transport import CompactEvidenceReferences
from core.answer_synthesis_semantic import semantic_input_digest
from core.answer_synthesis_semantic_ollama import build_semantic_review_prompt


@dataclass(frozen=True)
class NarrativeReviewBatch:
    plan: AnswerPlan
    draft: str
    instruction: str
    payload: str
    wire_bytes: int
    full_input_digest: str


def plan_narrative_review_batches(source, plan, draft, *, max_batches=4):
    """Partition only claims/draft lines, retaining ALL admitted evidence per batch.

    Exact reconstruction rejects unclaimed prose before any external call. This
    planner does not authorize inference or declare semantic correctness. Caller
    must reserve cumulative usage/deadline and validate every batch before release.
    """
    if type(max_batches) is not int or not 1 <= max_batches <= 4:
        raise ValueError("INVALID_REVIEW_BATCH_LIMIT")
    rebuilt = assemble_narrative(source, {"claims": [
        {"text": claim.semantic_content, "evidence_ids": list(claim.evidence_ids),
         "causal_strength": claim.causal_strength.value, "caveat": claim.caveat}
        for claim in plan.claims]})
    if rebuilt.plan != plan or rebuilt.text != draft:
        raise ValueError("REVIEW_DRAFT_PROJECTION_CHANGED")
    lines = draft.splitlines()
    prefix_count = len(lines) - len(plan.claims)
    assert prefix_count in (0, 1)
    references = CompactEvidenceReferences(source)
    digest = semantic_input_digest(source, plan, draft)

    def admit(start, end):
        batch_plan = replace(plan, claims=plan.claims[start:end])
        batch_draft = "\n".join(lines[(0 if start == 0 else prefix_count + start):prefix_count + end])
        instruction, payload = build_semantic_review_prompt(
            source, batch_plan, batch_draft, reference_transport=references)
        return NarrativeReviewBatch(batch_plan, batch_draft, instruction, payload,
                                    len((instruction + payload).encode("utf-8")), digest)

    batches = []
    start = 0
    while start < len(plan.claims):
        selected = None
        for end in range(start + 1, len(plan.claims) + 1):
            try:
                candidate = admit(start, end)
            except ValueError as error:
                if str(error) != "semantic input exceeds local context budget":
                    raise
                break
            selected = candidate
        if selected is None:
            raise ValueError("REVIEW_SINGLE_CLAIM_EXCEEDS_INPUT_BUDGET")
        batches.append(selected)
        if len(batches) > max_batches:
            raise ValueError("REVIEW_BATCH_LIMIT_EXCEEDED")
        start += len(selected.plan.claims)
    if (tuple(claim for batch in batches for claim in batch.plan.claims) != plan.claims
            or "\n".join(batch.draft for batch in batches) != draft):
        raise ValueError("REVIEW_BATCH_COVERAGE_CHANGED")
    return tuple(batches)
