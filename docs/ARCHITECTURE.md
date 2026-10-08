# Financial Agent Runtime Assistant V8.2.0 Architecture

This document describes the supported V8.2.0 runtime. The canonical container
topology is defined by the repository-root
[`docker-compose.yml`](../docker-compose.yml). For operational commands, see
[OPERATIONS.md](OPERATIONS.md).

## System overview

```text
Browser
  |
  | Docker: http://localhost:3000
  v
frontend (React build served by Nginx)
  | /api/* reverse proxy
  v
backend (FastAPI, :8000)
  |-- authentication and tenant context
  |-- chat API -> source-controlled LangGraph
  |      -> plan (intent) -> execute (Agent Runtime) -> finalize
  |      -> governed RetrievalTool -> hybrid retrieval
  |      -> ChromaDB -> LLM provider -> cited response
  |
  |-- PostgreSQL (:5432): users, tenants, documents, tasks, sessions
  |-- Redis (:6379): cache, sessions, task queue / worker coordination
  |-- ChromaDB (:8001 host / :8000 service): vector collections
  |
  `-- agent-worker (no public port)
          -> claim durable task -> extract PDF -> chunk -> embed -> ChromaDB
```

The Docker services use the `financial_network` bridge network and named
volumes so persistent data survives container replacement. `frontend` is the
React/Nginx service, `backend` is the FastAPI service, and `agent-worker` is the
asynchronous document-processing service.

## Request paths

### Chat

```text
React Copilot -> POST /api/v1/chat -> FastAPI service layer
              -> authenticated tenant context
              -> Agent Runtime / execution graph
              -> intent + plan + strategy selection
              -> tenant-scoped hybrid retrieval when needed
              -> selected LLM provider
              -> report, reasoning, execution metadata, workflow, citations
```

Direct questions use the direct-LLM strategy. Research questions use the RAG
strategy; retrieval receives the authenticated tenant scope and may include the
public demo knowledge base where the policy allows it. The frontend is a client
of the API only: it does not access PostgreSQL, Redis, or ChromaDB directly.

The Graph and domain runtime are intentionally separate. LangGraph owns
request-state orchestration; the existing Agent Runtime owns financial
planning, retrieval, provider routing, and response contracts. This avoids two
divergent RAG implementations while keeping graph nodes observable and
replaceable.

### Document ingestion

```text
Authenticated upload -> Document + durable Task in PostgreSQL
                       -> Redis publication
                       -> agent-worker claims the task
                       -> PDF extraction / chunking / embedding
                       -> tenant-scoped ChromaDB records
                       -> task and document status update
```

This separation keeps upload requests short and makes work retryable. The
worker must run alongside the API for uploaded documents to become searchable.
The API and worker share the upload volume and both connect to the same Chroma
HTTP service; they do not concurrently open a local Chroma persistence file.

## AI engineering extension points

Provider, prompt, retriever, tool, MCP, evaluation, and LoRA extension
contracts are documented in
[AI_ENGINEERING_GUIDE.md](AI_ENGINEERING_GUIDE.md). The online runtime does not
install optional training dependencies or perform fine-tuning.

## Service contract

| Compose service | Runtime responsibility | Host exposure |
| --- | --- | --- |
| `frontend` | React static application, Nginx SPA fallback, `/api` proxy | `3000` |
| `backend` | FastAPI, auth, Agent Runtime, API endpoints | `8000` |
| `agent-worker` | Async document ingestion and task processing | none |
| `postgres` | Relational application data and tenant-owned records | `5432` |
| `redis` | Cache, session/task coordination | `6379` |
| `chromadb` | Persistent vector database | `8001` |

The browser-facing production path is `frontend:3000 -> /api -> backend:8000`.
In local frontend development, Vite serves the React app on `:5173` and calls
the API at `http://localhost:8000`; the API CORS allowlist must include that
origin.

## Application boundaries

| Boundary | Primary modules | Responsibility |
| --- | --- | --- |
| API | `api/` | Request validation, authentication, response contracts, service composition |
| Agent Runtime | `agent/`, `services/agent_runtime/` | Intent, planning, graph/strategy execution, runtime state |
| Retrieval | `retrieval/`, `storage/` | Query scope, vector access, evidence normalization |
| LLM | `llm/`, `prompt_builder.py`, `prompts/` | Provider selection, prompt construction, model calls |
| Persistence | `storage/`, `cache/`, `tasks/` | PostgreSQL state, Redis-backed coordination, vector storage, task lifecycle |
| Web client | `frontend/` | Copilot UI and typed HTTP API client |

## Operational guarantees and ownership

- **Tenant isolation:** API authentication supplies a tenant context; relational
  queries, uploaded file paths, task records, checkpoints, and vector metadata
  are scoped by that context.
- **Durability:** PostgreSQL is the source of truth for application records and
  task state. Redis is coordination/queue infrastructure, not the only record
  of a document-processing request.
- **RAG traceability:** Research responses include evidence/citation metadata so
  the UI and callers can present source provenance.
- **Boundary-safe tools:** Tool execution is governed by server-side
  authorization and receives trusted context rather than browser-provided
  tenant identifiers.

## Supported deployment boundary

Use the root `docker-compose.yml` for V8.2.0. The `deploy/` Compose variants,
`docker/Dockerfile.ui`, and Streamlit-oriented material describe an earlier
deployment line and are kept only as historical artifacts. Do not combine those
files with the root Compose stack. Historical product milestones remain in
[`docs/releases/`](releases/).
