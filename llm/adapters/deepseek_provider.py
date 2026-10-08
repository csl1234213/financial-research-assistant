# ============================================================
# DeepSeek Provider
# ============================================================
# DeepSeek uses OpenAI-compatible API, so we reuse openai-python SDK.
# All settings come from ProviderConfig, not from environment variables.
# ============================================================

import math
import os
import queue
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from logging import getLogger
from typing import List

import httpx
from openai import APIConnectionError, APITimeoutError, OpenAI

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
from ..providers.provider_models import (
    ChatRequest,
    ChatResponse,
    ProviderCapability,
)
from ..providers.timeout_policy import effective_timeout

logger = getLogger(__name__)


class DeepSeekProvider(BaseProvider):
    # Thinking tokens and the final answer share the provider's max_tokens
    # budget.  A thinking response that reaches the limit without a visible
    # answer is not useful to the application, so the recovery request keeps
    # a bounded answer-only budget instead of increasing the global limit.
    _ANSWER_RECOVERY_MAX_TOKENS = 2048

    def __init__(self, config: ProviderConfig, *, max_api_attempts: int = 3):
        if type(max_api_attempts) is not int or not 1 <= max_api_attempts <= 3:
            raise ValueError("INVALID_DEEPSEEK_ATTEMPT_LIMIT")
        self._config = config
        self._api_key = config.api_key
        self._base_url = config.base_url or "https://api.deepseek.com"
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._timeout = config.timeout
        self._connect_timeout = float(config.connect_timeout or config.timeout)
        self._read_timeout = float(config.read_timeout or config.timeout)
        self._total_deadline = config.total_deadline
        self._stream = config.stream
        self._max_retry = max_api_attempts
        self._client = None
        self._provider_name = "deepseek"

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def base_url(self) -> str:
        return self._base_url

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
            # Custom models outside this adapter's declared contract ignore
            # thinking_enabled; do not claim toggle support for those models.
            supports_thinking_control=self._model in self.list_models(),
            supports_tools=False,
            supports_multimodal=False,
            max_context_tokens=1_000_000,
        )

    def _get_client(self) -> OpenAI:
        if self._client is None:
            # Real provider access is an explicit opt-in in every runtime.
            # Production must not silently spend against a credential merely
            # because a persisted routing setting selects DeepSeek.  Pytest
            # adapter tests may inject an OpenAI test double; that constructor
            # is not a network client and remains allowed for retry-contract
            # coverage.
            provider_enabled = os.environ.get("ALLOW_REAL_PROVIDER", "false").lower() in {
                "1", "true", "yes"
            }
            injected_test_client = bool(
                os.environ.get("PYTEST_CURRENT_TEST")
                and not getattr(OpenAI, "__module__", "openai").startswith("openai")
            )
            if not provider_enabled and not injected_test_client:
                raise ProviderError(
                    "Real provider calls are disabled; "
                    "set ALLOW_REAL_PROVIDER=true only for an explicit live run"
                )
            if not self._api_key:
                raise AuthenticationError("DEEPSEEK_API_KEY not set in environment")
            # The adapter owns the retry budget; avoid SDK × adapter retries.
            timeout = httpx.Timeout(
                timeout=self._read_timeout,
                connect=self._connect_timeout,
            )
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=timeout,
                max_retries=0,
            )
        return self._client

    def _client_for_attempt(self, client: OpenAI, remaining: float | None) -> OpenAI:
        if remaining is None:
            return client
        timeout = httpx.Timeout(
            timeout=max(0.001, min(self._read_timeout, remaining)),
            connect=max(0.001, min(self._connect_timeout, remaining)),
        )
        with_options = getattr(client, "with_options", None)
        return with_options(timeout=timeout) if callable(with_options) else client

    @staticmethod
    def _invoke_with_deadline(call, remaining: float | None):
        """Bound a synchronous SDK call without leaving its result observable.

        The OpenAI client has its own socket timeout.  The daemon thread is a
        final containment boundary for injected/hung transports that ignore
        socket timeouts; on expiry the caller returns immediately and the late
        result is discarded.
        """

        if remaining is None:
            return call()
        result: queue.Queue = queue.Queue(maxsize=1)

        def run_call():
            try:
                result.put((True, call()))
            except BaseException as exc:  # re-raise on the request thread
                result.put((False, exc))

        worker = threading.Thread(target=run_call, name="llm-provider-call", daemon=True)
        worker.start()
        worker.join(timeout=max(0.001, remaining))
        if worker.is_alive():
            raise ProviderTimeoutError("LLM provider exceeded total request deadline",
                timeout_source="TOTAL_REQUEST_DEADLINE")
        ok, value = result.get_nowait()
        if ok:
            return value
        raise value

    def chat(self, request: ChatRequest) -> ChatResponse:
        if request.thinking_enabled is not None and type(request.thinking_enabled) is not bool:
            raise ProviderError("Invalid thinking mode")
        client = self._get_client()
        messages = []

        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        messages.extend(request.messages)

        model = self._model
        temperature = request.temperature
        max_tokens = request.max_tokens or self._max_tokens
        api_attempts = 0
        attempt_usage = []
        response_diagnostics = []

        def record_usage(response):
            from llm.providers.response_diagnostics import safe_response_diagnostics

            choice = response.choices[0]
            usage = getattr(response, "usage", None)
            details = getattr(usage, "completion_tokens_details", None)
            response_diagnostics.append(safe_response_diagnostics(
                choice.message.content, finish_reason=choice.finish_reason,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                reasoning_tokens=getattr(details, "reasoning_tokens", None)))
            while len(attempt_usage) < api_attempts - 1:
                attempt_usage.append(None)
            usage = getattr(response, "usage", None)
            values = tuple(getattr(usage, name, None) for name in
                           ("prompt_tokens", "completion_tokens", "total_tokens"))
            if (any(type(value) is not int or value < 0 for value in values)
                    or values[0] + values[1] != values[2]):
                attempt_usage.append(None)
            else:
                attempt_usage.append(dict(zip(
                    ("prompt_tokens", "completion_tokens", "total_tokens"), values)))

        recovery_attempted = False
        request_started = time.monotonic()
        deadline = request.deadline
        if self._total_deadline is not None:
            configured_deadline = request_started + self._total_deadline
            deadline = min(deadline, configured_deadline) if deadline is not None else configured_deadline
        deadline = request_started + effective_timeout(self._timeout, deadline, now=request_started)

        for attempt in range(self._max_retry):
            if api_attempts >= self._max_retry:
                break
            remaining = effective_timeout(self._timeout, deadline)
            try:
                api_attempts += 1
                attempt_started = time.monotonic()
                attempt_client = self._client_for_attempt(client, remaining)
                logger.info(
                    "deepseek_provider_attempt_started provider=deepseek attempt=%s",
                    api_attempts,
                )
                if model in self.list_models() and request.thinking_enabled is not False:
                    response = self._invoke_with_deadline(
                        lambda: attempt_client.chat.completions.create(
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            reasoning_effort="high",
                            extra_body={"thinking": {"type": "enabled"}},
                        ),
                        remaining,
                    )
                elif model in self.list_models():
                    response = self._invoke_with_deadline(
                        lambda: attempt_client.chat.completions.create(
                            model=model, messages=messages, temperature=temperature,
                            max_tokens=max_tokens, extra_body={"thinking": {"type": "disabled"}},
                        ), remaining,
                    )
                else:
                    response = self._invoke_with_deadline(
                        lambda: attempt_client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        ),
                        remaining,
                    )

                record_usage(response)
                choice = response.choices[0]
                content = choice.message.content.strip() if choice.message.content else ""

                # DeepSeek V4 can spend the whole budget in hidden thinking
                # and return an empty visible answer with finish_reason=length.
                # Retry once with thinking explicitly disabled and a bounded
                # answer budget.  Do not expose reasoning_content as the final
                # answer (it may contain chain-of-thought rather than a reply).
                if (
                    not content
                    and choice.finish_reason == "length"
                    and model in self.list_models()
                    and request.thinking_enabled is not False
                    and not recovery_attempted
                ):
                    recovery_attempted = True
                    recovery_tokens = max(
                        512,
                        min(max_tokens, self._ANSWER_RECOVERY_MAX_TOKENS),
                    )
                    api_attempts += 1
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise ProviderTimeoutError("LLM provider exceeded total request deadline",
                            timeout_source="TOTAL_REQUEST_DEADLINE")
                    response = self._invoke_with_deadline(
                        lambda: self._client_for_attempt(client, remaining)
                        .chat.completions.create(
                            model=model,
                            messages=messages,
                            max_tokens=recovery_tokens,
                            extra_body={"thinking": {"type": "disabled"}},
                        ),
                        remaining,
                    )
                    record_usage(response)
                    choice = response.choices[0]
                    content = choice.message.content.strip() if choice.message.content else ""

                usage = getattr(response, "usage", None)
                counts = tuple(getattr(usage, name, None) for name in
                               ("prompt_tokens", "completion_tokens", "total_tokens"))
                if api_attempts > 1:
                    if len(attempt_usage) == api_attempts and all(item is not None for item in attempt_usage):
                        counts = tuple(sum(item[name] for item in attempt_usage) for name in
                                       ("prompt_tokens", "completion_tokens", "total_tokens"))
                    else:
                        counts = (None, None, None)

                logger.info(
                    "deepseek_provider_attempt_completed provider=deepseek attempt=%s duration_ms=%.2f",
                    api_attempts,
                    (time.monotonic() - attempt_started) * 1000,
                )

                return ChatResponse(
                    content=content,
                    provider=self._provider_name,
                    model=model,
                    prompt_tokens=counts[0],
                    completion_tokens=counts[1],
                    total_tokens=counts[2],
                    metadata={
                        "api_attempts": api_attempts,
                        "attempt_usage": attempt_usage,
                        "response_diagnostics": response_diagnostics,
                        "reasoning_tokens": response_diagnostics[-1]["reasoning_tokens"],
                        "all_attempt_usage_complete": (
                            len(attempt_usage) == api_attempts
                            and all(item is not None for item in attempt_usage)
                        ),
                        "finish_reason": choice.finish_reason,
                        "usage_available": usage is not None,
                        "cached_tokens": getattr(usage, "prompt_cache_hit_tokens", None) if usage else None,
                        "served_model": getattr(response, "model", None),
                    },
                )
            except ProviderTimeoutError:
                logger.warning(
                    "deepseek_provider_timeout provider=deepseek attempts=%s duration_ms=%.2f",
                    api_attempts,
                    (time.monotonic() - request_started) * 1000,
                )
                raise
            except Exception as e:
                if isinstance(e, (APITimeoutError, httpx.TimeoutException)):
                    source = "CONNECTION_TIMEOUT" if isinstance(e, httpx.ConnectTimeout) else "HTTP_TIMEOUT"
                    raise ProviderTimeoutError("DeepSeek generation request timed out",
                        timeout_source=source) from e
                status = getattr(e, "status_code", None)
                error_str = str(e).lower() if status is None else ""
                connection = isinstance(e, (APIConnectionError, APITimeoutError)) or any(
                    word in error_str for word in ("connection", "timeout", "timed out", "nameresolution")
                )
                if status == 401 or "401" in error_str or "unauthorized" in error_str:
                    raise AuthenticationError("Invalid DeepSeek API key") from e
                if status == 402 or "402" in error_str:
                    raise RateLimitError("Insufficient balance") from e
                if status == 404 or "404" in error_str or "model not found" in error_str:
                    raise ModelNotFoundError(f"Model not found: {model}") from e
                limited = status == 429 or (status is None and "429" in error_str)
                server_error = isinstance(status, int) and 500 <= status < 600
                retryable = (
                    limited
                    or server_error
                    or connection
                    or (status is None and any(code in error_str for code in ("500", "503")))
                )
                delay = 2**attempt + random.uniform(0, 0.25)
                retry_after = getattr(getattr(e, "response", None), "headers", {}).get("Retry-After")
                if retry_after is not None:
                    try:
                        seconds = float(retry_after)
                    except ValueError:
                        try:
                            when = parsedate_to_datetime(retry_after)
                            seconds = (when - datetime.now(timezone.utc)).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            seconds = 0
                    if math.isfinite(seconds):
                        delay = max(delay, seconds)
                remaining = None if deadline is None else deadline - time.monotonic()
                if deadline is not None and retryable and (
                    remaining is not None and remaining <= delay
                ):
                    raise ProviderTimeoutError("LLM provider exceeded total request deadline",
                        timeout_source="TOTAL_REQUEST_DEADLINE") from e
                if retryable and api_attempts < self._max_retry and delay <= 60 and (
                    remaining is None or delay < remaining
                ):
                    time.sleep(delay if remaining is None else min(delay, remaining))
                    continue
                if connection and deadline is not None and (
                    remaining is not None and remaining <= 0
                ):
                    raise ProviderTimeoutError("LLM provider exceeded total request deadline",
                        timeout_source="TOTAL_REQUEST_DEADLINE") from e
                if limited:
                    raise RateLimitError("Rate limit exceeded; retry budget exhausted") from e
                if connection:
                    raise ProviderConnectionError("Cannot connect to DeepSeek; retry budget exhausted") from e
                # Do not expose upstream bodies, credentials or request headers.
                raise ProviderError("DeepSeek request failed") from e

        if deadline is not None and time.monotonic() >= deadline:
            raise ProviderTimeoutError("LLM provider exceeded total request deadline",
                timeout_source="TOTAL_REQUEST_DEADLINE")
        raise ProviderError("Max retries exceeded")

    def health(self) -> bool:
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return response is not None
        except Exception:
            return False

    def list_models(self) -> List[str]:
        return [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ]
