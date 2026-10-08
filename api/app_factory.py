import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.__version__ import __version__
from middleware.security import (
    RateLimitMiddleware,
    RequestIDMiddleware,
    RequestTimingMiddleware,
    SecurityHeadersMiddleware,
)
from middleware.tenant_audit import TenantAuditMiddleware

DEFAULT_CORS_ORIGINS = ("http://localhost:5173",)
_PRODUCTION_ENVIRONMENTS = {"production", "prod"}


def get_cors_origins(
    raw_origins: str | None = None,
    *,
    app_env: str | None = None,
) -> list[str]:
    """Parse the comma-separated CORS allowlist supplied by the environment."""

    configured_origins = raw_origins if raw_origins is not None else os.getenv("CORS_ORIGINS", "")
    origins = [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]
    if origins:
        return origins

    environment = (app_env if app_env is not None else os.getenv("APP_ENV", "development"))
    if environment.strip().lower() in _PRODUCTION_ENVIRONMENTS:
        raise RuntimeError("CORS_ORIGINS must be explicitly configured when APP_ENV=production.")
    return list(DEFAULT_CORS_ORIGINS)


def get_positive_int_setting(name: str, default: int) -> int:
    """Read a positive integer setting and fail fast on invalid deployment input."""

    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def create_app(*, profile="query", ingestion_routers=()):
    """Compose the existing API or an explicit ingestion-only service subset."""
    if profile not in {"query", "ingestion"}:
        raise ValueError("INVALID_APPLICATION_PROFILE")
    app = FastAPI(
        title="Financial Research Copilot API",
        description="Production API for Financial Research Copilot",
        version=__version__,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(TenantAuditMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_window=get_positive_int_setting("RATE_LIMIT_REQUESTS", 100),
        window_seconds=get_positive_int_setting("RATE_LIMIT_WINDOW", 60),
    )


    if profile == "query":
        from api.routers.agent import router as agent_router
        from api.routers.agent_sessions import router as agent_sessions_router
        from api.routers.auth import router as auth_router
        from api.routers.billing import router as billing_router
        from api.routers.chat import router as chat_router
        from api.routers.grounded_answers import build_grounded_answer_router
        from api.routers.health import health as system_health
        from api.routers.health import router as health_router
        from api.routers.knowledge import router as knowledge_router
        from api.routers.monitoring import router as monitoring_router
        from api.routers.refresh import router as refresh_router
        from api.routers.settings import router as settings_router
        from api.routers.source_documents import build_source_document_router
        from api.routers.subscription import router as subscription_router
        from api.routers.tasks import router as tasks_router
        from api.routers.tenant import router as tenant_router
        from api.routers.upload import router as upload_router
        from api.routers.upload_sessions import build_upload_session_router
        from api.routers.usage import router as usage_router
        from services.rc1_delivery import (
            LazyLedger,
            LazyUploadService,
            resolve_grounded_source,
            resolve_narrative_ports,
            source_service,
        )
        app.include_router(health_router, prefix="/api/v1")
        app.include_router(chat_router, prefix="/api/v1")
        app.include_router(knowledge_router, prefix="/api/v1")
        app.include_router(upload_router, prefix="/api/v1")
        app.include_router(refresh_router, prefix="/api/v1")
        app.include_router(settings_router, prefix="/api/v1")
        app.include_router(auth_router, prefix="/api/v1/auth")
        app.include_router(tasks_router, prefix="/api/v1")
        app.include_router(usage_router, prefix="/api/v1")
        app.include_router(subscription_router, prefix="/api/v1")
        app.include_router(tenant_router, prefix="/api/v1")
        app.include_router(agent_router, prefix="/api/v1")
        app.include_router(agent_sessions_router, prefix="/api/v1")
        app.include_router(billing_router, prefix="/api/v1")
        app.include_router(monitoring_router, prefix="/api/v1")
        app.include_router(build_upload_session_router(
            LazyUploadService(), ingestion_ledger=LazyLedger(), transport_protocol="legacy_multipart",
        ), prefix="/api/v1")
        app.include_router(build_source_document_router(source_service), prefix="/api/v1")
        app.include_router(build_grounded_answer_router(
            LazyLedger(), source_resolver=resolve_grounded_source,
            narrative_ports_resolver=resolve_narrative_ports,
            narrative_max_total_tokens=16384,
        ), prefix="/api/v1")



    else:
        for router in ingestion_routers:
            app.include_router(router)

        @app.get("/api/v1/health")
        def ingestion_liveness():
            return {"status": "ok", "capability": "ingestion"}

    @app.get("/")
    def root():
        return {"service": "Financial Research Copilot", "version": __version__}

    @app.get("/health")
    def health_root():
        if profile == "ingestion":
            return ingestion_liveness()
        return system_health()

    return app
