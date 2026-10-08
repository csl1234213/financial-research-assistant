# Financial RAG Assistant — P1 Offline Quality Sprint

## Scope and safety

This sprint used only frozen artifacts from
`evaluation/results/formal_20260914_p0_quality_sprint1_1_final/` and a seeded
in-memory retrieval fixture. No DeepSeek request, external network request,
database write, or Docker data mutation was performed.

`DEEPSEEK_API_USED: NO`  
`REAL_PROVIDER_CALLS: 0`  
`API_COST: $0`

The frozen P0.1 answer set was not regenerated. The P0 baseline used for the
diff is `formal_20260914_budget8192`; the current set is the separate P1.1
release artifact.

## Failure diff

The deterministic diff is stored at
`evaluation/results/p1_failure_diff.json` and includes the question, expected
criteria, old/new main answer, retrieval citations, grades, and suspected
failure layer for each changed case.

| Classification | Count |
|---|---:|
| IMPROVED | 18 |
| REGRESSED | 17 |
| UNCHANGED_CORRECT | 27 |
| UNCHANGED_PARTIAL | 12 |
| UNCHANGED_INCORRECT | 24 |
| UNCOMPARABLE_REVIEW | 2 |

English regressions: **9**. In the available frozen artifact comparison,
English strict CORRECT changed from **19/50 (38%)** to **18/50 (36%)**. The
previously quoted 42% baseline is not reproducible from the preserved
`formal_20260914_budget8192` semantic artifact, so it is not silently used.
Regression layers were primarily RERANK (9),
REASONING (6), RETRIEVAL_RECALL (1), and DATASET (1). The two
`UNCOMPARABLE_REVIEW` rows were not treated as regressions because the old
semantic reviewer had no stable grade.

The two stale planning contracts for broad company performance questions were
corrected in `evaluation/datasets/financial_golden_v1.json`: these questions
use the governed `document_qa → rag` path, while global research remains
`research → multi_step`. This is a dataset-contract correction, not a runtime
logic bypass.

## Retrieval benchmark

`evaluation/p1_quality.py` exercises the production `HybridRetriever` and
tenant retrieval tool with a seeded hash embedding and the frozen 303-chunk
reference corpus. It does not claim production embedding or Chroma quality.

| Metric | Result | Gate |
|---|---:|---:|
| Source Recall@4 | 93.0% | ≥80% |
| Source Recall@8 | 94.7% | ≥90% |
| Source Recall@12 | 96.0% | ≥95% |
| Eligible positive cases | 88 | — |
| Negative/direct-chat scope pass | 92/100 | — |
| Page Recall | N/A | no authoritative page labels in dataset |

The retrieval gate passes. Page-level recall is deliberately not fabricated;
the frozen dataset records expected source files but not authoritative target
pages/chunks.

## Table-aware retrieval

Twenty-four deterministic table cases cover Tesla, NVIDIA, and Apple metrics
including revenue, gross margin, EPS, net income, cash flow, segment metrics,
operating income, energy, and iPhone data.

`TABLE_RETRIEVAL: PASS (24/24)`  
Artifact: `evaluation/results/p1_table_retrieval.json`

`core/query_scope.py` now provides a provider-free scope contract with
`FACT`, `SUMMARY`, `COMPARE`, `ANALYSIS`, `RISK`, and `GENERAL_CONCEPT` labels;
its six-case unit contract passes. Runtime answer-budget integration is kept as
the next focused change so this sprint does not alter generated answers before
the deterministic citation failures are repaired.

## Citation gate

The offline gate validates citation source/chunk/page identity, company scope,
period compatibility, and numeric-token presence without an LLM judge.

| Gate | Result |
|---|---:|
| Citation Numeric Gate | 47/100 (47.0%) — FAIL |
| Citation Period Gate | 100/100 (100%) — PASS |
| Citation Metric Gate | 100/100 (100%) — PASS |
| Citation Company Gate | 98/100 (98%) — FAIL |

The numeric result is intentionally strict: numeric claims in the main answer
must be found in the cited chunk text. It exposes unsupported or over-expanded
answers instead of accepting a citation merely because the source filename is
valid. The company failures are the multi-turn follow-up cases where the
previous turn's company was not preserved in the retrieved evidence.

Artifact: `evaluation/results/p1_citation_gate.json`.

## ZH-034 root cause

`ZH-034` asks for Alibaba's latest quarterly financial performance. The frozen
knowledge corpus contains only Apple, NVIDIA, and Tesla chunks; it contains
zero Alibaba chunks and no Alibaba source file. The retriever therefore cannot
recover evidence. The answer's insufficient-evidence response is correct for
the available knowledge scope, while its semantic grade `FAILED` reflects that
the requested analysis could not be performed. This is a **DATASET / KNOWLEDGE
SCOPE** finding, not a reason to invent an Alibaba answer or loosen retrieval
filters.

## Focused offline inventory

`evaluation/regression/p1_quality_cases/README.md` documents the focused
inventory. The runner selected **38 cases** including all English regressions,
key retrieval/citation failures, `EN-007`, `ZH-034`, `ZH-044`, multi-turn
follow-ups, and Tesla period cases.

Artifacts:

- `evaluation/results/p1_offline_planning_baseline.json`
- `evaluation/results/p1_retrieval_benchmark.json`
- `evaluation/results/p1_table_retrieval.json`
- `evaluation/results/p1_citation_gate.json`
- `evaluation/results/p1_focused_cases.json`
- `evaluation/results/p1_offline_summary.json`

## Offline gate and verification

| Gate | Result |
|---|---|
| Routing / planning contract | PASS — 6/6 |
| Company / period / metric parser coverage | PASS in existing offline suite |
| Retrieval Recall@4/@8/@12 | PASS — 93.0% / 94.7% / 96.0% |
| Table Retrieval Regression | PASS — 24/24 |
| Citation Numeric Gate | FAIL — 47.0% |
| Citation Period Gate | PASS — 100% |
| Citation Metric Gate | PASS — 100% |
| Citation Company Gate | FAIL — 98.0% |
| Backend offline tests | PASS — 192 passed, 1 warning |
| Frontend tests | PASS — 31 passed |
| Frontend build | PASS |
| Ruff | PASS |
| `git diff --check` | PASS |
| Docker health | PASS — six services healthy; health/ready 200 |

Because the citation gates are not all passing, the required stop condition
applies:

`READY_FOR_REAL_API_SMOKE: NO`

No 10Q Smoke and no new 100Q DeepSeek benchmark were run.

## Final status

`SPRINT_STATUS: OFFLINE_GATE_FAIL_CITATION_QUALITY`

The offline infrastructure is now repeatable and cost-controlled. The next
engineering step is to turn the 17 semantic regressions and the citation-gate
failures into deterministic regression cases, repair context/query-scope and
citation claim alignment offline, then rerun this gate. Only after it passes
should a 10-question real-provider smoke be authorized.
