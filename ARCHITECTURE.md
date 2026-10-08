# Financial Agent Runtime Assistant — V8.2.0 Architecture

## Overview

Financial Agent Runtime Assistant implements a **layered Agent Runtime architecture** designed for financial document research. The system supports both Direct Chat and RAG workflows, with a pluggable capability layer for Memory, Metrics, Reliability, Tracing, and Tool Calling.

---

## Architecture Layers

```
                         User
                          │
                          ▼
                   ┌──────────────┐
                   │ 1. Intent    │
                   │    Layer     │
                   └──────┬───────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ 2. Planning  │
                   │    Layer     │
                   └──────┬───────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ 3. Workflow  │
                   │    Layer     │
                   └──────┬───────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ 4. Execution │
                   │    Layer     │
                   └──────┬───────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ 5. Provider  │
                   │    Layer     │
                   └──────┬───────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ 6. Runtime   │
                   │ Capability   │
                   │    Layer     │
                   └──────────────┘
```

### 1. Intent Layer

**File:** `core/intent_analyzer.py`

Classifies user queries into one of four intent types:
- `DIRECT_CHAT` — Conversational queries (Hello, What is AI?)
- `SINGLE_COMPANY` — Single company research (Analyze Tesla revenue)
- `COMPARE_COMPANIES` — Cross-company comparison (Apple vs Tesla)
- `GLOBAL_RESEARCH` — Market/industry questions (Market trend 2026)

Uses research signal detection to distinguish chat from research queries.

### 2. Planning Layer

**Files:** `agent/query_planner.py`, `agent/planning/`

Analyzes task complexity and generates structured execution plans:
- `TaskAnalyzer` — Determines task type and required resources
- `ComplexityAnalyzer` — Estimates complexity level
- `RoutingPolicy` — Selects optimal execution path

### 3. Workflow Layer

**Files:** `agent/workflow/`

Orchestrates execution strategy into actionable workflows:
- `WorkflowEngine` — Builds workflow from strategy result
- `WorkflowExecutor` — Executes workflow steps with context
- `WorkflowBridge` — Bridges between Runtime and Workflow layers

### 4. Execution Layer (Dual-Engine Design)

The project uses a **dual-engine execution architecture**:

```
Strategy Execution Engine          Step Execution Engine
(agent/execution/)                 (agent/execution_engine.py)

"How to execute?"                  "Execute each step"
         │                                  │
         ▼                                  ▼
  Selects strategy:                 Dispatches to handlers:
  - RAG                             - Retrieve
  - DirectLLM                       - Tool
  - Parallel                        - Metrics
  - MultiStep                       - Memory
  - ToolCalling                     - Reasoning
```

#### Strategy Execution Engine

**File:** `agent/execution/execution_engine.py`

Responsible for selecting the execution strategy. Receives `ExecutionContext` (task, complexity, routing) and produces `ExecutionResult` (strategy, steps, parallelism, confidence).

Supported strategies:
- **RAG** — Retrieval-Augmented Generation
- **DirectLLM** — Direct LLM conversation (no retrieval)
- **Parallel** — Concurrent execution of multiple steps
- **MultiStep** — Sequential step execution with dependencies
- **ToolCalling** — External tool invocation

#### Step Execution Engine

**File:** `agent/execution_engine.py`

Responsible for executing individual workflow steps. Iterates over `ExecutionPlan` tasks, dispatches by `StepType`, resolves dependencies, and tracks step status.

This design separates **strategic decision-making** (how to execute) from **step-level execution** (execute each step), enabling independent evolution of both layers.

### 5. Provider Layer

**Files:** `llm/provider.py`, `llm/adapters/`, `llm/factory/`, `llm/router/`

LLM Provider abstraction with factory pattern:

```
ProviderFactory.create(config)
        │
        ▼
ProviderRegistry.get(name)
        │
        ▼
BaseProvider.chat(ChatRequest)
```

Supported providers:
- **DeepSeek** — Production, primary provider
- **Gemini** — Supported, registered in ProviderRegistry
- **Azure** — Reserved extension point
- **Claude** — Reserved extension point

### 6. Runtime Capability Layer

Pluggable capabilities that can be activated by injecting engine instances into `AgentRuntime`:

| Capability | Module | Status | Description |
|---|---|---|---|
| Memory | `agent/memory/` | Framework Ready | Retrieve + Store lifecycle hooks |
| Metrics | `agent/metrics/` | Framework Ready | `runtime_duration`, `workflow_duration`, `estimated_tokens` |
| Reliability | `agent/reliability/` | Framework Ready | Retry, Timeout, CircuitBreaker, HealthCheck, RateLimiter, Fallback |
| Tracing | `agent/tracing/` | Framework Ready | Console, File, Memory tracers with TraceRegistry |
| Tool Calling | `agent/tools/` | Framework Ready | ToolEngine with ToolCallingStrategy |

---

## Agent Runtime Pipeline

The full pipeline executed by `AgentRuntime.run()`:

```
1. Intent Analysis
       │
2. Memory Retrieve (if memory_engine injected)
       │
3. Planning — TaskAnalyzer + ComplexityAnalyzer
       │
4. Routing — ModelRouter
       │
5. Strategy Execution — StrategyExecutionEngine
       │
6. Execution Plan — QueryPlanner
       │
7. Workflow — WorkflowEngine + WorkflowExecutor
       │
8. Execution — Step Execution Engine (handler dispatch)
       │
9. Reasoning — ReasoningEngine
       │
10. Memory Store (if memory_engine injected)
       │
11. Metrics Collection (if metric_engine injected)
       │
12. RuntimeResult
```

---

## Project Structure

```
financial-rag-assistant/
├── agent/
│   ├── agent_runtime.py          # Unified lifecycle manager
│   ├── execution_engine.py       # Step Execution Engine (handler dispatch)
│   ├── execution_plan.py         # PlanStep / ExecutionPlan structures
│   ├── execution_result.py       # Step execution result
│   ├── query_planner.py          # Intent → ExecutionPlan
│   ├── reasoning_engine.py       # Evidence → Facts / Risks / Opportunities
│   ├── reasoning_models.py       # Evidence + ReasoningResult
│   ├── runtime_context.py        # Runtime state
│   ├── runtime_result.py         # Unified output
│   ├── runtime_state.py          # Reliability state tracking
│   ├── execution/                # Strategy Execution Engine
│   │   ├── execution_engine.py   # Strategy selection
│   │   ├── execution_context.py
│   │   ├── execution_result.py
│   │   ├── execution_strategy.py
│   │   ├── strategy_registry.py
│   │   ├── strategy_enums.py
│   │   ├── execution_dispatcher.py
│   │   ├── execution_handler.py
│   │   ├── handlers/             # RAG, DirectLLM, Parallel, MultiStep, ToolCalling
│   │   └── strategies/           # Strategy implementations
│   ├── workflow/                 # Workflow Engine + Executor
│   ├── planning/                 # TaskAnalyzer, ComplexityAnalyzer, Routing
│   ├── memory/                   # Memory Engine (Framework Ready)
│   ├── metrics/                  # Metrics Engine (Framework Ready)
│   ├── reliability/              # Reliability Engine (Framework Ready)
│   ├── tracing/                  # Tracing Engine (Framework Ready)
│   └── tools/                    # Tool Engine (Framework Ready)
├── core/
│   ├── core_engine.py            # Main entry point (run_rag)
│   ├── intent_analyzer.py        # Intent classification
│   ├── context_builder.py        # Evidence → structured context
│   ├── knowledge_manager.py      # Knowledge source management
│   ├── report_builder.py         # Structured research report
│   └── citation_formatter.py     # Citation formatting
├── llm/
│   ├── provider.py               # Bridge adapter (ProviderFactory + call_llm)
│   ├── adapters/                 # Provider implementations
│   ├── factory/                  # ProviderFactory
│   ├── router/                   # ModelRouter
│   └── providers/                # Base classes and models
├── retrieval/
│   └── hybrid_retriever.py       # Semantic search + ranking
├── api/
│   ├── main.py                   # FastAPI entry point
│   ├── routers/                  # API route handlers
│   ├── services/                 # Business logic layer
│   └── schemas/                  # Pydantic request/response models
├── config/                       # Centralized configuration
├── tests/
│   ├── test_intent_analyzer.py
│   ├── planning/                 # Intent router regression matrix
│   └── e2e/                      # End-to-end tests
└── docs/                         # Architecture & deployment docs
```

---

## Data Flow

```
Upload PDF
      │
      ▼
Knowledge Base (ChromaDB)
      │
      ▼
User Question
      │
      ▼
Intent Classification
      │
      ▼
Planning (TaskAnalyzer + ComplexityAnalyzer)
      │
      ▼
Strategy Selection (RAG / DirectLLM / ...)
      │
      ▼
Workflow Orchestration
      │
      ▼
Retrieval (semantic search + ranking)
      │
      ▼
Context Building (Evidence → structured context)
      │
      ▼
Prompt Building
      │
      ▼
LLM (via ProviderFactory)
      │
      ▼
Research Report + Evidence Panel
```

---

## Design Principles

- **Single Responsibility** — Each module has one clear purpose
- **Layered Architecture** — Clear separation between Intent, Planning, Execution, and Provider layers
- **Pluggable Capabilities** — Memory, Metrics, Reliability, Tracing, and Tool Calling are injectable
- **Evidence-First** — Every output must be traceable to source documents
- **Graceful Degradation** — Runtime capabilities degrade gracefully when not injected
- **Provider Abstraction** — LLM providers are interchangeable via factory pattern

---

## Version Evolution

| Version | Milestone |
|---|---|
| V1 | Single PDF QA prototype |
| V2 | Multi-document RAG |
| V2.2 | Stable architecture |
| V3.0 | Agent Runtime Edition |
| V4.0 | Production Architecture (FastAPI, Docker, CI/CD) |
| V7.3.1 | Agent Runtime Framework (Layered Execution, Pluggable Capabilities) |
| V7.3.2 | Docker Production Packaging |
| V7.3.3 | Demo Knowledge Bootstrap |
| V8.1.0 | Production Agent Platform |
| V8.2.0 | Release-Aligned Financial AI Copilot |
