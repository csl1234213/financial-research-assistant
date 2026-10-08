import logging
import os
from urllib.request import urlopen

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from agent.__version__ import __version__
from core.knowledge_manager import get_document_count
from embedding import get_embedding_model_status
from services.agent_runtime.checkpointing import get_checkpoint_backend_status
from services.agent_runtime.factory import is_agent_available

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])
_PRODUCTION_ENVIRONMENTS = {"production", "prod"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _check_database() -> str:
    try:
        from storage.database import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return "ok"
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return "unavailable"


def _check_redis() -> str:
    if os.getenv("REDIS_ENABLED", "true").strip().lower() not in _TRUE_VALUES:
        return "disabled"

    client = None
    try:
        import redis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(
            redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        return "ok"
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return "unavailable"
    finally:
        if client is not None:
            client.close()


def _check_chroma() -> str:
    """Probe the configured Chroma HTTP service without loading embeddings."""

    host = os.getenv("CHROMA_HOST", "").strip()
    if not host:
        # An empty host selects the local persistent client. Opening that store
        # from a readiness probe would create files, so report it explicitly.
        return "unknown"

    try:
        port = int(os.getenv("CHROMA_PORT", "8000"))
        ssl_enabled = os.getenv("CHROMA_SSL", "false").strip().lower() in _TRUE_VALUES
        scheme = "https" if ssl_enabled else "http"
        heartbeat_url = f"{scheme}://{host}:{port}/api/v2/heartbeat"
        with urlopen(heartbeat_url, timeout=2) as response:  # noqa: S310 - configured service
            return "ok" if response.status == 200 else "unavailable"
    except Exception as exc:
        logger.warning("Chroma health check failed: %s", exc)
        return "unavailable"


def _check_runtime() -> str:
    """Check graph availability without running an agent or provider call."""

    try:
        return "ok" if is_agent_available() else "unavailable"
    except Exception as exc:
        logger.warning("Agent runtime health check failed: %s", exc)
        return "unavailable"


def _check_embedding_model() -> str:
    """Report the public lazy lifecycle state without loading the model."""

    try:
        status = get_embedding_model_status()
        state = status.get("state", "unknown")
        return state if state in {"loaded", "not_loaded", "error"} else "unknown"
    except Exception as exc:
        logger.warning("Embedding model status check failed: %s", exc)
        return "unknown"


def _overall_status(
    *,
    database: str,
    redis: str,
    chroma: str,
    runtime: str,
    embedding_model: str,
    checkpointing: dict[str, object] | None = None,
) -> str:
    if database != "ok" or runtime != "ok" or embedding_model == "error":
        return "degraded"
    if redis == "unavailable" or chroma == "unavailable":
        return "degraded"
    if checkpointing and checkpointing.get("status") == "fallback":
        return "degraded"

    environment = os.getenv("APP_ENV", "development").strip().lower()
    if environment in _PRODUCTION_ENVIRONMENTS and (
        redis != "ok" or chroma != "ok" or embedding_model == "unknown"
    ):
        return "degraded"
    return "ok"


def _health_payload() -> dict[str, object]:
    """Build the dependency-aware health payload shared by all probes."""

    db_status = _check_database()
    redis_status = _check_redis()
    chroma_status = _check_chroma()
    runtime_status = _check_runtime()
    embedding_status = _check_embedding_model()
    checkpointing_status = get_checkpoint_backend_status()

    try:
        doc_count = get_document_count()
    except Exception:
        doc_count = 0

    overall = _overall_status(
        database=db_status,
        redis=redis_status,
        chroma=chroma_status,
        runtime=runtime_status,
        embedding_model=embedding_status,
        checkpointing=checkpointing_status,
    )

    return {
        "status": overall,
        "service": "Financial Research Copilot",
        "version": __version__,
        "api": "ok",
        "runtime": runtime_status,
        "database": db_status,
        "redis": redis_status,
        "chroma": chroma_status,
        "embedding_model": embedding_status,
        "checkpointing": checkpointing_status,
        "documents": doc_count,
    }


@router.get("/health")
def health() -> dict[str, object]:
    """Return diagnostic health details without changing legacy HTTP semantics."""

    return _health_payload()


@router.get("/ready")
def readiness() -> JSONResponse:
    """Return 503 unless every production-critical dependency is ready."""

    payload = _health_payload()
    status_code = 200 if payload["status"] == "ok" else 503
    return JSONResponse(content=payload, status_code=status_code)
