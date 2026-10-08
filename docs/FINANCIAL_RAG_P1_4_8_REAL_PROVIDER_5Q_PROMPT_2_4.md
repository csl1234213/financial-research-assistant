# Financial RAG P1.4.8 — Prompt 2.4.0 Real 5Q Verification

Date: 2026-09-16

## Scope

This was one fixed five-question run using Prompt `2.4.0` and the existing
semantic recheck set: `ZH-013`, `EN-016`, `EN-019`, `ZH-019`, and `ZH-008`.
Each question made one request. No retry, evaluator request, question
replacement, or 100Q run was performed.

## Result

```text
TEST_STATUS: FAIL
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
CORRECT: 1/5
PARTIAL: 4/5
INCORRECT: 0
FAILED: 0
REQUIRED_FACT_FULL: 2/5
EVIDENCE_UTILIZATION_FULL: 2/5
WRONG_COMPANY: 2
WRONG_PERIOD: 0
UNSUPPORTED_NUMERIC: 8
OVER_SANITIZATION: 1
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
EVALUATOR_CALLS: 0
EVALUATOR_COST: $0
```

| ID | Grade | Required facts | Evidence utilization | Wrong company | Wrong period | Unsupported numeric | Over-sanitization |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| EN-016 | PARTIAL | PARTIAL | PARTIAL | 0 | 0 | 2 | 0 |
| EN-019 | PARTIAL | PARTIAL | PARTIAL | 1 | 0 | 1 | 0 |
| ZH-008 | CORRECT | FULL | FULL | 0 | 0 | 0 | 0 |
| ZH-013 | PARTIAL | PARTIAL | PARTIAL | 0 | 0 | 3 | 1 |
| ZH-019 | PARTIAL | FULL | FULL | 1 | 0 | 2 | 0 |

Raw responses, final responses, citations, usage, and audit records are under
`evaluation/results/p1_4_8_real_provider_5q_20260916/`.

## Cost and latency

```text
INPUT_TOKENS: 37411
OUTPUT_TOKENS: 11364
CACHED_TOKENS: 15360
MAIN_QUERY_COST: $0.020344260
TOTAL_SMOKE_COST: $0.020344260
LATENCY_P50_MS: 12207.64
LATENCY_MAX_MS: 26890.96
EVALUATOR_CALLS: 0
EVALUATOR_COST: $0
```

## Interpretation

Prompt `2.4.0` was present in both backend and worker, and the offline prompt
contract passed for all five questions. The prompt correctly expresses the
document-specific rules, but it cannot by itself fix retrieval provenance or
post-generation answer composition:

- Duplicate tenant sample documents still appeared beside canonical public
  filings, producing two unexpected-source/company-gate failures.
- The checker still treats valid billion-scale renderings as missing in some
  required-fact cases and scans the complete report wrapper.
- Apple multi-fact Chinese output still retained repeated refusal fragments;
  deterministic completion did not replace the earlier refusal narrative.
- NVIDIA Q1 and Tesla Q2 comparison output still depends on mixed source
  provenance even though period errors remained zero.

This run therefore confirms that the next repair must be source-authority
deduplication plus numeric-aware evaluation and answer composition. It is not
appropriate to keep tuning the Prompt alone or to proceed to another smoke set.

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
PROMPT_2_4_5Q_GATE: FAIL
READY_FOR_REMAINING_5Q: NO
READY_FOR_100Q: NO
NEXT_ACTION: OFFLINE_SOURCE_AUTHORITY_AND_ANSWER_COMPOSITION_REPAIR
```

