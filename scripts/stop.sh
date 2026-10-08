#!/usr/bin/env bash
# Stop the canonical V8.2.0 Docker Compose stack while preserving volumes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
docker compose down
echo "Containers stopped; named volumes were preserved."
