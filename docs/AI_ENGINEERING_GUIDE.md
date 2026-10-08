# AI Engineering Capability Guide

This guide maps the project's AI application capabilities to stable extension
points, verification suites, and honest runtime boundaries. It is the starting
point for maintainers adding a model, retriever, prompt, tool, or evaluation
case.

## Capability map

| Capability | Runtime entry point | Contract / extension point | Verification |
| --- | --- | --- | --- |
| LLM application | `llm/provider.py` | Provider registry and provider adapters | provider and routing tests |
| Financial RAG | `core/core_engine.py` | `EmbeddingStore`, `RetrievalContext`, `RetrievalTool` | retrieval, tenant-isolation, integration tests |
| Agent orchestration | `services/agent_runtime/graph.py` | LangGraph state plus plan/execute/finalize nodes | `tests/test_langgraph_agent.py` |
| Tool use | `agent/tools/tool_engine.py` | `BaseTool`, governed retrieval, deterministic financial metrics | `tests/tools/` |
| MCP | `mcp/app.py` | default-deny composition plus lifecycle/stdio transport | Python contract tests plus the isolated official SDK conformance gate |
| Session management | `services/agent_runtime/runtime.py` and `/api/v1/agent/sessions` | tenant/user/thread cache, PostgreSQL messages, lifecycle API and LangGraph checkpoints | agent/storage/session tests |
| Prompt engineering | `prompts/registry.py` | immutable name/version/checksum metadata | prompt registry and builder tests |
| Evaluation | `evaluation/` | versioned golden data, deterministic metrics and model benchmark protocol | `tests/evaluation/` |
| Hugging Face | `embedding.py` and training extras | sentence-transformer embeddings; optional Transformers training stack | retrieval and training-readiness tests |
| LoRA / fine-tuning | `training/` | validated SFT data, explicit PEFT/Transformers or TRL execution, and an eval-loss promotion gate | `tests/training/` |

## Online request path

```text
FastAPI /api/v1/chat
  -> authenticated tenant, user and thread scope
  -> source-controlled LangGraph
       plan: intent analysis
       execute: Agent Runtime / run_rag
         -> ToolEngine
         -> tenant-scoped RetrievalTool
         -> HybridRetriever
         -> Chroma HTTP service (Docker) or persistent client (local)
         -> selected LLM provider
       finalize: stable response contract
  -> cache, session history, checkpoint and trace
  -> report + workflow + execution metadata + citations
```

Tenant identity is server-owned. Browser input cannot inject a retrieval
adapter or override the authenticated tenant. Public demo evidence is merged
only through the explicit `include_public` policy.

## Session lifecycle

Authenticated users can list, read, page-export, and delete only their own
Agent sessions:

- `GET /api/v1/agent/sessions`
- `GET /api/v1/agent/sessions/{thread_id}`
- `GET /api/v1/agent/sessions/{thread_id}/export`
- `DELETE /api/v1/agent/sessions/{thread_id}`

Every repository lookup applies tenant, user, and exact thread scope. A
cross-tenant or cross-user lookup returns the same `404` as a missing session.
Transcripts use deterministic chronological ordering and bounded pagination;
session lists use deterministic newest-first ordering.

Deleting a session removes its messages, archives application checkpoint
records, removes the operational LangGraph checkpoint, and invalidates all
Redis request-summary variants for that exact thread. Redis fallback matching
escapes client-controlled glob characters, so a thread such as `research*`
cannot invalidate a neighboring session.

## Advanced execution strategies

Strategy selection and evidence-producing execution are separate layers. The
strategy engine chooses `rag`, `multi_step`, `parallel`, or `tool_calling`;
the dispatcher then executes the concrete `ExecutionPlan`.

- `multi_step` executes plan nodes in dependency order. Each downstream
  handler receives a request-local snapshot of completed step outputs through
  `_step_results`.
- `parallel` uses a bounded thread pool only for independent `RETRIEVE`
  nodes. Every worker gets an isolated evidence list; results and citations
  are merged in original plan order. Non-retrieval handlers always remain on
  the caller thread.
- `tool_calling` accepts only an explicit `TOOL_CALL` plan node whose
  `tool_name` is `retrieval`. It translates that node to the same
  tenant-scoped retrieval handler used by RAG. Python, SQL, HTTP, OCR, image,
  and custom execution are rejected without invoking a handler.

The current planner does not create an explicit governed tool node for OCR,
image-analysis, or code-generation prompts. Those prompts therefore fail
closed instead of producing a fabricated tool success. Adding one of those
capabilities requires a typed input contract, a server-owned adapter, an
authorization policy, and behavioral tests before changing the allowlist.

`WorkflowResult` describes lifecycle and selected workflow shape. It is not
proof that a tool produced data; evidence, citations, plan-step results, and
`ToolResult` are the authoritative execution records.

The production runtime shares its planner, embedding model, and store across
FastAPI requests. Planning is serialized around its step-ID state, embedding
inference is guarded, store initialization is single-flight, and parallel
workers never share their mutable evidence accumulator. Handler registration
is startup-only.

## Adding an LLM provider

Implement the existing provider interface under `llm/adapters/`, register it
with the provider registry, and add routing tests. Keep SDK imports inside the
adapter so another provider can run without that optional SDK. Credentials
must come from environment or a secret manager and must never be placed in
prompts, traces, datasets, or reports.

## Adding a retriever or vector store

Implement the narrow `EmbeddingStore` or `EvidenceRetriever` protocol rather
than importing a concrete Chroma client into the Agent layer. Production
retrieval flows through `TenantRetrievalToolExecutor`; this preserves argument
validation, tenant scope, citations, and tool observability.

`ChromaEmbeddingStore` selects its client explicitly:

- non-empty `CHROMA_HOST`: `chromadb.HttpClient`;
- no `CHROMA_HOST`: local `chromadb.PersistentClient`;
- Docker Compose always supplies `CHROMA_HOST=chromadb`.

The API and worker therefore use the same Chroma service. Do not mount and open
the same local Chroma/SQLite directory from multiple containers.

## Adding a tool

1. Implement `BaseTool` and return a truthful `ToolResult`.
2. Register it through an idempotent bootstrap function.
3. Define a JSON Schema before exposing it through MCP.
4. Add the tool to an explicit allowlist.
5. Use an authorization hook for tenant/user/approval policy.

Disabled or unavailable tools must return `SKIPPED` or `FAILED`; they must not
return fabricated successful output.

The built-in `financial_metrics` tool is a side-effect-free reference
implementation for growth rate, margin, ratio and CAGR. It uses explicit
numeric inputs and is safe to expose through the governed MCP allowlist.
The production planner emits a typed `TOOL_CALL` only for its small,
unambiguous grammar. The runtime dispatcher is the sole execution owner,
records a structured tool trace, returns no retrieval citations, and does not
call an LLM for a successful deterministic calculation.
Python, SQL and outbound HTTP execution remain disabled until separately
reviewed sandboxes or adapters exist.

## MCP boundary

`mcp/server.py` provides the 2025-06-18 initialize/initialized lifecycle, ping,
newline-delimited stdio JSON-RPC transport, and governed `tools/list` and
`tools/call`. Tool order is deterministic, argument schemas are validated, and
an empty allowlist denies every tool.

Protocol-shaped Python unit tests are not treated as interoperability proof.
The isolated harness under `tests/mcp/official_sdk/` uses the official stable
v1 TypeScript SDK and its `StdioClientTransport` to start the real
`python -m mcp` entry point. It verifies initialization metadata,
`tools/list`, a successful `tools/call`, and an observable default-deny
governance rejection. The harness neither opens a network transport nor calls
an LLM.

The harness is intentionally a separate Node package. This repository's
application package is already named `mcp`, which collides with the import name
of the official Python SDK. Installing both into the application interpreter
would make correctness depend on Python path ordering. Keeping the official
client dependency isolated avoids renaming production modules or coupling the
API image to a test-only SDK.

The repository does not expose a public Streamable HTTP MCP endpoint. Adding
one requires transport authentication, network policy, per-request tenant
context, and deployment-specific authorization. The reusable local adapter and
governance layer should remain transport-independent.

Run the stdio server with an operator-owned tenant and explicit tools:

```bash
python -m mcp --tenant-id 1 \
  --allow-tool retrieval \
  --allow-tool financial_metrics
```

Run the official SDK interoperability gate after installing its pinned
test-only dependencies:

```bash
npm ci --ignore-scripts --prefix tests/mcp/official_sdk
npm test --prefix tests/mcp/official_sdk
```

## Prompt lifecycle

Prompt definitions have a name, semantic version, and SHA-256 checksum.
Runtime planning metadata records the exact prompt version/checksum used by a
request. When prompt behavior changes:

1. register a new version;
2. add or update golden cases;
3. run the deterministic evaluation suite;
4. run an explicitly opted-in live model benchmark if model behavior matters;
5. promote only after reviewing the report.

Do not silently change the content associated with an existing prompt version.

## Evaluation workflow

The default CI evaluation path is offline and deterministic:

```bash
pytest tests/evaluation tests/test_langgraph_agent.py \
  tests/test_prompt_registry.py -q --no-cov

python -m evaluation \
  --dataset evaluation/datasets/financial_golden_v1.json \
  --report artifacts/evaluation/offline-golden-report.json \
  --threshold 100
```

The versioned golden dataset records expected intent, workflow, strategy,
tools, sources, retrieval IDs, and reference claims. Metrics include ranked
retrieval precision/recall/MRR/NDCG, tool selection, routing matches, claim
coverage, answer quality, and a deterministic hallucination-risk heuristic.

The offline CLI executes the real intent, planning, execution-strategy, and
workflow-selection components. It stops before retrieval and generation. Its
threshold therefore gates planning contracts only; the JSON report explicitly
marks retrieval quality, citation faithfulness, answer quality, latency, and
model quality as unmeasured. Passing this gate is not evidence of live-model
quality.

`evaluation/model_benchmark.py` is provider-agnostic. It never calls a model
unless the caller passes both a provider callable and
`execute_provider=True`. The lexical scorer is a reproducible baseline, not an
LLM judge or a substitute for human financial review.

## LoRA and fine-tuning workflow

Training is intentionally separated from the online API image:

```bash
python -m pip install -r requirements/training.txt
```

```python
from training import LoRAConfig, run_lora_training

config = LoRAConfig(
    dataset_path="training/datasets/financial_sft_v1.json",
    base_model_id="an-approved-hugging-face-model",
)

# Safe default: validate data, configuration and optional dependencies.
readiness = run_lora_training(config)
assert readiness.actual_training_ran is False

# A real run additionally requires reviewed data, model/license approval,
# adequate hardware and explicit operator confirmation.
result = run_lora_training(
    config,
    dry_run=False,
    confirm_training=True,
)
assert result.actual_training_ran is True
```

The dataset loader rejects unknown fields, invalid conversation ordering, PII,
credentials, and common secret patterns. No trained adapter or claim of model
quality is bundled with this repository; those require an actual controlled
training run and evaluation report. A confirmed run may download the external
base model, require a Hugging Face access token, allocate substantial
CPU/GPU/RAM, and write adapter artifacts to `output_dir`; it is intentionally
outside normal API startup and CI.

## Maintainer verification

Run these gates before proposing a change:

```bash
ruff check api agent auth billing cache config core evaluation llm mcp memory \
  middleware migrations models observability prompts retrieval services \
  storage tasks training workers

pytest tests/ -m "not e2e and not perf" \
  --ignore=tests/e2e \
  --ignore=tests/benchmark \
  --ignore=tests/execution/test_execution_benchmark.py \
  --ignore=tests/memory/test_memory_benchmark.py \
  --ignore=tests/planning/test_complexity_benchmark.py \
  --no-cov -q

npm ci --ignore-scripts --prefix tests/mcp/official_sdk
npm test --prefix tests/mcp/official_sdk

cd frontend
npm ci
npm test
npm run build
```

For deployment changes, provide non-production values only for validation:

```bash
POSTGRES_PASSWORD=ci-only REDIS_PASSWORD=ci-only \
  docker compose config --quiet
```

Real production secrets belong outside source control.
