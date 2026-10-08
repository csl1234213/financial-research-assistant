# P1.3 Real Provider Smoke — 2026-09-25 rerun

## Status

**FAIL / NOT EVALUABLE**

The frozen ten-question selection was used once. The run reached the audit
export step after the sequential chat requests, but the backend container had
`P1_3_SMOKE_AUDIT_PATH` empty. Consequently `/tmp/p1_3_real_provider_smoke.jsonl`
was not created and the harness stopped with:

```text
RuntimeError: Smoke audit capture was not produced by backend
```

Because the per-question rows were held in memory and were not written before
audit export, this run cannot establish HTTP/application success, grounding
gates, answer quality, Evidence Utilization, token usage, or cost. No PASS
claim is made and the smoke was not retried.

## Safety closure

- `ALLOW_REAL_PROVIDER=false` restored in backend and worker.
- `P1_3_SMOKE_AUDIT_PATH` restored to empty/default.
- `/api/v1/health`: 200.
- `/api/v1/ready`: 200.
- All six compose services healthy.
- Secret log scan: no matches for configured secret names, JWT, or bearer
  headers.
- No evaluator API call and no 100Q benchmark was run.

## Follow-up requirement

Before a future smoke attempt, inject the audit path into the container
environment (for example `/tmp/p1_3_real_provider_smoke.jsonl`) and preserve
the existing single-run/no-retry policy. This is a harness/runtime
configuration correction, not evidence that the ten-question smoke passed.

## Artifacts

The fixed selection snapshot is preserved at:

`evaluation/results/p1_3_real_provider_smoke_20260925_canary/selection.json`

No `smoke_results.json`, `summary.json`, or raw audit artifact was produced.
