import hashlib
import ipaddress
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("security")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_HEALTH_PATHS = {
    "/health",
    "/api/v1/health",
    "/api/v1/ready",
}


def _rate_limit_identity(request: Request) -> str:
    """Return a privacy-preserving, proxy-aware client identity."""

    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and token.strip():
        digest = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()[:24]
        return f"auth:{digest}"

    trust_proxy = (
        os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower()
        in _TRUE_VALUES
    )
    if trust_proxy:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        candidate = forwarded_for.split(",", maxsplit=1)[0].strip()
        if candidate:
            try:
                return f"ip:{ipaddress.ip_address(candidate)}"
            except ValueError:
                logger.warning("Ignoring invalid X-Forwarded-For address")

    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_window: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._clients: Dict[str, Tuple[int, datetime]] = defaultdict(
            lambda: (0, datetime.now(timezone.utc))
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() not in _TRUE_VALUES:
            return await call_next(request)

        if request.url.path in _HEALTH_PATHS:
            return await call_next(request)

        client_id = _rate_limit_identity(request)
        now = datetime.now(timezone.utc)

        count, window_start = self._clients[client_id]

        if now - window_start > timedelta(seconds=self.window_seconds):
            count = 0
            window_start = now

        count += 1
        self._clients[client_id] = (count, window_start)

        if count > self.requests_per_window:
            logger.warning(
                "Rate limit exceeded for %s: %s/%s",
                client_id,
                count,
                self.requests_per_window,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "retry_after": self.window_seconds,
                },
            )

        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Download-Options"] = "noopen"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = await call_next(request)
        elapsed_ms = round((time.time() - start) * 1000, 2)
        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        return response
