# Docker Build Guide — V8.2.0

The supported V8.2.0 Docker entry point is the repository-root
[`docker-compose.yml`](../docker-compose.yml). It builds and runs the complete
React + FastAPI stack, including PostgreSQL, Redis, ChromaDB, and
`agent-worker`.

For configuration and operational commands, see
[docs/OPERATIONS.md](../docs/OPERATIONS.md).

## Current images

| Dockerfile | Compose service | Purpose |
| --- | --- | --- |
| `Dockerfile.api` | `backend`, `agent-worker` | One shared image for FastAPI and the asynchronous worker |
| `Dockerfile.frontend` | `frontend` | React build served by Nginx on port 3000 |

## Runtime dependency boundary

`Dockerfile.api` installs `requirements/api.txt`, which contains the complete
API, worker, embedding, and RAG runtime. It deliberately excludes pytest,
Ruff, the historical Streamlit client, and optional LoRA training packages.
CI installs `requirements/dev.txt`; fine-tuning remains an explicit,
isolated install from `requirements/training.txt`.

The inference layer pins PyTorch from the official CPU wheel index. This keeps
the production API/worker image free of CUDA/NVIDIA runtime packages without
removing any embedding or retrieval capability. See
[`requirements/README.md`](../requirements/README.md) for the layer contract.

## Build and run

```bash
cp .env.example .env
# Edit .env: set application/provider secrets plus POSTGRES_PASSWORD and
# REDIS_PASSWORD. Compose derives its internal PostgreSQL and Redis URLs.
docker compose up -d --build
docker compose ps
```

The primary endpoints are:

- Copilot: `http://localhost:3000`
- FastAPI: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

## Historical Docker artifacts

`Dockerfile.ui`, `Dockerfile.dev`, and the Compose files under `deploy/` are
kept as historical Streamlit-era artifacts. They are not the supported V8.2.0
startup path and must not be combined with the root Compose stack.
