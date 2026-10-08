# Financial RAG Assistant — 100Q Real Provider Run

Date: 2026-09-16

## Execution

The frozen EN50/ZH50 dataset was executed in a new isolated evaluation tenant.
The five required business Smoke requests were run separately and the 100
main requests were then executed exactly once each. Historical result folders
were not overwritten.

```text
MAIN_REQUESTS: 100
UNIQUE_REQUEST_IDS: 100
ENGLISH: 50
CHINESE: 50
HTTP_SUCCESS: 100/100
APPLICATION_SUCCESS: 100/100
BUSINESS_ERROR: 0
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
```

All main responses were HTTP 200 with a non-empty report and no harness-level
error. This is a runtime/execution gate, not a claim of answer accuracy.

Structural citation validation found 341 citations across the 100 responses;
all 341 matched a known source/chunk/page in the frozen reference corpus.
Thirty-four responses had no citations, including the eight direct-chat
concept questions where citations are not expected.

## Usage and cost

```text
MAIN_INPUT_TOKENS: 301443
MAIN_OUTPUT_TOKENS: 225854
MAIN_CACHED_TOKENS: 274296
MAIN_QUERY_COST: $0.280814676

SMOKE_INPUT_AND_OUTPUT_COST: $0.013160148
TOTAL_PROVIDER_COST: $0.293974824

MAIN_LATENCY_P50_MS: 10507.89
MAIN_LATENCY_MAX_MS: 43123.66
```

Usage values are the provider-reported values captured by the harness. No
evaluator calls were made, so there is no evaluator cost in this report.

## Semantic quality status

```text
SEMANTIC_REVIEW: NOT_RUN
ANSWER_ACCURACY: NOT_CLAIMED
CITATION_ENTAILMENT: NOT_CLAIMED
```

The raw answers, citations, usage, and HTTP envelopes are available for a
separate human or evaluator review under:

`evaluation/results/formal_20260916/`

The directory contains the frozen dataset, reference manifest, Smoke results,
and 100 unique main-request records. No credentials or Authorization headers
were copied into the result directory.

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

No Docker volumes, database data, or historical result artifacts were deleted.

## Gate

```text
100Q_RUNTIME_GATE: PASS
100Q_ANSWER_QUALITY_GATE: NOT_EVALUATED
FINAL_STATUS: PARTIAL
```

`PARTIAL` is intentional: runtime completion passed, while semantic grading
was not run to avoid an additional 100 paid evaluator calls without explicit
authorization.
