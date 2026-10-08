#!/usr/bin/env bash
# Show status for the canonical V8.2.0 Docker Compose stack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
echo "Container status"
docker compose ps
echo
echo "Recent logs"
docker compose logs --tail=20
