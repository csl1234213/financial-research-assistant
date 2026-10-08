# Financial RAG P1.4.9 — Real Provider 5Q Verification

Date: 2026-09-16

## Fixed set and execution

The frozen five-question set was executed once: `ZH-013`, `EN-016`,
`EN-019`, `ZH-019`, and `ZH-008`. Each question used the production HTTP
path and made exactly one DeepSeek request. No evaluator request, retry, or
question replacement was performed.

## Result

```text
FACT_LEDGER_RECHECK_STATUS: PASS
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
CORRECT: 5/5
PARTIAL: 0
INCORRECT: 0
FAILED: 0
REQUIRED_FACT_FULL: 5/5
EVIDENCE_UTILIZATION_FULL: 5/5
WRONG_COMPANY: 0
WRONG_PERIOD: 0
WRONG_METRIC: 0
UNSUPPORTED_NUMERIC: 0
OVER_SANITIZATION: 0
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
AUDIT_INTEGRITY: PASS
```

| Case | Grade | Required facts | Evidence utilization | Final unsupported numeric | Sources |
| --- | --- | --- | --- | ---: | --- |
| EN-016 | CORRECT | FULL | FULL | 0 | Apple_Q2_2026.pdf |
| EN-019 | CORRECT | FULL | FULL | 0 | Tesla_Q2_2025.pdf; NVIDIA_Q1_FY2027.pdf |
| ZH-008 | CORRECT | FULL | FULL | 0 | NVIDIA_Q1_FY2027.pdf |
| ZH-013 | CORRECT | FULL | FULL | 0 | Apple_Q2_2026.pdf |
| ZH-019 | CORRECT | FULL | FULL | 0 | Tesla_Q2_2025.pdf; NVIDIA_Q1_FY2027.pdf |

## Cost and latency

```text
INPUT_TOKENS: 23110
OUTPUT_TOKENS: 14044
CACHED_TOKENS: 8448
MAIN_QUERY_COST: $0.021302088
EVALUATOR_CALLS: 0
EVALUATOR_COST: $0
LATENCY_P50_MS: 12398.95
LATENCY_MAX_MS: 27785.43
```

## Interpretation

The previous failures were caused by duplicate tenant/public filing
provenance, stale refusal fragments in answer composition, and display-string
numeric checks. After the offline repair, all five answers retained the
required facts and only canonical public filing sources were cited where a
duplicate tenant document existed.

## Runtime restoration

```text
ALLOW_REAL_PROVIDER: false
P1_3_SMOKE_AUDIT_PATH: unset
frontend: healthy
backend: healthy
agent-worker: healthy
postgres: healthy
redis: healthy
chromadb: healthy
/api/v1/health: 200
/api/v1/ready: 200
```

No volumes or database data were deleted or recreated.

## Decision

```text
P1.4.9_REAL_5Q_GATE: PASS
READY_FOR_NEXT_STEP: YES
```

Raw HTTP responses and audit records are stored under
`evaluation/results/p1_4_9_real_provider_5q_20260916/` without credentials or
authorization headers.
