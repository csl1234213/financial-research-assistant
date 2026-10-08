# P1.3 Real Provider Smoke — retry 4 (2026-09-25)

## Result

`SMOKE_STATUS: PASS`

The frozen ten-question set ran once through the production HTTP path with
grounding audit capture enabled. No evaluator API and no 100Q benchmark were
run.

| Gate | Result |
|---|---:|
| Real provider calls | 9 |
| HTTP success | 10/10 |
| Application success | 10/10 |
| Empty output / fallback / provider error | 0 / 0 / 0 |
| Correct / Partial / Incorrect / Failed | 4 / 6 / 0 / 0 |
| EN-007 | CORRECT |
| ZH-044 | CORRECT; no citations |
| Tesla period case (EN-002) | CORRECT |
| Evidence Utilization FULL / PARTIAL / FAILED | 4 / 6 / 0 |
| Final unsupported numeric claims | 0 |
| Critical wrong-company claims | 0 |
| Critical wrong-period claims | 0 |
| Over-sanitization | 0 |

`READY_FOR_FINAL_100Q_BENCHMARK: YES`.

## Cost and usage

- Input tokens: 162,451
- Output tokens: 16,142
- Cached tokens: 140,032
- Main query cost: `$0.026936292`
- Evaluator calls/cost: `0 / $0`
- Total smoke cost: `$0.026936292`

## TypeSafe-style evidence audit

The review keeps typed evidence judgments separate from final answer claims:
rejected candidate citations do not become wrong-period errors when they are
not present in the final grounded answer. Direct concept explanations remain
outside the filing-citation gate, while numeric financial claims remain subject
to deterministic normalization and scope checks.

The implementation follows the local typed citation contract in
`core/typesafe_citation.py`; no external TypeSafe API call was made during the
smoke.

## Safety closure

- `ALLOW_REAL_PROVIDER=false` restored for backend and worker.
- `P1_3_SMOKE_AUDIT_PATH` restored to empty/default.
- `/api/v1/health`: 200.
- `/api/v1/ready`: 200.
- All six Docker services healthy.
- Secret log scan: no configured secret names, bearer headers, or JWT matches.

Artifacts:

- `evaluation/results/p1_3_real_provider_smoke_20260925_retry4/selection.json`
- `evaluation/results/p1_3_real_provider_smoke_20260925_retry4/smoke_results.json`
- `evaluation/results/p1_3_real_provider_smoke_20260925_retry4/summary.json`
- `evaluation/results/p1_3_real_provider_smoke_20260925_retry4/raw_grounding_audit.jsonl`

Offline verification after the fix: 50 targeted tests passed; Ruff and
`git diff --check` passed. No commit or push was performed.
