#!/usr/bin/env bash
# Start the canonical V8.2.0 Docker Compose stack.
#
# Usage:
#   ./scripts/start.sh       # React/Nginx UI on :3000
#   ./scripts/start.sh dev   # backend dependencies + API/worker; run Vite separately on :5173
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"
MODE="${1:-prod}"
API_URL="http://localhost:8000"
MAX_RETRIES=30
RETRY_INTERVAL=2

if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from .env.example."
    echo "Before a production deployment, set AUTH_SECRET_KEY, POSTGRES_PASSWORD,"
    echo "REDIS_PASSWORD, DEEPSEEK_API_KEY, and production CORS_ORIGINS."
fi

cd "$PROJECT_ROOT"

case "$MODE" in
    prod|stack)
        UI_URL="http://localhost:3000"
        echo "Starting the complete V8.2.0 Compose stack..."
        docker compose up -d --build
        ;;
    dev)
        UI_URL="http://localhost:5173"
        echo "Starting API, worker, and stateful services for Vite development..."
        docker compose up -d --build backend agent-worker
        echo "Run 'cd frontend && npm run dev' in another terminal for the React dev server."
        ;;
    *)
        echo "Usage: $0 [prod|stack|dev]" >&2
        exit 2
        ;;
esac

echo "Waiting for API health..."
for i in $(seq 1 "$MAX_RETRIES"); do
    if curl -fsS "$API_URL/api/v1/health" >/dev/null 2>&1; then
        echo "Financial Research Copilot is ready."
        echo "  API:     $API_URL"
        echo "  Swagger: $API_URL/docs"
        echo "  UI:      $UI_URL"
        echo "  Logs:    ./scripts/logs.sh"
        exit 0
    fi
    printf "  [%2d/%2d] Waiting...\r" "$i" "$MAX_RETRIES"
    sleep "$RETRY_INTERVAL"
done

echo "API did not become healthy within $((MAX_RETRIES * RETRY_INTERVAL))s." >&2
echo "Inspect logs with: docker compose logs backend" >&2
exit 1
