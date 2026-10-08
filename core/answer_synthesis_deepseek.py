"""Explicit DeepSeek synthesis ports; no automatic routing or local fallback."""

import json
from dataclasses import replace

from core.answer_provider_port import chat_answer, complete_usage, resolve_answer_provider
from core.answer_synthesis_narrative import assemble_narrative
from core.answer_synthesis_narrative_ollama import GeneratedNarrative
from core.answer_synthesis_narrative_strategy import build_narrative_prompt, parse_narrative_json
from core.answer_synthesis_reference_transport import REFERENCE_TRANSPORT_VERSION, CompactEvidenceReferences
from core.answer_synthesis_semantic_ollama import build_semantic_review_prompt, parse_local_review
from core.answer_synthesis_usage import AccountedCompletionFailure, FailedCompletionUsage, ProviderPreflightFailure
from llm.providers.provider_config import ProviderConfig
from llm.providers.provider_exceptions import StructuredOutputError


class DeepSeekSynthesisPorts:
    """One explicitly configured provider, shared budgets and locked review schema."""

    def __init__(self, *, model=None, api_key="", enabled=False, provider=None, provider_config=None):
        config = provider_config
        if provider is None and config is None:
            config = ProviderConfig(provider="deepseek", model=model, api_key=api_key)
        self.provider = resolve_answer_provider(provider=provider, provider_config=config)
        self.model, self.enabled = self.provider.model, enabled is True
        self.completion_receipts = []
        self.preflight_receipts = []

    def _chat(self, instruction, payload, max_seconds, max_tokens):
        if not self.enabled:
            raise ValueError("DEEPSEEK_SYNTHESIS_DISABLED")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ValueError("INVALID_DEEPSEEK_SYNTHESIS_BUDGET")
        response = chat_answer(self.provider, instruction, payload,
            max_seconds=max_seconds, max_tokens=max_tokens, thinking_enabled=False)
        self.completion_receipts.append({"provider": response.provider, "model": response.model,
            "request_bytes": len((instruction + payload).encode("utf-8")),
            "reference_transport": REFERENCE_TRANSPORT_VERSION,
            "finish_reason": response.metadata.get("finish_reason"),
            "api_attempts": response.metadata.get("api_attempts"),
            "attempt_usage": response.metadata.get("attempt_usage"),
            "all_attempt_usage_complete": response.metadata.get("all_attempt_usage_complete"),
            "prompt_tokens": response.prompt_tokens, "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens})
        # The adapter reports complete aggregate usage or None, retaining real
        # per-attempt records for telemetry without making them a release gate.
        usage = (response.prompt_tokens, response.completion_tokens, response.total_tokens)
        if response.finish_reason != "stop":
            if complete_usage(response) is not None and response.total_tokens > 0:
                raise AccountedCompletionFailure("DEEPSEEK_SYNTHESIS_COMPLETION_MISMATCH",
                    FailedCompletionUsage(*usage), failure_class="STRUCTURED_OUTPUT_ERROR")
            raise StructuredOutputError("INCOMPLETE_STRUCTURED_RESPONSE")
        return response, usage

    def generate(self, source, *, max_seconds=60, max_tokens=1024, feedback_codes=()):
        references = CompactEvidenceReferences(source)
        instruction, payload = build_narrative_prompt(source, reference_transport=references)
        if feedback_codes not in {(), ("SEMANTIC_REVIEW_NOT_SUPPORTED",)}:
            raise ValueError("INVALID_NARRATIVE_REVISION_FEEDBACK")
        if feedback_codes:
            instruction += (" Previous candidate was not supported. "
                            "Recheck every claim against its exact cited evidence.")
        if len((instruction + payload).encode("utf-8")) > 16000:
            raise ValueError("NARRATIVE_INPUT_BUDGET_EXCEEDED")
        response, usage = self._chat(instruction, payload, max_seconds, max_tokens)
        try:
            candidate = references.decode_claims(source, parse_narrative_json(response.content))
            buffered = assemble_narrative(source, candidate)
        except (ValueError, TypeError, KeyError) as exc:
            if str(exc) in {"NARRATIVE_SUBJECT_ATTRIBUTION_REQUIRED", "INVALID_NARRATIVE_SUBJECT_CONTEXT",
                            "NARRATIVE_NUMERIC_MUTATION", "NARRATIVE_QUERY_DIMENSION_MISMATCH",
                            "INVALID_NARRATIVE_SCHEMA", "INVALID_NARRATIVE_CLAIM_SCHEMA",
                            "INVALID_NARRATIVE_CLAIM", "NARRATIVE_CLAIM_BUDGET"}:
                self.completion_receipts[-1]["contract_failure_code"] = str(exc)
            if complete_usage(response) is not None and response.total_tokens > 0:
                raise AccountedCompletionFailure("DEEPSEEK_GENERATION_CONTRACT_FAILED",
                    FailedCompletionUsage(*usage), failure_class="STRUCTURED_OUTPUT_ERROR") from exc
            raise StructuredOutputError("DEEPSEEK_GENERATION_CONTRACT_FAILED") from exc
        return GeneratedNarrative(buffered, self.model, *usage)

    def review(self, source, plan, draft, *, max_seconds=60, max_tokens=1024):
        references = CompactEvidenceReferences(source)
        try:
            instruction, payload = build_semantic_review_prompt(source, plan, draft,
                                                                reference_transport=references)
        except ValueError as exc:
            input_bytes = getattr(exc, "input_bytes", None)
            if str(exc) == "semantic input exceeds local context budget" and type(input_bytes) is int:
                self.preflight_receipts.append({"phase": "review", "api_attempts": 0,
                    "code": "SEMANTIC_INPUT_BUDGET_EXCEEDED", "input_bytes": input_bytes})
                raise ProviderPreflightFailure("SEMANTIC_INPUT_BUDGET_EXCEEDED", input_bytes) from exc
            raise
        response, usage = self._chat(instruction, payload, max_seconds, max_tokens)
        try:
            decoded = references.decode_claims(source, parse_narrative_json(response.content))
            review = parse_local_review(json.dumps(decoded), source, plan, draft,
                                       f"deepseek-entailment.v1:{self.model}")
        except (ValueError, TypeError, KeyError) as exc:
            if complete_usage(response) is not None and response.total_tokens > 0:
                raise AccountedCompletionFailure("DEEPSEEK_REVIEW_CONTRACT_FAILED",
                    FailedCompletionUsage(*usage), failure_class="STRUCTURED_OUTPUT_ERROR") from exc
            raise StructuredOutputError("DEEPSEEK_REVIEW_CONTRACT_FAILED") from exc
        return replace(review, prompt_tokens=usage[0], completion_tokens=usage[1], total_tokens=usage[2])
