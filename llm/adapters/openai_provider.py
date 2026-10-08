"""OpenAI Chat Completions provider."""

from __future__ import annotations

import time
from typing import Any, ClassVar

import httpx
from openai import OpenAI

from ..providers.base_provider import BaseProvider
from ..providers.provider_config import ProviderConfig
from ..providers.provider_exceptions import (
    AuthenticationError,
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
)
from ..providers.provider_guard import ensure_real_provider_allowed
from ..providers.provider_models import ChatRequest, ChatResponse, ProviderCapability
from ..providers.timeout_policy import effective_timeout, invoke_with_deadline


class OpenAIProvider(BaseProvider):
    """Text-only adapter for the OpenAI reasoning-model family."""

    MODELS: ClassVar[list[str]] = [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
    ]
    MODEL_CONTEXT_TOKENS: ClassVar[dict[str, int]] = {
        "gpt-5.5": 1_050_000,
        "gpt-5.4": 1_050_000,
        "gpt-5.4-mini": 400_000,
        "gpt-5.4-nano": 400_000,
    }

    def __init__(self, config: ProviderConfig):
        self._config = config
        self._api_key = config.api_key
        self._base_url = config.base_url
        self._model = config.model
        self._max_tokens = config.max_tokens
        self._timeout = config.timeout
        self._max_retry = 3
        self._client: Any = None

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_reasoning_effort=True,
            supports_system_prompt=True,
            max_context_tokens=self.MODEL_CONTEXT_TOKENS.get(
                self._model,
                400_000,
            ),
        )

    def _get_client(self) -> OpenAI:
        if self._client is None:
            ensure_real_provider_allowed("openai", self._base_url)
            if not self._api_key:
                raise AuthenticationError("OpenAI API key is not configured")
            options: dict[str, object] = {
                "api_key": self._api_key,
                "timeout": self._timeout,
                "max_retries": 0,
            }
            if self._base_url:
                options["base_url"] = self._base_url
            self._client = OpenAI(**options)
        return self._client

    @staticmethod
    def _messages(request: ChatRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)
        return messages

    def chat(self, request: ChatRequest) -> ChatResponse:
        started = time.monotonic()
        deadline = request.deadline
        if self._config.total_deadline is not None:
            configured_deadline = started + self._config.total_deadline
            deadline = min(deadline, configured_deadline) if deadline is not None else configured_deadline
        deadline = started + effective_timeout(self._timeout, deadline, now=started)
        client = self._get_client()
        max_tokens = request.max_tokens or self._max_tokens

        for attempt in range(self._max_retry):
            try:
                remaining = effective_timeout(self._timeout, deadline)
                attempt_client = client
                with_options = getattr(client, "with_options", None)
                if callable(with_options):
                    attempt_client = with_options(timeout=httpx.Timeout(remaining,
                        connect=min(float(self._config.connect_timeout or remaining), remaining),
                        read=min(float(self._config.read_timeout or remaining), remaining)))
                response = invoke_with_deadline(lambda: attempt_client.chat.completions.create(
                    model=self._model,
                    messages=self._messages(request),
                    max_completion_tokens=max_tokens,
                    reasoning_effort="medium",
                ), remaining)
                effective_timeout(self._timeout, deadline)
                choice = response.choices[0]
                usage = getattr(response, "usage", None)
                return ChatResponse(
                    content=(choice.message.content or "").strip(),
                    provider=self.provider_name,
                    model=self._model,
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                    metadata={"finish_reason": choice.finish_reason},
                )
            except Exception as exc:
                if self._raise_or_retry(exc, attempt):
                    delay = 2**attempt
                    if deadline is not None and deadline - time.monotonic() <= delay:
                        raise ProviderTimeoutError("OpenAI total request deadline exhausted",
                            timeout_source="TOTAL_REQUEST_DEADLINE") from exc
                    time.sleep(delay)

        raise ProviderError("OpenAI request failed after retries")

    def _raise_or_retry(self, exc: Exception, attempt: int) -> bool:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__.lower()
        if isinstance(exc, ProviderTimeoutError):
            raise exc
        if isinstance(exc, httpx.TimeoutException) or "timeout" in name:
            source = "CONNECTION_TIMEOUT" if isinstance(exc, httpx.ConnectTimeout) else "HTTP_TIMEOUT"
            raise ProviderTimeoutError("OpenAI generation request timed out",
                timeout_source=source) from exc
        retryable = status in {408, 429, 500, 502, 503, 504} or any(
            marker in name for marker in ("connection",)
        )
        if status in {401, 403} or "authentication" in name:
            raise AuthenticationError("OpenAI authentication failed") from exc
        if status == 404 or "notfound" in name:
            raise ModelNotFoundError(f"Model not found: {self._model}") from exc
        if retryable and attempt < self._max_retry - 1:
            return True
        if status == 429 or "ratelimit" in name:
            raise RateLimitError("OpenAI rate limit exceeded") from exc
        if any(marker in name for marker in ("timeout", "connection")):
            raise ProviderConnectionError("Cannot connect to OpenAI") from exc
        raise ProviderError("OpenAI request failed") from exc

    def health(self) -> bool:
        try:
            response = self._get_client().chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_completion_tokens=1,
                reasoning_effort="medium",
            )
            return response is not None
        except Exception:
            return False

    def list_models(self) -> list[str]:
        return list(self.MODELS)
