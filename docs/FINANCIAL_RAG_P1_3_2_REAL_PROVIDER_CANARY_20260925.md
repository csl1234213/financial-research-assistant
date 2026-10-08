# P1.3.2 Real Provider Canary — 2026-09-25

## Scope

This was one explicit, frozen `EN-007` request only:

`Summarize NVIDIA's financial performance in Q1 FY2027.`

The question was loaded from the frozen benchmark dataset and was not changed.
No evaluator API, 5Q, 10Q, or 100Q run was started. The canary used one
authenticated HTTP request, with no harness-level retry or replacement.

## Runtime result

```text
CANARY_STATUS: FAIL
HTTP_STATUS: 599 (client read timeout)
APPLICATION_SUCCESS: false
TOTAL_LATENCY: 45005.79 ms
PROVIDER_FAILURE: HTTP_599
EMPTY_OUTPUT: false
RUNTIME_FALLBACK: false
PROVIDER_ERROR: false
EN_007_GRADE: FAILED
EVIDENCE_UTILIZATION: FAILED
```

The client used `connect=10s`, `read=45s`; the API's configured total deadline
remained 120s. The client timed out before a response containing model output
was available. Therefore raw answer, final answer, citation consistency, and
token/cost usage are `UNKNOWN` rather than inferred. This is not a quality
PASS and is not evidence that Q1 facts were wrong.

Artifact:

`evaluation/results/p1_3_2_real_provider_canary_20260925/summary.json`

The artifact records `real_provider_calls`, token usage, and cost as
`UNKNOWN` because no usage payload arrived. It does not print or store the
auth token or password.

## Safety restoration

After the single attempt:

```text
ALLOW_REAL_PROVIDER: false
P1_3_SMOKE_AUDIT_PATH: empty
backend: healthy
agent-worker: healthy
frontend: healthy
postgres: healthy
redis: healthy
chromadb: healthy
```

No volume was deleted, no database was reinitialized, and no retry was made.

## Classification

This result is a real-provider/runtime timeout regression, not a semantic
answer regression. Before another live attempt, the timeout boundary must be
reproduced offline or the provider/runtime timeout contract must be changed
and covered by tests. The next live run must not be started automatically.

## Explicit retry (same fixed canary)

The user then explicitly authorized one retry under the same fixed scope. The
retry was not automatic and did not change the question, prompt, evaluator, or
timeout settings.

```text
CANARY_STATUS: PASS
HTTP_STATUS: 200
APPLICATION_SUCCESS: true
TOTAL_LATENCY: 23422.62 ms
REAL_PROVIDER_CALLS: 1
EN_007_GRADE: CORRECT
EVIDENCE_UTILIZATION: FULL
FINAL_UNSUPPORTED_NUMERIC_CLAIMS: 0
CRITICAL_WRONG_COMPANY: 0
CRITICAL_WRONG_PERIOD: 0
RAW_CLAIMS: 30
SUPPORTED_RAW_CLAIMS: 5
REMOVED_CLAIMS: 13
REWRITTEN_CLAIMS: 0
INPUT_TOKENS: 20040
OUTPUT_TOKENS: 2789
CACHED_TOKENS: 19840
MAIN_QUERY_COST: $0.00352584
EVALUATOR_CALLS: 0
EVALUATOR_COST: $0
READY_FOR_REMAINING_9Q_SMOKE: YES
```

The raw model output, grounding result, final sanitized answer, and final
citations are stored in:

`evaluation/results/p1_3_2_real_provider_canary_20260925_retry1/`

The sanitizer removed unsupported claims rather than attaching unrelated
citations. After the retry, `ALLOW_REAL_PROVIDER=false` and the audit path was
cleared again; all six services remained healthy and health/ready returned
`200`.
