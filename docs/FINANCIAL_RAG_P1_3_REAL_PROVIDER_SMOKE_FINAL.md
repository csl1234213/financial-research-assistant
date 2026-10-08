# Financial RAG Assistant — P1.3 Frozen Real Provider Smoke (Final)

## Run composition

This report combines two independent production runs without presenting them as one batch:

1. **P1.3.2 1Q Canary:** EN-007, one request, PASS.
2. **P1.3.3 continuation:** the remaining nine frozen questions, one request each, completed without runtime failure.

No 100Q benchmark or evaluator call was executed.

## Final result

```text
SMOKE_STATUS: FAIL
CANARY_1Q: PASS
REMAINING_9Q_HTTP_SUCCESS: 9/9
REMAINING_9Q_APPLICATION_SUCCESS: 9/9
TOTAL_FROZEN_SMOKE: 10
TOTAL_HTTP_SUCCESS: 10/10
TOTAL_APPLICATION_SUCCESS: 10/10

CORRECT: 4
PARTIAL: 3
INCORRECT: 2
FAILED: 0

EN_007: PASS
ZH_044: PASS
TESLA_PERIOD: PASS for EN-002; comparison-period findings remain in EN-019/ZH-019

WRONG_COMPANY: 0
WRONG_PERIOD: 2
UNSUPPORTED_NUMERIC_FINAL_CLAIMS: 0
EVIDENCE_UTILIZATION_FULL: 4
EVIDENCE_UTILIZATION_PARTIAL: 4
EVIDENCE_UTILIZATION_FAILED: 1
OVER_SANITIZATION_COUNT: 1

RAW_UNSUPPORTED_CLAIMS: 10
REMOVED_CLAIMS: 10
REWRITTEN_CLAIMS: 4
FINAL_UNSUPPORTED_CLAIMS: 0

TOTAL_PROVIDER_CALLS: 8
TOTAL_INPUT_TOKENS: 13307
TOTAL_OUTPUT_TOKENS: 24069
TOTAL_CACHED_TOKENS: 11648
MAIN_QUERY_COST: UNKNOWN
EVALUATOR_COST: $0
TOTAL_SMOKE_COST: UNKNOWN

LATENCY_P50: 7944.60ms
LATENCY_P90: 21174.22ms
LATENCY_MAX: 31248.52ms
OVER_45S: 0
OVER_60S: 0
OVER_120S: 0

ALLOW_REAL_PROVIDER_RESTORED: true
READY_FOR_FINAL_100Q_BENCHMARK: NO
```

## Why the gate failed

All HTTP and application runtime gates passed. The quality gate failed on semantic evidence use: Apple financial headline metrics were omitted in ZH-013, Apple cash-flow coverage was incomplete in EN-016, Tesla Q4/Q2 period labeling was mixed in the comparison cases, and the ZH-008 answer contradicted sufficient retrieved evidence by presenting an insufficient-evidence lead. These are preserved as offline regression targets; no real request is repeated in this run.

Detailed continuation evidence is in [P1.3.3 report](FINANCIAL_RAG_P1_3_3_REMAINING_9Q_SMOKE.md), and the single-canary evidence is in [P1.3.2 report](FINANCIAL_RAG_P1_3_2_REAL_PROVIDER_CANARY.md).

