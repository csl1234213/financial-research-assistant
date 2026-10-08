"""Native Ollama chat adapter for local, provider-cost-free evaluation."""

from __future__ import annotations

import time

import httpx

from ..providers.base_provider import BaseProvider
from ..providers.provider_config import ProviderConfig
from ..providers.provider_exceptions import (
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from ..providers.provider_guard import normalize_local_ollama_url
from ..providers.provider_models import ChatRequest, ChatResponse, ProviderCapability
from ..providers.timeout_policy import effective_timeout, invoke_with_deadline


class OllamaProvider(BaseProvider):
    """Call Ollama's native ``/api/chat`` endpoint without OpenAI shims."""

    def __init__(self, config: ProviderConfig):
        self._config = config
        self._model = config.model
        self._base_url = (config.base_url or "http://host.docker.internal:11434").rstrip("/")
        self._timeout = config.timeout

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_system_prompt=True,
            max_context_tokens=8192,
        )

    def _validate_local_endpoint(self) -> None:
        try:
            self._base_url = normalize_local_ollama_url(self._base_url)
        except ValueError as exc:
            raise ProviderError("Ollama provider requires an explicitly local endpoint") from exc

    def _timeout_config(self, request: ChatRequest | None = None) -> httpx.Timeout:
        configured = (min(self._timeout, self._config.total_deadline)
                      if self._config.total_deadline is not None else self._timeout)
        remaining = effective_timeout(configured, request.deadline if request is not None else None)
        connect = min(float(self._config.connect_timeout or remaining), remaining)
        read = min(float(self._config.read_timeout or remaining), remaining)
        return httpx.Timeout(remaining, connect=connect, read=read)

    def chat(self, request: ChatRequest) -> ChatResponse:
        self._validate_local_endpoint()
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)
        options = {
            "temperature": request.temperature,
            "num_ctx": self.get_capability().max_context_tokens,
            "num_predict": request.max_tokens or self._config.max_tokens,
        }
        payload = {
            "model": self._model,
            "messages": messages,
            "think": False,
            "stream": False,
            "options": options,
        }
        started = time.monotonic()
        configured = (min(self._timeout, self._config.total_deadline)
                      if self._config.total_deadline is not None else self._timeout)
        allowance = effective_timeout(configured, request.deadline, now=started)
        deadline = started + allowance

        def call():
            with httpx.Client(timeout=self._timeout_config(request)) as client:
                return client.post(f"{self._base_url}/api/chat", json=payload)

        try:
            response = invoke_with_deadline(call, allowance)
            if response.status_code == 404:
                raise ModelNotFoundError(f"Ollama model or endpoint not found: {self._model}")
            response.raise_for_status()
            body = response.json()
            effective_timeout(configured, deadline)
        except httpx.TimeoutException as exc:
            source = "CONNECTION_TIMEOUT" if isinstance(exc, httpx.ConnectTimeout) else "HTTP_TIMEOUT"
            if request.deadline is not None and time.monotonic() >= request.deadline:
                source = "TOTAL_REQUEST_DEADLINE"
            raise ProviderTimeoutError("Ollama request timed out", timeout_source=source) from exc
        except httpx.ConnectError as exc:
            raise ProviderConnectionError("Cannot connect to local Ollama") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError("Ollama request failed") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise ProviderError("Ollama returned an invalid response") from exc

        message = body.get("message")
        content = message.get("content", "").strip() if isinstance(message, dict) else ""
        if not content:
            raise ProviderError("Ollama returned empty model content")
        prompt_tokens = body.get("prompt_eval_count")
        completion_tokens = body.get("eval_count")
        total_tokens = (prompt_tokens + completion_tokens
                        if type(prompt_tokens) is int and type(completion_tokens) is int else None)
        return ChatResponse(
            content=content,
            provider=self.provider_name,
            model=str(body.get("model") or self._model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            metadata={
                "done_reason": body.get("done_reason"),
                "latency_seconds": round(time.monotonic() - started, 3),
            },
        )

    def health(self) -> bool:
        try:
            self._validate_local_endpoint()
            with httpx.Client(timeout=self._timeout_config()) as client:
                response = client.get(f"{self._base_url}/api/tags")
                return response.is_success
        except (httpx.RequestError, ProviderError):
            return False

    def list_models(self) -> list[str]:
        return [self._model]
