#!/bin/bash
# ============================================================
# Financial RAG Assistant — Backend Entrypoint
# ============================================================
set -e

echo "============================================"
echo " Financial RAG Assistant — Backend API"
echo "============================================"
echo " APP_ENV:  ${APP_ENV:-production}"
echo " API_HOST: ${API_HOST:-0.0.0.0}"
echo " API_PORT: ${API_PORT:-8000}"
echo " LLM_PROVIDER: ${LLM_PROVIDER:-deepseek}"
echo " CHROMA_PATH: ${CHROMA_PATH:-chroma_db}"
echo "============================================"

require_production_secret() {
    local name="$1"
    local value="$2"
    case "$value" in
        ""|change-me|change-me-before-production|your-secret-key|your-deepseek-api-key)
            echo "ERROR: $name must be set to a non-placeholder value when APP_ENV=production." >&2
            exit 1
            ;;
    esac
}

if [ "${APP_ENV:-development}" = "production" ] || [ "${APP_ENV:-development}" = "prod" ]; then
    require_production_secret "AUTH_SECRET_KEY" "${AUTH_SECRET_KEY:-${SECRET_KEY:-}}"
    require_production_secret "POSTGRES_PASSWORD" "${POSTGRES_PASSWORD:-}"
    require_production_secret "REDIS_PASSWORD" "${REDIS_PASSWORD:-}"
fi

# Ensure data directories exist
mkdir -p "${CHROMA_PATH:-chroma_db}"
mkdir -p "${UPLOAD_DIR:-storage/uploads}"
mkdir -p "${PDF_DIR:-storage/pdfs}"

# The API container owns schema bootstrap.  Workers wait for its health check
# in Compose and set RUN_DATABASE_MIGRATIONS=false to avoid concurrent Alembic
# upgrades against the same PostgreSQL database.
if [ "${RUN_DATABASE_MIGRATIONS:-true}" = "true" ]; then
    echo " Applying database migrations..."
    alembic upgrade head
    echo " Seeding idempotent application reference data..."
    python -c "from storage.database import seed_defaults; seed_defaults()"

    if [ "${BOOTSTRAP_DEMO_KNOWLEDGE:-true}" = "true" ]; then
        echo " Bootstrapping public demo knowledge..."
        python docker/bootstrap_knowledge.py
    fi
fi

# Honor a Docker Compose command (for example the agent worker) after the
# shared directory setup above.  With no command, this image remains the API.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Start Uvicorn
exec uvicorn api.main:app \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --log-level "${LOG_LEVEL:-info}" \
    --no-access-log
