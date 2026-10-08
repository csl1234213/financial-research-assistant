#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.linux.yml)

: "${PUBLIC_DOMAIN:?Set PUBLIC_DOMAIN to the HTTPS hostname before deploying}"
: "${ACME_EMAIL:?Set ACME_EMAIL for certificate renewal notifications}"

echo "Validating Compose configuration"
"${COMPOSE[@]}" config -q
echo "Building application images"
"${COMPOSE[@]}" build backend agent-worker frontend
echo "Starting services"
"${COMPOSE[@]}" up -d

for attempt in $(seq 1 30); do
  if "${COMPOSE[@]}" ps --status running --services | grep -qx backend && \
     "${COMPOSE[@]}" ps --status running --services | grep -qx frontend; then
    break
  fi
  sleep 5
done

python scripts/smoke_online.py --base-url "https://${PUBLIC_DOMAIN}"
echo "Deployment completed"
