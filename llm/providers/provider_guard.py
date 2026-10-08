"""Explicit opt-in guard for network-backed LLM providers."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from .provider_exceptions import ProviderError

_ENABLED = {"1", "true", "yes"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"}


def normalize_local_ollama_url(value: str | None) -> str:
    """Accept only an explicit local Ollama HTTP endpoint, never an arbitrary URL."""

    candidate = (value or "http://host.docker.internal:11434").strip()
    try:
        parsed = urlsplit(candidate)
        hostname = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Ollama endpoint is invalid") from exc
    if (
        parsed.scheme != "http"
        or hostname not in _LOCAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Ollama endpoint must use an allowed local host and HTTP")
    netloc = hostname if port is None else f"{hostname}:{port}"
    return urlunsplit(("http", netloc, "", "", ""))


def ensure_real_provider_allowed(provider: str, base_url: str | None = None) -> None:
    """Fail closed before constructing an external network client.

    A local OpenAI-compatible endpoint (for example Ollama) is intentionally
    allowed without the paid-provider opt-in. Every non-local endpoint requires
    an explicit ``ALLOW_REAL_PROVIDER=true`` setting.
    """

    if os.environ.get("ALLOW_REAL_PROVIDER", "false").casefold() in _ENABLED:
        return
    if base_url:
        hostname = (urlsplit(base_url).hostname or "").casefold()
        if hostname in _LOCAL_HOSTS:
            return
    raise ProviderError(
        f"Real provider calls are disabled for {provider}; "
        "set ALLOW_REAL_PROVIDER=true only for an explicit live run"
    )
