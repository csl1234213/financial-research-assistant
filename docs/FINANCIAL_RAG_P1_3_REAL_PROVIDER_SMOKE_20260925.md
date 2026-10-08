# P1.3 Real Provider Smoke — 2026-09-25

## Scope

The frozen `evaluation/datasets/p1_3_real_smoke_10.json` selection was used without changing questions or expected criteria. A single sequential HTTP run was started with `ALLOW_REAL_PROVIDER=true`; no evaluator API, 100Q benchmark, retry, or replacement question was run.

## Result

`SMOKE_STATUS: FAIL`

The ten HTTP calls reached the smoke loop, but post-processing stopped before writing `smoke_results.json` or `summary.json`. The failure was:

`Missing raw grounding capture for EN-033`

`EN-033` is the fixed insufficient-evidence case. Its production path can return a deterministic refusal before the grounding-audit hook, so the smoke harness incorrectly treated a valid no-audit response as a fatal artifact error. This is a harness-contract failure, not evidence that the model answer passed the smoke gates.

Observed artifacts:

- `evaluation/results/p1_3_real_provider_smoke_20260925/selection.json` (10 frozen cases)
- `evaluation/results/p1_3_real_provider_smoke_20260925/raw_grounding_audit.jsonl` (9 audit records; 599,860 bytes)
- `raw_grounding_audit.jsonl` SHA-256: `4f30d37104284be6d23da2d44056683ab0e3d70a5c3b3c97685b8509c596716f`

The missing record means the run cannot honestly report complete HTTP/application success, provider-call count, token usage, or cost from persisted evidence. Those fields are therefore `UNKNOWN`, not inferred.

## Safety closure

- `ALLOW_REAL_PROVIDER` was restored to `false` in backend and worker.
- `P1_3_SMOKE_AUDIT_PATH` was cleared.
- Six services remained healthy after restoration.
- `/api/v1/health`: `200`
- `/api/v1/ready`: `200`
- Recent backend log scan found no secret, JWT, or Authorization-header leakage.
- No 100Q run and no evaluator call was made.

## Offline follow-up

`evaluation/p1_3_real_provider_smoke.py` now accepts a non-empty, citation-free deterministic response without an audit record only when the response reports zero provider calls; provider-backed responses still fail closed when their audit record is missing. The change was linted and compiled, but this run was not repeated in accordance with the no-retry rule.

## Gate decision

`READY_FOR_FINAL_100Q_BENCHMARK: NO`

The remaining 9Q smoke must not be run until a separately authorized, one-shot rerun is requested after the offline harness fix.
