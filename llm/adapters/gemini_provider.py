# ============================================================
# Gemini Provider — Google AI SDK
# ============================================================
# Uses the official google-genai SDK (v2.x).
# All settings come from ProviderConfig, not from environment variables.
# ============================================================

import time
from typing import List

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
from ..providers.provider_models import (
    ChatRequest,
    ChatResponse,
    ProviderCapability,
)


class GeminiProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self._config = config
        self._api_key = config.api_key
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._timeout = config.timeout
        self._stream = config.stream
        self._max_retry = 3
        self._client = None
        self._provider_name = "gemini"

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def api_key(self) -> str:
        return self._api_key

    def get_capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_stream=False,
            supports_function_call=False,
            supports_image=False,
            supports_audio=False,
            supports_video=False,
            supports_json_mode=False,
            supports_embedding=False,
            supports_reranking=False,
            supports_reasoning_effort=False,
            supports_system_prompt=True,
            supports_tools=False,
            supports_multimodal=False,
            max_context_tokens=1048576,
        )

    def _get_client(self):
        if self._client is None:
            ensure_real_provider_allowed("gemini")
            if not self._api_key:
                raise AuthenticationError("GEMINI_API_KEY not set in environment")
            from google import genai

            self._client = genai.Client(api_key=self._api_key, http_options={"timeout": self._timeout * 1000})
        return self._client

    def _build_contents(self, request: ChatRequest) -> list:
        contents = []
        if request.system_prompt:
            contents.append(request.system_prompt)
            contents.append("")
        for msg in request.messages:
            content = msg.get("content", "")
            if content:
                contents.append(content)
        return contents

    def chat(self, request: ChatRequest) -> ChatResponse:
        client = self._get_client()
        model = self._model
        max_tokens = request.max_tokens or self._max_tokens

        # Build prompt: combine system prompt and messages
        prompt_parts = self._build_contents(request)
        prompt = "\n\n".join(prompt_parts)

        for attempt in range(self._max_retry):
            try:
                from google.genai import types

                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                    ),
                )

                text = response.text if response.text else ""

                usage = response.usage_metadata
                if usage:
                    prompt_tokens = usage.prompt_token_count or 0
                    completion_tokens = usage.candidates_token_count or 0
                    total_tokens = usage.total_token_count or 0
                else:
                    prompt_tokens = 0
                    completion_tokens = 0
                    total_tokens = 0

                return ChatResponse(
                    content=text.strip(),
                    provider=self._provider_name,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    metadata={
                        "finish_reason": getattr(
                            response.candidates[0].finish_reason, "name", str(response.candidates[0].finish_reason)
                        )
                        if response.candidates
                        else "unknown",
                    },
                )

            except Exception as e:
                error_str = str(e).lower()

                retryable = any(
                    [
                        "timeout" in error_str,
                        "connection" in error_str,
                        "429" in error_str,
                        "500" in error_str,
                        "503" in error_str,
                        "resource exhausted" in error_str,
                    ]
                )

                if "401" in error_str or "unauthorized" in error_str or "permission" in error_str:
                    raise AuthenticationError("Invalid Gemini API key") from e
                elif "429" in error_str or "resource exhausted" in error_str:
                    raise RateLimitError("Gemini rate limit exceeded") from e
                elif "404" in error_str or "model not found" in error_str:
                    raise ModelNotFoundError(f"Model not found: {model}") from e
                elif "connection" in error_str or "timeout" in error_str:
                    if not retryable or attempt >= self._max_retry - 1:
                        raise ProviderConnectionError(f"Cannot connect to Gemini: {str(e)}") from e
                else:
                    if not retryable or attempt >= self._max_retry - 1:
                        raise ProviderError(f"Gemini error: {str(e)}") from e

                if retryable and attempt < self._max_retry - 1:
                    wait_time = 2**attempt
                    time.sleep(wait_time)
                    continue

        raise ProviderError("Max retries exceeded")

    def health(self) -> bool:
        try:
            client = self._get_client()
            response = client.models.generate_content(
                model=self._model,
                contents="ping",
                config={"max_output_tokens": 5},
            )
            return response is not None
        except Exception:
            return False

    def list_models(self) -> List[str]:
        return [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ]
