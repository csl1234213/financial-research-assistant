# Financial RAG P0 Quality Sprint 1

## Scope and safety

This sprint audited the canonical repository at `<repository>`. Existing evaluation datasets, expected answers, Docker volumes, and prior result directories were preserved. No Git staging, commit, push, database reset, volume deletion, or provider secret output was performed.

## Architecture audit

| Concern | Runtime location | Finding |
| --- | --- | --- |
| Intent routing | `core/intent_analyzer.py`, `agent/planning/keyword_rules.py` | Two rule paths previously disagreed on Chinese definition questions. |
| Planning | `agent/planning/task_analyzer.py`, `agent/query_planner.py` | Retrieval plans now carry explicit period/metric filters. |
| Retrieval | `retrieval/hybrid_retriever.py`, `retrieval/bm25_retriever.py`, `retrieval/query_enrichment.py` | Hybrid retrieval now applies semantic period/metric constraints before RRF. |
| Source metadata | `document_loader.py`, `tasks/knowledge_tasks.py`, `core/core_engine.py` | Chunks expose periods and metrics detected from extracted text; filename remains a display label. |
| Citation gate | `core/citation_gate.py`, `core/context_builder.py` | Company, period, metric, and deterministic numeric support checks run before/after generation. |
| Provider retry | `llm/adapters/deepseek_provider.py` | Existing SDK retry isolation was fault-tested; adapter owns a three-attempt total budget. |

## P0 fixes

1. General finance definitions such as `什么叫毛利率？` and `What does gross margin mean?` now route to `DIRECT_CHAT`/`CHAT`, while named-company or uploaded-report questions remain retrieval tasks.
2. Period parsing recognises calendar and fiscal quarter forms (`Q2_2025`, `Q1_FY2027`, Chinese quarter wording). Retrieval matches period text in the chunk, not only the filename, so comparative tables remain usable without treating a filename as the report period.
3. Query plans carry period/metric filters. Table-aware lexical retrieval now prefers the NVIDIA Q1 FY2027 actual-results chunk over Q2 outlook text.
4. Citation gating rejects wrong-company/period/metric evidence and marks a bounded fallback as `unverified` instead of silently returning empty or fabricated support. Numeric answer claims are checked against evidence numbers deterministically.

## Before / focused After

The previous frozen 100-question review (budget-8192 run) recorded 34% strict correct overall (EN 42%, ZH 26%) and 40.11% citation support. Those are historical baseline values only.

| Signal | Before | Focused After |
| --- | --- | --- |
| ZH-044 `什么叫毛利率` | `GLOBAL_RESEARCH`/RAG with Apple citations | `DIRECT_CHAT`, `direct_chat`, `direct_llm`, `use_retrieval=false`, 0 citations (real HTTP) |
| EN-007 NVIDIA Q1 FY2027 | Refused Q1 and cited Q2 outlook | Real HTTP response returned Q1 FY2027 actual revenue in a `rag` response with 3 NVIDIA citations |
| Tesla Q2 revenue | Period could be confused with the filename/latest Q4 narrative | Real HTTP response returned Q2 revenue with 2 Tesla citations; period-aware tests pass |
| Retry fault drill | Historical 503 drill showed 9 attempts | Current isolated 429/503/timeout drill: 3 total attempts, 2 retries each |
| Focused tests | — | 150 targeted pytest tests passed; offline regression 53 passed |

## Frozen 100-question rerun

The new run is isolated at `evaluation/results/formal_20260914_p0_quality_sprint1/` and did not overwrite earlier runs.

- Dataset: 100 unique questions, EN50/ZH50; frozen dataset unchanged.
- Transport: 100/100 HTTP 200.
- Application errors: 9 (EN-001, ZH-014, ZH-019, ZH-028 empty model content; ZH-045–ZH-049 runtime fallback).
- ZH-044 route remained correct in the batch; EN-007 returned Q1 FY2027 actual-results content.
- Fresh semantic review could start only once: the provider then returned HTTP 402. Therefore new accuracy, citation-support, and P95 quality metrics are **NOT VERIFIED** and must not be inferred from the historical run.

## Verification gates

- Backend focused pytest: **PASS** (150 passed).
- Credential-free regression harness: **PASS** (53 passed).
- Production Ruff scope: **PASS**.
- Frontend tests: **PASS** (31 passed).
- Frontend build: **PASS** (`tsc -b && vite build`).
- `git diff --check`: **PASS** (only existing line-ending warnings).
- Docker rebuild: `backend` and `agent-worker` rebuilt; six services healthy; `/api/v1/health` and `/api/v1/ready` returned 200.
- Secret output/log scan: no secrets were printed by this sprint.

## Files changed for this sprint

- `agent/planning/keyword_rules.py`
- `agent/query_planner.py`
- `core/citation_gate.py`
- `core/context_builder.py`
- `core/core_engine.py`
- `core/intent_analyzer.py`
- `document_loader.py`
- `retrieval/hybrid_retriever.py`
- `retrieval/periods.py`
- `retrieval/query_enrichment.py`
- `tasks/knowledge_tasks.py`
- `tests/planning/test_bilingual_financial_routing.py`
- `tests/retrieval/test_period_aware_retrieval.py`
- `tests/test_citation_gate.py`

## Gate decision

**P0 QUALITY SPRINT 1: PARTIAL / BLOCKED**

The deterministic routing, period-aware retrieval, citation gate, retry boundary, focused tests, Docker health, and build gates pass. The quality gate remains blocked because the fresh 100-question semantic review was stopped by provider HTTP 402 and the batch itself contained 9 application-layer errors. Re-run the new result directory's semantic review and summarize only after valid provider capacity is available; do not reuse historical grades.
