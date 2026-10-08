"""Anthropic Claude Messages API provider."""

from __future__ import annotations

import time
from typing import Any, ClassVar

from ..providers.base_provider import BaseProvider
from ..providers.provider_config import ProviderConfig
from ..providers.provider_exceptions import (
    AuthenticationError,
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderError,
    RateLimitError,
)
from ..providers.provider_guard import ensure_real_provider_allowed
from ..providers.provider_models import ChatRequest, ChatResponse, ProviderCapability


class ClaudeProvider(BaseProvider):
    MODELS: ClassVar[list[str]] = [
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
    ]
    MODEL_CONTEXT_TOKENS: ClassVar[dict[str, int]] = {
        "claude-fable-5": 1_000_000,
        "claude-opus-4-8": 1_000_000,
        "claude-sonnet-5": 1_000_000,
        "claude-haiku-4-5-20251001": 200_000,
    }

    def __init__(self, config: ProviderConfig):
        self._config = config
        self._api_key = config.api_key
        self._base_url = config.base_url
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._timeout = config.timeout
        self._max_retry = 3
        self._client: Any = None

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_system_prompt=True,
            max_context_tokens=self.MODEL_CONTEXT_TOKENS.get(
                self._model,
                200_000,
            ),
        )

    def _get_client(self) -> Any:
        if self._client is None:
            ensure_real_provider_allowed("anthropic", self._base_url)
            if not self._api_key:
                raise AuthenticationError("Anthropic API key is not configured")
            from anthropic import Anthropic

            options: dict[str, object] = {
                "api_key": self._api_key,
                "timeout": self._timeout,
                "max_retries": 0,
            }
            if self._base_url:
                options["base_url"] = self._base_url
            self._client = Anthropic(**options)
        return self._client

    def chat(self, request: ChatRequest) -> ChatResponse:
        client = self._get_client()
        payload: dict[str, object] = {
            "model": self._model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or self._max_tokens,
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt

        for attempt in range(self._max_retry):
            try:
                response = client.messages.create(**payload)
                content = "".join(
                    block.text
                    for block in response.content
                    if getattr(block, "type", None) == "text"
                )
                usage = response.usage
                prompt_tokens = getattr(usage, "input_tokens", 0)
                completion_tokens = getattr(usage, "output_tokens", 0)
                return ChatResponse(
                    content=content.strip(),
                    provider=self.provider_name,
                    model=self._model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    metadata={"finish_reason": response.stop_reason},
                )
            except Exception as exc:
                if self._raise_or_retry(exc, attempt):
                    time.sleep(2**attempt)

        raise ProviderError("Anthropic request failed after retries")

    def _raise_or_retry(self, exc: Exception, attempt: int) -> bool:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__.lower()
        retryable = status in {408, 429, 500, 502, 503, 504} or any(
            marker in name for marker in ("timeout", "connection")
        )
        if status in {401, 403} or "authentication" in name:
            raise AuthenticationError("Anthropic authentication failed") from exc
        if status == 404 or "notfound" in name:
            raise ModelNotFoundError(f"Model not found: {self._model}") from exc
        if status == 429 or "ratelimit" in name:
            raise RateLimitError("Anthropic rate limit exceeded") from exc
        if retryable and attempt < self._max_retry - 1:
            return True
        if any(marker in name for marker in ("timeout", "connection")):
            raise ProviderConnectionError("Cannot connect to Anthropic") from exc
        raise ProviderError("Anthropic request failed") from exc

    def health(self) -> bool:
        try:
            response = self._get_client().messages.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return response is not None
        except Exception:
            return False

    def list_models(self) -> list[str]:
        return list(self.MODELS)
