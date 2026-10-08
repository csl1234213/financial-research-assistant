# Financial RAG Assistant — P1.4.1 Real Provider Fact Ledger Recheck

Date: 2026-09-15  
Scope: exactly five fixed production HTTP requests (`ZH-013`, `EN-016`, `EN-019`, `ZH-019`, `ZH-008`); no evaluator calls, no retries, no 10Q/100Q execution.

## Result

```text
FACT_LEDGER_RECHECK_STATUS: FAIL
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
CORRECT: 0/5
PARTIAL: 5/5
INCORRECT: 0
FAILED: 0
REQUIRED_FACT_FULL: 0/5
EVIDENCE_UTILIZATION_FULL: 0/5
READY_FOR_FINAL_10Q_RELEASE_SMOKE: NO
```

All five requests completed once with HTTP 200 and application success. The
failure is an environment/deployment gate, not a timeout or Provider error:
the running `financial-rag-assistant-runtime:8.2.0` image did not contain the
P1.4 evidence-first implementation. A non-secret inspection of the live image
found the old smoke capture hook but no `fact_ledger` / `required_fact_plan`
runtime fields. Consequently the production response did not expose a
verifiable Fact Ledger, Required Fact Plan, Fact-ID binding, or deterministic
completion for any of the five cases. The source tree does contain the P1.4
implementation; the image must be rebuilt before a future recheck is requested.

Per the runbook, the five requests were not repeated or replaced after this
observation.

## Per-question outcome

| ID | HTTP / app | Fact Ledger | Required facts | Evidence utilization | Result |
|---|---:|---:|---:|---:|---|
| ZH-013 | 200 / PASS | 0 facts | PARTIAL | PARTIAL | Legacy image; no ledger completion |
| EN-016 | 200 / PASS | 0 facts | PARTIAL | PARTIAL | Legacy image; metric binding not observable |
| EN-019 | 200 / PASS | 0 facts | PARTIAL | PARTIAL | Legacy image; company partition not observable |
| ZH-019 | 200 / PASS | 0 facts | PARTIAL | PARTIAL | Legacy image; company/period binding not observable |
| ZH-008 | 200 / PASS | 0 facts | PARTIAL | PARTIAL | Legacy image; supported-fact retention not observable |

The raw model answer, old grounding result, final API report, retrieved
evidence, and empty ledger/planning observation are retained in each artifact:

- [ZH-013.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck/ZH-013.json)
- [EN-016.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck/EN-016.json)
- [EN-019.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck/EN-019.json)
- [ZH-019.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck/ZH-019.json)
- [ZH-008.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck/ZH-008.json)
- [summary.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck/summary.json)
- [raw_grounding_audit.jsonl](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck/raw_grounding_audit.jsonl)

## Grounding observations

These are observations from the legacy grounding hook only and are not a
passing P1.4 Fact Ledger gate:

```text
SUPPORTED_CLAIMS: 11
SUPPORTED_CLAIMS_KEPT: 11
DERIVABLE_CLAIMS: 2
UNSUPPORTED_CLAIMS: 8
UNSUPPORTED_CLAIMS_REJECTED: 8
GROUNDING_KEEP_RATE: 1.0
GROUNDING_REJECTION_RATE: 1.0
FACT_LEDGER_FACTS: 0
DETERMINISTIC_COMPLETIONS: 0
```

`WRONG_COMPANY`, `WRONG_PERIOD`, and `WRONG_METRIC` are **not observable** for
this run because the required Fact-ID bindings were absent; they must not be
interpreted as zero.

## Cost and latency

```text
INPUT_TOKENS: 7399
OUTPUT_TOKENS: 9156
CACHED_TOKENS: 6272
MAIN_QUERY_COST: $0.011362932
EVALUATOR_COST: $0
LATENCY_P50: 10439.54 ms
LATENCY_MAX: 17700.74 ms
```

## Runtime guard and safety

After the five requests, backend and agent-worker were recreated without
volume changes. The live container was verified as:

```text
ALLOW_REAL_PROVIDER: false
P1_3_SMOKE_AUDIT_PATH: empty
/api/v1/health: 200
/api/v1/ready: 200
```

No password, token, API key, or Authorization header is present in the report
or result artifacts. No commit, push, volume deletion, database reset, or
additional Provider request was performed.

## Required next step

1. Rebuild the backend/worker image from the current source tree so the P1.4
   Fact Ledger and Required Fact Plan code is present in `/app`.
2. Verify the rebuilt image non-secretly before requesting another five-question
   run.
3. Only then request a new one-shot P1.4.1 recheck; do not reuse this failed
   run as a release gate.

```text
ALLOW_REAL_PROVIDER_RESTORED: YES
READY_FOR_FINAL_10Q_RELEASE_SMOKE: NO
```
