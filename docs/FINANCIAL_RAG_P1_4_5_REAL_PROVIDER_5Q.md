# Financial RAG P1.4.5 — Third Real Provider 5Q Verification

Date: 2026-09-15

## Result

```text
TEST_STATUS: FAIL
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
CORRECT_BY_REQUIRED_FACT_COVERAGE: 5/5
REQUIRED_FACT_FULL: 5/5
EVIDENCE_UTILIZATION_FULL: 5/5
WRONG_COMPANY: 0
WRONG_PERIOD: 0
WRONG_METRIC: 0
UNSUPPORTED_NUMERIC: 80
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
OVER_SANITIZATION: 0
```

The fixed five-question run completed without HTTP or provider failures and recovered every required fact. The release gate nevertheless failed because the post-flight grounding check found 80 unsupported numeric items in the complete user-visible reports. A successful required-fact completion does not override this grounding failure.

## Per-case result

| Case | Required facts | Evidence utilization | Wrong company | Wrong period | Wrong metric | Unsupported numeric |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| EN-016 | FULL | FULL | 0 | 0 | 0 | 2 |
| EN-019 | FULL | FULL | 0 | 0 | 0 | 23 |
| ZH-008 | FULL | FULL | 0 | 0 | 0 | 12 |
| ZH-013 | FULL | FULL | 0 | 0 | 0 | 14 |
| ZH-019 | FULL | FULL | 0 | 0 | 0 | 29 |

## Observations

- EN-016 recovered Apple's Q2 2026 operating cash flow fact, but the main generated answer was mostly reduced to insufficient-evidence language before the verified fact was appended.
- EN-019 retrieved both Tesla Q2 2025 and NVIDIA Q1 FY2027 revenue facts, but the generated report over-expanded into unrelated strategy, AI technology, infrastructure, and competitive-advantage sections.
- ZH-008 recovered NVIDIA Q1 FY2027 Data Center revenue, but the generated body rejected core numeric statements and relied on an appended verified fact.
- ZH-013 recovered Apple Q2 2026 revenue, net income, and operating cash flow, but the main generated body again rejected the requested numeric summary before deterministic completion.
- ZH-019 recovered both companies' required revenue facts. Its generated body was overlong and the complete report still failed the post-flight numeric grounding check.
- The large post-flight count includes the complete API report, which contains the answer plus the evidence-analysis appendix. The next offline investigation must separate user claims from quoted evidence and ensure deterministic required facts are integrated before final sanitation; the gate must not simply be relaxed.

## Timing and cost

```text
LATENCY_P50_MS: 14044.59
LATENCY_MAX_MS: 42423.69
INPUT_TOKENS: 36723
OUTPUT_TOKENS: 13176
CACHED_TOKENS: 19072
MAIN_QUERY_COST: 0.010610466
EVALUATOR_CALLS: 0
EVALUATOR_COST: $0
```

## Runtime restoration

```text
ALLOW_REAL_PROVIDER: false
frontend: healthy
backend: healthy
agent-worker: healthy
postgres: healthy
redis: healthy
chromadb: healthy
/api/v1/health: 200
/api/v1/ready: 200
AUTOMATIC_RETRY: NO
```

## Decision

```text
THIRD_5Q_GATE: FAIL
READY_FOR_NEXT_REAL_PROVIDER_STAGE: NO
NEXT_ACTION: CONVERT_UNSUPPORTED_NUMERIC_AND_SCOPE_FAILURES_TO_OFFLINE_REGRESSIONS
```

