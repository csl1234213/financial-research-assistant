# V8.2.0 Operations Runbook

This runbook is for the supported V8.2.0 React + FastAPI deployment. Its
canonical definition is the repository-root
[`docker-compose.yml`](../docker-compose.yml).

## Start the Docker stack

1. Create a local environment file from the tracked template.

   ```bash
   cp .env.example .env
   ```

   On PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` before starting. At minimum, use non-placeholder
   `AUTH_SECRET_KEY`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`, then provide
   the configured LLM provider credential. Root Compose derives the internal
   API/worker `DATABASE_URL` and `REDIS_URL` from the PostgreSQL and Redis
   variables, so the local `DATABASE_URL=sqlite...` example remains useful for
   Python-only development outside Docker.

   Leave `CHROMA_HOST` blank for a Python-only local persistent client. Root
   Compose overrides it with `chromadb`, so the API and worker use the same
   network Chroma service.

   Keep `.env` out of source control. Production credentials belong in the
   deployment platform's secret manager or equivalent secure configuration.

3. Build and start every service.

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

4. Verify the API and open the UI.

   ```bash
   curl http://localhost:8000/api/v1/health
   ```

   - Copilot: `http://localhost:3000`
   - API: `http://localhost:8000`
   - Swagger: `http://localhost:8000/docs`

Expected Compose services are `frontend`, `backend`, `agent-worker`,
`postgres`, `redis`, and `chromadb`. The worker does not expose a host port.
`backend` and `agent-worker` intentionally reuse one immutable Python runtime
image; only their command and runtime environment differ.

## React/Vite development

Run dependencies and the Vite server from `frontend/` while the backend stack
is available on port 8000:

```bash
cd frontend
cp .env.example .env
# Keep VITE_API_BASE_URL=/api; Vite proxies it to http://localhost:8000.
npm ci
npm run dev
```

Vite serves the UI at `http://localhost:5173`. Because Vite does not provide a
proxy in this project, `frontend/.env` must use the absolute API base URL
`http://localhost:8000` for local development. The FastAPI CORS configuration
allows `http://localhost:5173` in development. Do not use `/api` for the Vite
workflow; `/api` is the Docker production value resolved by the Nginx frontend.

## Health and troubleshooting

```bash
# Service state and recent logs
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 agent-worker
docker compose logs --tail=100 frontend

# Dependency checks
curl http://localhost:8000/api/v1/health
curl http://localhost:8001/api/v2/heartbeat
```

- If the UI loads but API calls fail in Docker, inspect `frontend` and `backend`
  logs; the Nginx proxy targets the Compose service name `backend`.
- If an uploaded document remains `processing` or `pending`, inspect
  `agent-worker` logs and confirm Redis, PostgreSQL, and ChromaDB are healthy.
- `POST /api/v1/refresh` is an operator action and requires an authenticated
  `admin` or `owner` account.
- If the Vite browser reports CORS failures, confirm `CORS_ORIGINS` includes
  exactly `http://localhost:5173` and that `VITE_API_BASE_URL=/api`. Endpoint
  modules append `/v1/...`; do not put `/api/v1` in the base URL.
- Do not expose PostgreSQL, Redis, or ChromaDB ports publicly without network
  controls appropriate to the deployment environment.

## Stop and data lifecycle

```bash
# Stop the stack while preserving named volumes.
docker compose down
```

Named volumes preserve PostgreSQL, Redis, ChromaDB, uploads, logs, and agent
memory. `docker compose down -v` deletes those volumes and is a destructive
operation; use it only when intentionally resetting local data.

## Backup and disaster recovery

Use the checksum-gated PostgreSQL and offline Chroma named-volume procedures in
[`BACKUP_RECOVERY.md`](BACKUP_RECOVERY.md). That runbook defines the recovery
objectives, coordinated backup order, explicit restore confirmations,
non-mutating preflights, and quarterly drill evidence. A successful backup
command alone is not proof that a recovery set is restorable.

## Production checklist

- Use `APP_ENV=production`.
- Set unique secrets outside Git (`AUTH_SECRET_KEY`, provider API credentials,
  PostgreSQL password).
- Configure explicit public origins through `CORS_ORIGINS`.
- Back up PostgreSQL and the ChromaDB persistent volume before upgrades.
- Monitor `backend` health, `agent-worker` logs, Redis availability, and queue
  age/pending tasks.
- Keep the root `docker-compose.yml` as the single supported V8.2.0 stack;
  do not combine it with the historical files under `deploy/`.
