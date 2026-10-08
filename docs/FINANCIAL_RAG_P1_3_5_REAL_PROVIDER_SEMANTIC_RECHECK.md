# Financial RAG Assistant — P1.3.5 Real Provider Semantic Recheck

Date: 2026-09-15  
Scope: exactly five frozen production-path requests; no evaluator calls, no 10Q/100Q execution.

## Result

```text
SEMANTIC_RECHECK_STATUS: FAIL
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
CORRECT: 0/5
PARTIAL: 5/5
INCORRECT: 0
FAILED: 0
READY_FOR_FINAL_10Q_RELEASE_SMOKE: NO
```

The runtime path was healthy for all five calls. The failure is semantic: the live answers did not preserve the frozen required facts. Per the runbook, no failed question was retried and no further smoke request was started.

## Frozen questions

The immutable selection is [p1_3_5_semantic_recheck_5.json](../evaluation/datasets/p1_3_5_semantic_recheck_5.json). It contains, in order: `ZH-013`, `EN-016`, `EN-019`, `ZH-019`, and `ZH-008`, copied from the frozen 100-question dataset. The source dataset SHA-256 is recorded in that file.

## Per-question gates

| ID | HTTP / app | Quality | Required facts | Evidence utilization | Main finding |
|---|---:|---|---|---|---|
| ZH-013 | 200 / PASS | PARTIAL | PARTIAL | PARTIAL | Apple Q2 answer said evidence was insufficient and omitted net sales, net income, and six-month operating cash flow despite Apple evidence being retrieved. |
| EN-016 | 200 / PASS | PARTIAL | PARTIAL | PARTIAL | Answer discussed cash paid for income taxes, not the required six-month operating cash flow of `$82,627m`; this is a metric-selection failure. |
| EN-019 | 200 / PASS | PARTIAL | PARTIAL | PARTIAL | Comparison omitted Tesla Q2 revenue `$22,496m`; citations also included an unexpected duplicate `tesla_report.pdf` source and NVIDIA Q2 guidance. |
| ZH-019 | 200 / PASS | PARTIAL | PARTIAL | PARTIAL | Comparison retained growth percentages but omitted the required Tesla Q2 and NVIDIA Q1 revenue anchors; unexpected duplicate Tesla source was cited. |
| ZH-008 | 200 / PASS | PARTIAL | PARTIAL | PARTIAL | Correct NVIDIA evidence was retrieved, but the final answer was downgraded to “证据不足” and omitted the Data Center core fact; this is an over-sanitization candidate. |

The deterministic run recorded `WRONG_COMPANY: 2`, `WRONG_PERIOD: 1`, `UNSUPPORTED_NUMERIC: 8`, and `OVER_SANITIZATION: 1`. These are release-gate failures, not evaluator judgments.

## Raw/final evidence

Each case artifact contains the raw model answer, final sanitized answer, retrieved evidence with chunk content, final context, raw/final citations, supported/derivable/uncertain/unsupported claims, removed/rewritten claims, and required-fact coverage:

- [ZH-013.json](../evaluation/results/p1_3_5_real_provider_semantic_recheck/ZH-013.json)
- [EN-016.json](../evaluation/results/p1_3_5_real_provider_semantic_recheck/EN-016.json)
- [EN-019.json](../evaluation/results/p1_3_5_real_provider_semantic_recheck/EN-019.json)
- [ZH-019.json](../evaluation/results/p1_3_5_real_provider_semantic_recheck/ZH-019.json)
- [ZH-008.json](../evaluation/results/p1_3_5_real_provider_semantic_recheck/ZH-008.json)

The machine-readable aggregate is [summary.json](../evaluation/results/p1_3_5_real_provider_semantic_recheck/summary.json). The backend opt-in audit is [raw_grounding_audit.jsonl](../evaluation/results/p1_3_5_real_provider_semantic_recheck/raw_grounding_audit.jsonl).

## Cost and latency

```text
INPUT_TOKENS: 7399
OUTPUT_TOKENS: 14975
CACHED_TOKENS: 4224
MAIN_QUERY_COST: $0.009792042
EVALUATOR_CALLS: 0
EVALUATOR_COST: $0
LATENCY_P50: 14601.85 ms
LATENCY_MAX: 26496.60 ms
```

Provider usage was returned by the application for all five calls. No cost-bearing evaluator request was made.

## Runtime guard and safety

The provider flag and audit path were enabled only for the five-request window. After the run, backend was recreated without changing volumes, with:

```text
ALLOW_REAL_PROVIDER=false
P1_3_SMOKE_AUDIT_PATH=unset
```

The guard was verified in the running backend. No password, token, API key, or authorization header is included in the report or artifacts. No commit, push, volume deletion, or database reset was performed.

## Required next step

Convert these live failures into offline regressions before any second smoke attempt:

1. Preserve Apple operating-cash-flow table evidence and prevent tax-payment metric substitution.
2. Improve comparison query coverage so both Tesla Q2 and NVIDIA Q1 required facts survive retrieval/context construction.
3. Investigate duplicate Tesla source contamination and the ZH-008 false “证据不足” downgrade.

Only after the offline gate is green may a new smoke window be requested. The final 10Q release smoke was not run.
