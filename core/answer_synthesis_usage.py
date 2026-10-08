"""Accounted failed completions are receipts, never answer authorization."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FailedCompletionUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __post_init__(self):
        values = (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        if (any(type(value) is not int or value < 0 for value in values)
                or self.total_tokens <= 0
                or self.prompt_tokens + self.completion_tokens != self.total_tokens):
            raise ValueError("INVALID_FAILED_COMPLETION_USAGE")


class AccountedCompletionFailure(ValueError):
    """A failed single completion with validated identity and complete usage."""

    def __init__(self, code: str, usage: FailedCompletionUsage, *, failure_class="GENERATION_FAILURE"):
        if not isinstance(usage, FailedCompletionUsage):
            raise ValueError("FAILED_COMPLETION_RECEIPT_REQUIRED")
        super().__init__(code)
        self.usage = usage
        self.failure_class = failure_class


class ProviderPreflightFailure(ValueError):
    """Validated input overflow before any Provider attempt, not a timeout."""

    def __init__(self, code: str, input_bytes: int):
        if code != "SEMANTIC_INPUT_BUDGET_EXCEEDED" or type(input_bytes) is not int or input_bytes <= 16000:
            raise ValueError("INVALID_PROVIDER_PREFLIGHT_RECEIPT")
        super().__init__(code)
        self.input_bytes = input_bytes


class ReviewBatchPreflightFailure(ValueError):
    """Batch admission rejected before any review invocation; zero review usage."""

    def __init__(self, code: str):
        if code not in {"BATCH_REVIEW_RESERVATION_EXCEEDED", "BATCH_REVIEW_DEADLINE_EXHAUSTED",
                        "REVIEW_SINGLE_CLAIM_EXCEEDS_INPUT_BUDGET", "REVIEW_BATCH_LIMIT_EXCEEDED",
                        "REVIEW_DRAFT_PROJECTION_CHANGED"}:
            raise ValueError("INVALID_BATCH_PREFLIGHT_RECEIPT")
        super().__init__(code)
