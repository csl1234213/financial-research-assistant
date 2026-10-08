#!/usr/bin/env bash
# Follow logs for the canonical V8.2.0 Docker Compose stack.
#
# Usage:
#   ./scripts/logs.sh
#   ./scripts/logs.sh backend|frontend|agent-worker
# Legacy aliases api, ui, and worker are accepted for convenience.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE="${1:-}"

case "$SERVICE" in
    api) SERVICE="backend" ;;
    ui) SERVICE="frontend" ;;
    worker) SERVICE="agent-worker" ;;
esac

cd "$PROJECT_ROOT"
if [ -n "$SERVICE" ]; then
    docker compose logs -f "$SERVICE"
else
    docker compose logs -f
fi
