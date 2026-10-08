"""Explicit local Qwen candidate generation, never an answer release path."""

from dataclasses import dataclass

from core.answer_provider_port import AnswerRequestPurpose, chat_answer, complete_usage, resolve_answer_provider
from core.answer_synthesis_narrative import BufferedNarrative, assemble_narrative
from core.answer_synthesis_narrative_strategy import build_narrative_prompt, parse_narrative_json
from core.answer_synthesis_reference_transport import CompactEvidenceReferences
from core.answer_synthesis_semantic import validate_grounded_answer_review
from core.answer_synthesis_usage import AccountedCompletionFailure, FailedCompletionUsage
from llm.providers.provider_exceptions import StructuredOutputError


@dataclass(frozen=True)
class GeneratedNarrative:
    buffered: BufferedNarrative
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


def reviewed_narrative_chunks(source, generated, review, *, chunk_size=128):
    """Reconstruct and review the complete buffered answer before first yield."""
    if type(chunk_size) is not int or not 1 <= chunk_size <= 4096:
        raise ValueError("INVALID_NARRATIVE_CHUNK_SIZE")
    if not isinstance(generated, GeneratedNarrative):
        raise ValueError("GENERATED_NARRATIVE_REQUIRED")
    buffered = generated.buffered
    candidate = {"claims": [{"text": claim.semantic_content, "evidence_ids": list(claim.evidence_ids),
        "causal_strength": claim.causal_strength.value, "caveat": claim.caveat} for claim in buffered.plan.claims]}
    rebuilt = assemble_narrative(source, candidate)
    if rebuilt != buffered or not validate_grounded_answer_review(source, rebuilt.plan, review, rebuilt.text):
        raise ValueError("FINAL_NARRATIVE_REVIEW_FAILED")
    for offset in range(0, len(rebuilt.text), chunk_size):
        yield rebuilt.text[offset:offset + chunk_size]


class LocalQwenNarrativeGenerator:
    def __init__(self, *, model=None, base_url="http://127.0.0.1:11434", enabled=False,
                 compact_references=False, provider=None, provider_config=None, request_purpose=None):
        self.provider = resolve_answer_provider(provider=provider, provider_config=provider_config,
                                               model=model, base_url=base_url)
        self.model = self.provider.model
        self.enabled = enabled is True
        if type(compact_references) is not bool:
            raise ValueError("INVALID_REFERENCE_TRANSPORT_OPTION")
        self.compact_references = compact_references
        self.request_purpose = None if request_purpose is None else AnswerRequestPurpose(request_purpose)
        self.completion_receipts = []
        self.failure_receipts = []

    def generate(self, source, *, max_tokens=1024, max_seconds=60, feedback_codes=()):
        if not self.enabled:
            raise ValueError("LOCAL_NARRATIVE_GENERATION_DISABLED")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ValueError("INVALID_NARRATIVE_TOKEN_BUDGET")
        references = CompactEvidenceReferences(source) if self.compact_references else None
        instruction, payload = build_narrative_prompt(source, reference_transport=references)
        if feedback_codes not in {(), ("SEMANTIC_REVIEW_NOT_SUPPORTED",)}:
            raise ValueError("INVALID_NARRATIVE_REVISION_FEEDBACK")
        if feedback_codes:
            instruction += (" Previous candidate was not supported. "
                            "Recheck every claim against its exact cited evidence.")
        if len((instruction + payload).encode("utf-8")) > 16000:
            raise ValueError("NARRATIVE_INPUT_BUDGET_EXCEEDED")
        try:
            response = chat_answer(self.provider, instruction, payload,
                                   max_seconds=max_seconds, max_tokens=max_tokens, purpose=self.request_purpose)
        except Exception as error:
            self.failure_receipts.append({"phase": "generation", "error_type": type(error).__name__,
                                          "usage_complete": False})
            raise
        self.completion_receipts.append({"provider": response.provider, "model": response.model,
            "done_reason": response.metadata.get("done_reason"), "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens, "total_tokens": response.total_tokens,
            "safe_response_diagnostics": response.metadata["safe_response_diagnostics"]})
        usage = (response.prompt_tokens, response.completion_tokens, response.total_tokens)
        if response.finish_reason != "stop":
            if complete_usage(response) is not None and response.total_tokens > 0:
                raise AccountedCompletionFailure("NARRATIVE_PROVIDER_RESPONSE_MISMATCH",
                    FailedCompletionUsage(*usage), failure_class="STRUCTURED_OUTPUT_ERROR")
            raise StructuredOutputError("NARRATIVE_PROVIDER_RESPONSE_MISMATCH")
        try:
            candidate = parse_narrative_json(response.content)
            if references is not None:
                candidate = references.decode_claims(source, candidate)
            buffered = assemble_narrative(source, candidate)
        except (ValueError, TypeError, KeyError) as error:
            if str(error) in {"NARRATIVE_SUBJECT_ATTRIBUTION_REQUIRED", "NARRATIVE_NUMERIC_MUTATION",
                              "NARRATIVE_QUERY_DIMENSION_MISMATCH"}:
                self.completion_receipts[-1]["contract_failure_code"] = str(error)
            if complete_usage(response) is not None and response.total_tokens > 0:
                raise AccountedCompletionFailure("LOCAL_GENERATION_CONTRACT_FAILED",
                    FailedCompletionUsage(*usage), failure_class="STRUCTURED_OUTPUT_ERROR") from error
            raise StructuredOutputError("LOCAL_GENERATION_CONTRACT_FAILED") from error
        return GeneratedNarrative(buffered, self.model, *usage)
