# Financial RAG Assistant V8.1.0 — P1.2 Offline Release Gate

Date: 2026-09-14  
Execution mode: deterministic/offline replay only

## Release decision

`P1.2 OFFLINE RELEASE GATE: PASS`

No DeepSeek request was made. The future live smoke remains a separate,
explicitly gated operation.

## Required metrics

| Gate | Result | Notes |
|---|---:|---|
| Candidate Recall@12 | Source 99.6%; chunk 100.0% | Frozen P1.1 ground truth |
| Post-Rerank Recall@4 | Source 99.6%; chunk 95.8% | 24 chunk-ground-truth cases |
| Final Context Coverage | Source 99.6%; chunk 95.8% | Same frozen cases |
| Historical raw numeric gate | 47/100 | Baseline; not weakened |
| Normalized numeric gate | 83/100 | P1.1 normalization baseline |
| Production-safe numeric gate | 100/100 | Frozen answers replayed through production sanitizer |
| Period gate | 100/100 | Frozen P1.1 gate |
| Metric gate | 100/100 | Frozen P1.1 gate |
| Company gate | 100/100 | Grounding policy removes out-of-scope evidence |
| Critical wrong-company claims | 0 | Sanitizer rejects mismatched evidence |
| Critical wrong-period claims | 0 | Period filter rejects mismatched evidence |
| Unsupported numeric claims in final output | 0 | Unsupported lines become insufficient-evidence text |

## Production path

The live RAG path now follows:

`LLM raw answer → claim extraction → semantic evidence filter → deterministic
grounding validator → supported/derivable/unsupported disposition → sanitized
answer → context/citations/API response`

`core.answer_grounding.sanitize_answer` is called by
`core.core_engine.run_rag` for RAG answers. Direct chat and deterministic tool
results remain separate paths because they do not claim retrieved financial
evidence.

## Frozen answer replay

`evaluation/p1_2_release_gate.py` replayed the 100 answers in
`formal_20260914_p0_quality_sprint1_1_final` without a provider call. It wrote:

- `evaluation/results/p1_2_release_replay.json`
- `evaluation/results/p1_2_release_summary.json`

47 cases contained one or more claims that were removed or downgraded. The
post-sanitization pass was 100/100 with no unsupported numeric claim remaining.
The 16 historical `NO_SUPPORTING_CITATION` and one `VALUE_MISMATCH` are
reported as baseline failures; they were not hidden by changing the evaluator.

## Contract tests

`tests/evaluation/test_answer_grounding_contract.py` covers supported values,
wrong value, wrong period, wrong company, unit normalization, deterministic
derived growth, and multi-company evidence isolation. All seven tests pass.

## Workflow and PDF regressions

- The period-qualified metric query `What is the revenue for Q1` now routes to
  document QA/RAG while bare concept questions such as `What is revenue?`
  remain direct chat. The planner does not invent a company when context is
  absent.
- The three successful-upload E2E cases now use a real one-page, text-bearing
  PDF generated with PyMuPDF. The backend still rejects zero-page PDFs; no
  invalid document is accepted or indexed.
- Provider/Docker E2E tests are marked `live` and are skipped unless
  `ALLOW_REAL_PROVIDER=true`. This is an explicit cost guard, not a business
  assertion bypass.

## Validation

| Check | Result |
|---|---|
| Backend offline pytest | 2095 passed, 23 explicit live tests skipped |
| Workflow benchmark | 80 passed, 2 skipped |
| Grounding contract tests | 7 passed |
| Standalone deployment E2E (`test_e2e_full.py`) | 11 passed before live marker was applied |
| Frontend tests | 31 passed |
| Frontend build | PASS (`vite build`) |
| Ruff | PASS |
| `git diff --check` | PASS |
| Provider call guard | PASS (`ALLOW_REAL_PROVIDER=false` blocks real SDK construction under pytest) |
| Docker Compose health | six services healthy |
| `/api/v1/health` | HTTP 200 |
| `/api/v1/ready` | HTTP 200; database, Redis and Chroma `ok` |

The 23 skipped tests are explicitly live/provider or external Docker tests; no
offline failure is hidden with `xfail` or a relaxed assertion.

## Cost and safety

```text
DEEPSEEK_API_USED: NO
REAL_PROVIDER_CALLS: 0
API_COST: $0
```

No secrets, tokens, Authorization headers, or provider response credentials are
stored in the new artifacts or printed by the replay command.

## Final fields

```text
SPRINT_STATUS: PASS
DEEPSEEK_API_USED: NO
REAL_PROVIDER_CALLS: 0
API_COST: $0
CANDIDATE_RECALL: source 99.6%; chunk 100.0%
RERANK_RECALL: source 99.6%; chunk 95.8%
FINAL_CONTEXT_COVERAGE: source 99.6%; chunk 95.8%
RAW_NUMERIC_GATE: 47/100
NORMALIZED_NUMERIC_GATE: 83/100
PRODUCTION_SAFE_NUMERIC_GATE: 100/100
NO_SUPPORTING_CITATION_BEFORE: 16
NO_SUPPORTING_CITATION_AFTER: 0
VALUE_MISMATCH_BEFORE: 1
VALUE_MISMATCH_AFTER: 0
CRITICAL_WRONG_COMPANY: 0
CRITICAL_WRONG_PERIOD: 0
UNSUPPORTED_NUMERIC_CLAIMS: 0
WORKFLOW_BENCHMARK: PASS
ZERO_PAGE_PDF_E2E: PASS (invalid zero-page remains rejected)
BACKEND_FULL_OFFLINE_TESTS: PASS (2095 passed; 23 live skipped)
FRONTEND_TESTS: PASS
RUFF: PASS
BUILD: PASS
DIFF_CHECK: PASS
DOCKER: PASS
DEEPSEEK_CALL_GUARD: PASS
READY_FOR_REAL_API_SMOKE: YES
```

`READY_FOR_REAL_API_SMOKE: YES` means the offline gate is complete; no live
smoke or 100-question run was started in this sprint.
