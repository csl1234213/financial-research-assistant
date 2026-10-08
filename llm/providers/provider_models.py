# ============================================================
# Provider Models — Unified Request / Response
# ============================================================
# All LLM providers return the same ChatResponse object,
# regardless of the underlying SDK (DeepSeek, Claude, Gemini, etc.)
# ============================================================

from dataclasses import dataclass, field
from enum import StrEnum

from llm.providers.response_diagnostics import safe_response_diagnostics


class GenerationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    STRUCTURED_OUTPUT_ERROR = "STRUCTURED_OUTPUT_ERROR"


class UsageStatus(StrEnum):
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class ProviderCapability:
    """Provider capabilities abstraction.

    Agent Runtime can make decisions based on capabilities instead of
    checking if provider == "deepseek", which makes the code cleaner
    and supports future providers without changes.

    Each provider declares only capabilities implemented by this adapter's
    public contract. A vendor supporting a feature is not sufficient if the
    local ``ChatRequest``/``chat`` path cannot accept and execute it.
    Planner / Agent uses these fields to auto-select the best provider.
    """

    supports_stream: bool = False
    supports_function_call: bool = False
    supports_image: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    supports_json_mode: bool = False
    supports_embedding: bool = False
    supports_reranking: bool = False
    supports_reasoning_effort: bool = False
    supports_system_prompt: bool = False
    supports_tools: bool = False
    supports_multimodal: bool = False
    max_context_tokens: int = 4096
    supports_usage: bool = True
    supports_cancellation: bool = False
    supports_thinking_control: bool = False


@dataclass
class ChatRequest:
    messages: list
    temperature: float = 0.0
    max_tokens: int | None = None
    system_prompt: str | None = None
    deadline: float | None = None
    thinking_enabled: bool | None = None


@dataclass
class ChatResponse:
    content: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    metadata: dict = field(default_factory=dict)
    generation_status: GenerationStatus = GenerationStatus.SUCCESS
    usage_status: UsageStatus | None = None
    finish_reason: str | None = None
    provider_request_id: str | None = None
    failure_class: str | None = None

    def __post_init__(self):
        """Missing telemetry never changes generation success; never invent counts."""
        self.generation_status = GenerationStatus(self.generation_status)
        values = (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        valid = tuple(type(value) is int and value >= 0 for value in values)
        if self.usage_status is not None:
            self.usage_status = UsageStatus(self.usage_status)
        elif all(valid) and values[0] + values[1] == values[2]:
            self.usage_status = UsageStatus.KNOWN
        elif any(valid):
            self.usage_status = UsageStatus.PARTIAL
        else:
            self.usage_status = UsageStatus.UNKNOWN
        # Malformed usage is unavailable telemetry, not a transport failure.
        for name, value, usable in zip(("prompt_tokens", "completion_tokens", "total_tokens"), values, valid):
            if value is not None and not usable:
                setattr(self, name, None)
        if self.finish_reason is None or "finish_reason" in self.metadata or "done_reason" in self.metadata:
            self.finish_reason = self.metadata.get("finish_reason", self.metadata.get("done_reason"))
        self.metadata["safe_response_diagnostics"] = safe_response_diagnostics(
            self.content, finish_reason=self.finish_reason, prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens, total_tokens=self.total_tokens,
            reasoning_tokens=self.metadata.get("reasoning_tokens"))
