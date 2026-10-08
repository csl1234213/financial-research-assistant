# Demo Script — Financial Agent Runtime Assistant v8.2.0

> This script uses the supported V8.2.0 root `docker-compose.yml` stack. For
> the operational runbook and the Vite development workflow, see
> [../OPERATIONS.md](../OPERATIONS.md).

## Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose)
- A local `.env` copied from `.env.example`, with a valid provider credential,
  `AUTH_SECRET_KEY`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`

---

## 1. Docker Quick Start

```bash
git clone https://github.com/csl1234213/financial-rag-assistant.git
cd financial-rag-assistant

# Create and configure local runtime settings first.
cp .env.example .env

# Build and start the V8.2.0 React + FastAPI stack.
docker compose up -d --build
```

**Expected output:**

```
=== Financial Agent Runtime Assistant v8.2.0 ===
[Entrypoint] Running knowledge bootstrap...
[Bootstrap] Knowledge base empty — initializing demo data...
Loading embedding model...
Embedding model loaded!
Loaded Documents: 3 unique sources (Tesla, NVIDIA, Apple)
Total Chunks: 303
[Bootstrap] Done — 3 public document sources are available.
[Entrypoint] Starting API server...
```

**Verify idempotency (restart):**

```bash
docker compose restart backend
docker compose logs --tail 5 backend
```

**Expected output:**

```
[Bootstrap] Knowledge base already populated — skipping init.
```

---

## 2. Health Check

```bash
curl http://localhost:8000/api/v1/health | python -m json.tool
```

**Expected response:**

```json
{
    "status": "ok",
    "service": "Financial Research Copilot",
    "version": "8.2.0",
    "api": "ok",
    "runtime": "ok",
    "embedding_model": "loaded",
    "documents": 0
}
```

---

## 3. Knowledge Base Statistics

```bash
curl http://localhost:8000/api/v1/knowledge/statistics | python -m json.tool
```

**Expected response:**

```json
{
    "total_documents": 3,
    "total_chunks": 303,
    "documents": [
        {"name": "Tesla_Q2_2025.pdf", "chunks": 85},
        {"name": "NVIDIA_Q1_FY2027.pdf", "chunks": 43},
        {"name": "Apple_Q2_2026.pdf", "chunks": 175}
    ]
}
```

---

## 4. Direct Chat Demo

**Non-research query — routed to direct LLM conversation:**

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is AI?", "stream": false}' \
  | python -m json.tool
```

**Expected response structure:**

```json
{
    "workflow": {
        "type": "direct_chat"
    },
    "reasoning": {
        "intent": "DIRECT_CHAT",
        "companies": null,
        "evidence_count": 0
    },
    "execution": {
        "strategy": "direct_llm",
        "use_retrieval": false
    },
    "routing": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash"
    },
    "report": "Artificial Intelligence (AI) is...",
    "citations": [],
    "execution_time": 1.234
}
```

**Key observations:**
- `workflow.type` = `"direct_chat"` — no retrieval pipeline triggered
- `reasoning.intent` = `"DIRECT_CHAT"` — Intent Router correctly classified
- `use_retrieval` = `false` — no ChromaDB query executed
- `citations` = `[]` — no evidence needed

---

## 5. Financial RAG Research — Tesla

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Analyze Tesla revenue growth", "stream": false}' \
  | python -m json.tool
```

**Expected response structure:**

```json
{
    "workflow": {
        "type": "rag"
    },
    "reasoning": {
        "intent": "SINGLE_COMPANY",
        "companies": ["Tesla"],
        "evidence_count": 4
    },
    "execution": {
        "strategy": "rag",
        "use_retrieval": true
    },
    "citations": [
        {
            "source": "Tesla_Q2_2025.pdf",
            "similarity": 0.97,
            "preview": "Total revenues 94,827 -3%..."
        },
        {
            "source": "Tesla_Q2_2025.pdf",
            "similarity": 0.92,
            "preview": "Automotive revenues 69,526 -10%..."
        },
        {
            "source": "Tesla_Q2_2025.pdf",
            "similarity": 0.90,
            "preview": "Energy generation and storage revenue..."
        },
        {
            "source": "Tesla_Q2_2025.pdf",
            "similarity": 0.86,
            "preview": "results of operations..."
        }
    ],
    "report": "# Research Report\n\n## Question\nAnalyze Tesla revenue growth\n\n## Answer\n...",
    "execution_time": 3.277
}
```

**Key observations:**
- `workflow.type` = `"rag"` — RAG pipeline triggered
- `reasoning.intent` = `"SINGLE_COMPANY"` — Intent Router classified correctly
- `evidence_count` = `4` — 4 relevant chunks retrieved
- All citations from `Tesla_Q2_2025.pdf` — correct source routing
- `report` contains structured Markdown with `## Answer`, `## Key Findings`, `## Risks`

---

## 6. Financial RAG Research — NVIDIA

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is NVIDIA revenue?", "stream": false}' \
  | python -m json.tool
```

**Expected response structure:**

```json
{
    "workflow": {
        "type": "rag"
    },
    "reasoning": {
        "intent": "SINGLE_COMPANY",
        "companies": ["NVIDIA"],
        "evidence_count": 4
    },
    "execution": {
        "strategy": "rag",
        "use_retrieval": true
    },
    "citations": [
        {"source": "NVIDIA_Q1_FY2027.pdf", "similarity": 0.98},
        {"source": "NVIDIA_Q1_FY2027.pdf", "similarity": 0.94}
    ],
    "report": "# Research Report\n\n## Question\nWhat is NVIDIA revenue?\n\n## Answer\n...",
    "execution_time": 2.31
}
```

**Key observations:**
- `intent` = `"SINGLE_COMPANY"` — NVIDIA auto-detected
- A single canonical NVIDIA report supplies page-level citations without duplicate files
- `NVIDIA_Q1_FY2027.pdf` — record revenue $81.6B, +85% YoY

---

## 7. Financial RAG Research — Apple

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Analyze Apple financial performance", "stream": false}' \
  | python -m json.tool
```

**Expected response structure:**

```json
{
    "workflow": {
        "type": "rag"
    },
    "reasoning": {
        "intent": "SINGLE_COMPANY",
        "companies": ["Apple"],
        "evidence_count": 2
    },
    "execution": {
        "strategy": "rag",
        "use_retrieval": true
    },
    "citations": [
        {"source": "Apple_Q2_2026.pdf", "similarity": 0.96},
        {"source": "Apple_Q2_2026.pdf", "similarity": 0.93}
    ],
    "report": "# Research Report\n\n## Question\nAnalyze Apple financial performance\n\n## Answer\n...",
    "execution_time": 3.41
}
```

**Key observations:**
- 6 chunks from `Apple_Q2_2026.pdf` across full source coverage
- Net sales: $111,184M, Products: $80,208M, Services: $30,976M
- R&D: $11,419M (+34% YoY)

---

## 8. Swagger API

Open browser: **http://localhost:8000/docs**

Available endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/chat` | POST | Financial research chat |
| `/api/v1/knowledge` | GET | Knowledge base overview |
| `/api/v1/knowledge/statistics` | GET | Document & chunk statistics |
| `/api/v1/upload` | POST | Upload PDF and enqueue asynchronous indexing |
| `/api/v1/refresh` | POST | Rebuild knowledge base |
| `/api/v1/health` | GET | System health check |

---

## 9. React Copilot UI

Open browser: **http://localhost:3000**

Try the same queries in the UI:
- "What is AI?" → Direct Chat
- "Analyze Tesla revenue growth" → RAG Research
- "What is NVIDIA revenue?" → RAG Research
- "Analyze Apple financial performance" → RAG Research

---

## 10. Cleanup

```bash
# Stop containers (preserves ChromaDB data)
docker compose down

# Full cleanup (removes volumes)
docker compose down -v
```

---

## Demo Flow Summary

```
docker compose up -d --build
  │
  ├── Bootstrap: 3 unique PDFs → 303 quality-gated chunks
  │
  ├── Health Check: version 8.2.0, model loaded
  │
  ├── Direct Chat: "What is AI?"
  │     ├── Intent: DIRECT_CHAT
  │     └── Strategy: direct_llm
  │
  ├── Tesla RAG: "Analyze Tesla revenue growth"
  │     ├── Intent: SINGLE_COMPANY
  │     ├── Source: Tesla_Q2_2025.pdf
  │     └── Evidence: 4 citations
  │
  ├── NVIDIA RAG: "What is NVIDIA revenue?"
  │     ├── Intent: SINGLE_COMPANY
  │     ├── Sources: 3 NVIDIA PDFs
  │     └── Evidence: 4 citations
  │
  ├── Apple RAG: "Analyze Apple financial performance"
  │     ├── Intent: SINGLE_COMPANY
  │     ├── Source: Apple_Q2_2026.pdf
  │     └── Evidence: 2 citations
  │
  └── Swagger UI: http://localhost:8000/docs
```

---

## Restart Verification (Idempotency)

```bash
docker compose restart backend
docker compose logs --tail 3 backend
```

**Expected output:**

```
[Bootstrap] Knowledge base already populated — skipping init.
[Entrypoint] Starting API server...
```

> Knowledge base is persisted in named Docker volumes.  
> Subsequent `docker compose up` skips re-initialization.
