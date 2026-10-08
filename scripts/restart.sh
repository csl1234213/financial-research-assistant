#!/usr/bin/env bash
# ============================================================
# restart.sh — Stop and restart all containers
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="${1:-prod}"

cd "$PROJECT_ROOT"

echo "Restarting containers..."
"$SCRIPT_DIR/stop.sh" "$MODE"
"$SCRIPT_DIR/start.sh" "$MODE"