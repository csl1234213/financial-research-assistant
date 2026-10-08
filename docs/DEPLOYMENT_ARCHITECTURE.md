# V8.2.0 Deployment Architecture

## Canonical V8.2.0 topology

The supported deployment definition is the repository-root
[`docker-compose.yml`](../docker-compose.yml). It is the only Compose file that
this V8.2.0 documentation treats as the standard startup path.

```text
Browser
  |
  +--> frontend / financial-frontend
  |       React build + Nginx, host :3000
  |       /api/* -> backend:8000
  |
  +--> backend / financial-backend
          FastAPI, host :8000
          |
          +--> postgres / financial-postgres, host :5432
          +--> redis / financial-redis, host :6379
          +--> chromadb / financial-chromadb, host :8001
          `--> agent-worker / financial-agent-worker (internal worker)
```

All services use the `financial_network` bridge network. Data is persisted in
named volumes for PostgreSQL, Redis, ChromaDB, uploads, logs, and agent memory.
The browser should normally use `http://localhost:3000`; FastAPI and Swagger
are also reachable at `http://localhost:8000` and
`http://localhost:8000/docs` for development and operations.

## Service ownership

| Service | Image/build role | Ports | Health/dependency role |
| --- | --- | --- | --- |
| `frontend` | `docker/Dockerfile.frontend`, React build served by Nginx | `3000` | Starts after backend health; proxies `/api` |
| `backend` | `docker/Dockerfile.api`, FastAPI + Agent Runtime | `8000` | Waits for PostgreSQL, Redis, and ChromaDB |
| `agent-worker` | `docker/Dockerfile.api`, `python -m workers.agent_worker` | none | Processes queued ingestion tasks after backend is healthy |
| `postgres` | PostgreSQL 16 | `5432` | Durable relational data |
| `redis` | Redis 7 | `6379` | Cache, sessions, and task coordination |
| `chromadb` | ChromaDB | `8001` | Persistent vector retrieval store |

`agent-worker` is intentionally not browser-facing. If it is down, uploads can
be accepted and remain pending, but their documents will not become searchable.

## Local frontend development

The Docker frontend uses Nginx on `:3000`. The separate developer workflow is:

```text
Vite dev server (:5173) -> http://localhost:8000/api/v1/*
```

Keep `VITE_API_BASE_URL=/api` in `frontend/.env` before running Vite. The Vite
development server and the Docker Nginx image both proxy that prefix to
FastAPI, while endpoint modules own the `/v1/...` portion. If a separate
frontend host must bypass those proxies, configure the full base as
`http://localhost:8000/api` and allow that frontend origin through CORS.

## Configuration boundary

- Copy `.env.example` to `.env`; keep `.env` untracked.
- Set a non-placeholder `AUTH_SECRET_KEY` and the LLM provider credential before
  any environment that will serve real users.
- For the root Compose topology, set `POSTGRES_PASSWORD` and
  `REDIS_PASSWORD`. Compose derives internal URLs that use the service names
  `postgres` and `redis`; do not replace them with host-local URLs.
- In production, explicitly set `APP_ENV=production` and a public
  `CORS_ORIGINS` allowlist. Do not rely on development defaults.

Exact commands, health checks, logs, shutdown guidance, and the Vite workflow
are in [OPERATIONS.md](OPERATIONS.md).

## Historical deployment material

The following files remain in the repository to preserve historical context but
are **not** the V8.2.0 startup path:

- `deploy/docker-compose.base.yml`
- `deploy/docker-compose.dev.yml`
- `deploy/docker-compose.prod.yml`
- `deploy/.env.*`
- `docker/Dockerfile.ui`

They describe an earlier Streamlit-oriented deployment line. Do not merge them
with the root Compose file or use them as the default V8.2.0 runbook. Historical
release material is retained under [`docs/releases/`](releases/).
