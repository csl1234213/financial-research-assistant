"""Volcengine Ark/Doubao OpenAI-compatible provider."""

from __future__ import annotations

import time
from typing import Any, ClassVar

from openai import OpenAI

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


class DoubaoProvider(BaseProvider):
    BASE_URL: ClassVar[str] = "https://ark.cn-beijing.volces.com/api/v3"
    MODELS: ClassVar[list[str]] = [
        "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-0-lite-260215",
        "doubao-seed-2-0-mini-260215",
    ]

    def __init__(self, config: ProviderConfig):
        self._config = config
        self._api_key = config.api_key
        self._base_url = config.base_url or self.BASE_URL
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._timeout = config.timeout
        self._max_retry = 3
        self._client: Any = None

    @property
    def provider_name(self) -> str:
        return "doubao"

    @property
    def model(self) -> str:
        return self._model

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_system_prompt=True,
            max_context_tokens=256_000,
        )

    def _get_client(self) -> OpenAI:
        if self._client is None:
            ensure_real_provider_allowed("doubao", self._base_url)
            if not self._api_key:
                raise AuthenticationError("Doubao API key is not configured")
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=0,
            )
        return self._client

    @staticmethod
    def _messages(request: ChatRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)
        return messages

    def chat(self, request: ChatRequest) -> ChatResponse:
        client = self._get_client()
        for attempt in range(self._max_retry):
            try:
                response = client.chat.completions.create(
                    model=self._model,
                    messages=self._messages(request),
                    temperature=request.temperature,
                    max_tokens=request.max_tokens or self._max_tokens,
                )
                choice = response.choices[0]
                usage = response.usage
                return ChatResponse(
                    content=(choice.message.content or "").strip(),
                    provider=self.provider_name,
                    model=self._model,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                    metadata={"finish_reason": choice.finish_reason},
                )
            except Exception as exc:
                if self._raise_or_retry(exc, attempt):
                    time.sleep(2**attempt)

        raise ProviderError("Doubao request failed after retries")

    def _raise_or_retry(self, exc: Exception, attempt: int) -> bool:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__.lower()
        retryable = status in {408, 429, 500, 502, 503, 504} or any(
            marker in name for marker in ("timeout", "connection")
        )
        if status in {401, 403} or "authentication" in name:
            raise AuthenticationError("Doubao authentication failed") from exc
        if status == 404 or "notfound" in name:
            raise ModelNotFoundError(f"Model not found: {self._model}") from exc
        if status == 429 or "ratelimit" in name:
            raise RateLimitError("Doubao rate limit exceeded") from exc
        if retryable and attempt < self._max_retry - 1:
            return True
        if any(marker in name for marker in ("timeout", "connection")):
            raise ProviderConnectionError("Cannot connect to Doubao") from exc
        raise ProviderError("Doubao request failed") from exc

    def health(self) -> bool:
        try:
            response = self._get_client().chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return response is not None
        except Exception:
            return False

    def list_models(self) -> list[str]:
        return list(self.MODELS)
