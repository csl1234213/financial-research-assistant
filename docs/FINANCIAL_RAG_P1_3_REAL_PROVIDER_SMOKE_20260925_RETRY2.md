# P1.3 Real Provider Smoke — retry 2 (2026-09-25)

## Result

`SMOKE_STATUS: FAIL`

The fixed ten-question selection was executed once with the production HTTP
path and with the backend grounding audit path enabled. No evaluator API and
no 100Q benchmark were run.

| Gate | Result |
|---|---:|
| Real provider calls | 9 |
| HTTP success | 10/10 |
| Application success | 10/10 |
| Empty output / fallback / provider error | 0 / 0 / 0 |
| Correct / Partial / Incorrect / Failed | 3 / 6 / 1 / 0 |
| EN-007 | CORRECT |
| ZH-044 | CORRECT; no citations |
| Tesla period case (EN-002) | CORRECT |
| Evidence Utilization FULL / PARTIAL / FAILED | 3 / 6 / 1 |
| Over-sanitization | 0 |
| Final unsupported numeric claims | 57 |
| Wrong-company / wrong-period counters | 57 / 57 |

The smoke gate therefore does not pass. `READY_FOR_FINAL_100Q_BENCHMARK: NO`.
The wrong-company/wrong-period values above are the harness's conservative
unsupported-claim counters; they are not a claim that 57 independently
reviewed semantic errors were proven.

## Cost and usage

- Input tokens: 162,476
- Output tokens: 27,044
- Cached tokens: 160,768
- Main query cost: `$0.033929808`
- Evaluator calls/cost: `0 / $0`
- Total smoke cost: `$0.033929808`

## Important observations

- EN-007 retained the Q1 FY2027 revenue and Data Center facts, but the final
  answer also contained many additional numeric claims that the current
  deterministic audit marked unsupported.
- ZH-044 returned a citation-free direct explanation, as required; the generic
  numeric post-check still counted example numbers in that explanation as
  unsupported, so the direct-chat exemption is not fully represented by the
  aggregate gate.
- EN-033 returned an insufficient-evidence answer with no citations, but the
  current smoke classifier marked it `INCORRECT`/`FAILED` for Evidence
  Utilization. This requires offline classifier/policy repair before another
  real smoke.

## Safety closure

- `ALLOW_REAL_PROVIDER=false` restored for backend and worker.
- `P1_3_SMOKE_AUDIT_PATH` restored to empty/default.
- `/api/v1/health`: 200.
- `/api/v1/ready`: 200.
- All six Docker services healthy.
- Secret log scan: no configured secret names, bearer headers, or JWT matches.

Artifacts:

- `evaluation/results/p1_3_real_provider_smoke_20260925_retry2/selection.json`
- `evaluation/results/p1_3_real_provider_smoke_20260925_retry2/smoke_results.json`
- `evaluation/results/p1_3_real_provider_smoke_20260925_retry2/summary.json`
- `evaluation/results/p1_3_real_provider_smoke_20260925_retry2/raw_grounding_audit.jsonl`

No commit or push was performed.
