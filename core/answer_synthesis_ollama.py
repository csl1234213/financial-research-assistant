"""Explicit opt-in local Qwen port; never resolves workspace keys or cloud providers."""

from __future__ import annotations

import time

from core.answer_provider_port import chat_answer, resolve_answer_provider
from core.answer_synthesis_draft_verifier import factual_sentence_variants
from core.answer_synthesis_workflow import DraftCandidate, DraftRequest
from llm.providers.provider_exceptions import StructuredOutputError


class LocalQwenDraftGenerator:
    def __init__(self, *, model=None, base_url="http://127.0.0.1:11434", enabled=False,
                 provider=None, provider_config=None):
        self.provider = resolve_answer_provider(provider=provider, provider_config=provider_config,
                                               model=model, base_url=base_url)
        self.model = self.provider.model
        self.enabled = enabled is True

    def generate(self, request: DraftRequest) -> DraftCandidate:
        if not self.enabled:
            raise ValueError("local Qwen generation is disabled")
        remaining = request.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("deadline exhausted before local request")
        variants = factual_sentence_variants(request.source, request.plan)
        choices = "\n".join(options[1] for options in variants)
        instruction = (
            "Return only the grounded answer below in the requested language. Preserve every number, "
            "period, company, scope and citation. No headings, comments or new claims. No reasoning."
        )
        user_text = f"Language: {request.source.locale}\nGrounded factual answer:\n{choices}"
        if request.feedback_codes:
            user_text += "\nPrevious verification failure codes: " + ",".join(request.feedback_codes)
        # Conservative preflight ceiling, not a tokenizer-exact usage promise.
        estimate = len((instruction + user_text).encode("utf-8")) + 512
        allowed_output = min(request.max_output_tokens, request.remaining_total_tokens - estimate)
        if allowed_output <= 0:
            raise ValueError("input leaves no generation token budget")
        response = chat_answer(self.provider, instruction, user_text,
                               max_seconds=remaining, max_tokens=allowed_output)
        if response.finish_reason != "stop":
            raise StructuredOutputError("truncated or incomplete local output")
        return DraftCandidate(response.content, response.total_tokens)
