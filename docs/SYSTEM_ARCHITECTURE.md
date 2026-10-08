# V4.3 System Architecture (Runtime)

> **Historical architecture record.** This V4.3 document intentionally retains
> the Streamlit-era design for release history. It is not the V8.2.0 deployment
> guide. Use [ARCHITECTURE.md](ARCHITECTURE.md) and
> [DEPLOYMENT_ARCHITECTURE.md](DEPLOYMENT_ARCHITECTURE.md) for the current
> React + FastAPI + PostgreSQL + Redis + ChromaDB + `agent-worker` topology.

## 1. Runtime Call Chain

```
                         Browser
                            │
                            │ HTTPS (Phase 3)
                            ▼
                         Nginx (:80/:443)
                            │
                  ┌─────────┴─────────┐
                  │                   │
                  ▼                   ▼
         Streamlit (:8501)      Static Files
         financial-ui
                  │
                  │ HTTP REST
                  ▼
         FastAPI (:8000)
         financial-api
                  │
                  │
    ┌─────────────┴─────────────┐
    │   ChatService             │
    │   POST /api/v1/chat       │
    └─────────────┬─────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │       AgentRuntime          │
    │  (orchestrates the pipeline)│
    └─────────────┬───────────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   QueryPlanner  IntentAnalyzer  ResearchMode
        │
        │ ExecutionPlan
        ▼
    ┌─────────────────────────────┐
    │     ExecutionEngine         │
    │  execute_single_company()   │
    │  execute_compare()          │
    │  execute_global()           │
    └─────────────┬───────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │     HybridRetriever         │
    │  semantic + keyword search  │
    └─────────────┬───────────────┘
                  │
                  │ RetrievalContext
                  ▼
    ┌─────────────────────────────┐
    │     EmbeddingStore          │
    │  (abstract interface)       │
    └─────────────┬───────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │     ChromaEmbeddingStore     │
    │  PersistentClient           │
    └─────────────┬───────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │     ChromaDB                │
    │  /app/chroma_db/            │
    └─────────────────────────────┘
                  │
                  │ results
                  ▼
    ┌─────────────────────────────┐
    │     ReasoningEngine         │
    │  evidence generation        │
    │  call_llm() → DeepSeek      │
    └─────────────┬───────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │     ReportBuilder           │
    │  facts / risks / citations  │
    └─────────────┬───────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │     RuntimeResult           │
    │  report + citations         │
    └─────────────┬───────────────┘
                  │
                  ▼
         JSON Response
         {"report": "...", "citations": [...]}
```

---

## 2. Module Responsibility Table

| Module | Layer | Responsibility |
|--------|-------|---------------|
| `api/routers/` | Transport | HTTP endpoints, validation, error handling |
| `api/services/chat_service.py` | Service | Orchestrates request → runtime |
| `agent/agent_runtime.py` | Agent | Creates runtime context, delegates to execution engine |
| `agent/query_planner.py` | Agent | Parses question → ExecutionPlan |
| `agent/execution_engine.py` | Agent | Executes plan steps (single/compare/global) |
| `agent/reasoning_engine.py` | Agent | Generates evidence per step, calls LLM |
| `core/intent_analyzer.py` | Core | SINGLE / COMPARE / GLOBAL / UNKNOWN |
| `core/report_builder.py` | Core | Builds structured research report |
| `core/citation_formatter.py` | Core | Formats citations from evidence |
| `retrieval/hybrid_retriever.py` | Retrieval | Semantic + keyword search |
| `retrieval/retrieval_context.py` | Retrieval | DTO: company, filters, k |
| `storage/embedding_store.py` | Storage | Abstract interface |
| `storage/chroma_store.py` | Storage | ChromaDB implementation |
| `llm/provider.py` | LLM | DeepSeek API client |
| `prompt_builder.py` | Prompt | Constructs LLM prompts |
| `embedding.py` | Embedding | SentenceTransformer wrapper |

---

## 3. Data Flow

```
          ┌──────────────────────────────────────────┐
          │              REQUEST (HTTP)               │
          │  {"question": "What is Apple's revenue?"} │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              ChatRequest                  │
          │  question: str, company: Optional[str]    │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              IntentAnalyzer               │
          │  "Apple" → SINGLE                         │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              QueryPlanner                 │
          │  ExecutionPlan(steps=[RETRIEVE, REASON])  │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              ExecutionEngine              │
          │  execute_single_company("Apple")          │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              RetrievalContext             │
          │  company="Apple", filters=[...], k=4      │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              HybridRetriever              │
          │  query → embedding → ChromaDB → results   │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │           List[SearchResult]              │
          │  [{chunk_id, text, score, metadata}, ...] │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              ReasoningEngine              │
          │  evidence = analyze(context, results)     │
          │  prompt = build_prompt(q, evidence)       │
          │  answer = call_llm(prompt)                │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              ReportBuilder                │
          │  facts, risks, opportunities, conclusion  │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              RuntimeResult                │
          │  report: str, citations: List[Citation]   │
          └──────────────────┬───────────────────────┘
                             │
                             ▼
          ┌──────────────────────────────────────────┐
          │              JSON RESPONSE                │
          │  {"report": "...", "citations": [...]}    │
          └──────────────────────────────────────────┘
```

---

## 4. Key Design Decisions

### 4.1 EmbeddingStore Abstraction

```
HybridRetriever
       │
       │ depends on (interface)
       ▼
EmbeddingStore (ABC)
       ▲
       │ implements
       │
ChromaEmbeddingStore
```

The retriever never knows it's talking to ChromaDB. Swap to Qdrant / Pinecone / Weaviate without changing retrieval logic.

### 4.2 RetrievalContext as DTO

```python
@dataclass
class RetrievalContext:
    company: Optional[str]
    filters: List[str]
    top_k: int
```

This is a plain data object — no behavior, no dependencies. The retriever receives it and knows exactly what to search for.

### 4.3 ExecutionPlan as Pipeline

```python
ExecutionPlan(
    steps=[
        Step(type=RETRIEVE, target="Apple"),
        Step(type=REASON, target="Apple"),
        Step(type=BUILD_REPORT)
    ]
)
```

The planner decides WHAT to do. The execution engine decides HOW. This separation makes it easy to add new step types.

### 4.4 RuntimeResult as Final Output

```python
@dataclass
class RuntimeResult:
    report: str
    citations: List[Citation]
    execution_time: float
    plan: ExecutionPlan
```

The API layer only sees this. It never touches ChromaDB, embeddings, or chunks.

---

## 5. Async / Concurrency Model

```
Phase 1-2 (current):    Synchronous
Phase 4 (Redis):        Async task queue for long-running queries
Phase 5 (Cloud):        Async FastAPI + connection pooling
```

---

## 6. Related Documents

- [DEPLOYMENT_ARCHITECTURE.md](./DEPLOYMENT_ARCHITECTURE.md) — container, network, volume, env design
- [ARCHITECTURE.md](../ARCHITECTURE.md) — original V4 architecture proposal
- [CHANGELOG.md](../CHANGELOG.md) — version history
