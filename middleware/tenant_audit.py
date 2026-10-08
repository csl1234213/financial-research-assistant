import json
import logging
import time
import uuid
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config.security import AUDIT_LOG_ENABLED

logger = logging.getLogger("tenant_audit")


class TenantAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = getattr(request.state, "request_id", None) or request.headers.get(
            "X-Request-ID"
        )
        request_id = request_id or str(uuid.uuid4())
        request.state.request_id = request_id

        start_time = time.time()

        response = await call_next(request)

        if AUDIT_LOG_ENABLED:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)

            tenant_id: Optional[str] = None
            user_id: Optional[str] = None

            if hasattr(request.state, "tenant_id"):
                tenant_id = str(request.state.tenant_id)
            if hasattr(request.state, "user_id"):
                user_id = str(request.state.user_id)

            audit_entry = {
                "request_id": request_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "endpoint": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            }

            logger.info(json.dumps(audit_entry, ensure_ascii=False))

        return response
