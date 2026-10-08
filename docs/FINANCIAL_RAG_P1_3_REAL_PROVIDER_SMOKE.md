# Financial RAG P1.3 — Real Provider Smoke

## Result

`SMOKE_STATUS: FAIL`

The frozen ten-case selection was created before requests and was not changed. The first main request (EN-007) did not return within the 180-second HTTP timeout. The smoke was stopped immediately; no automatic retry, replacement question, parameter tuning, 100Q benchmark, commit, or push was performed.

The failure occurred after the real HTTP request was started and before an API usage envelope was received. Therefore token and cost values are reported as unavailable rather than guessed. No raw answer or citation envelope was available for adjudication.

## Fixed selection

`evaluation/datasets/p1_3_real_smoke_10.json` contains exactly ten frozen cases:

- English: EN-007 (NVIDIA Q1 FY2027), EN-002 (Tesla Q2 period/numeric), EN-019 (multi-company).
- Chinese: ZH-044 (direct concept, no citations), ZH-007 (NVIDIA table), ZH-013 (Apple table).
- Additional coverage: EN-016 (cash-flow table), ZH-008 (NVIDIA Data Center table), EN-033 (insufficient evidence), ZH-019 (multi-company/derived comparison).

## Smoke metrics

```text
SMOKE_STATUS: FAIL
REAL_PROVIDER_CALLS: UNKNOWN_TIMEOUT (one main request attempted; usage envelope not received)
HTTP_SUCCESS: 0/10 completed
APPLICATION_SUCCESS: 0/10 completed
CORRECT: 0
PARTIAL: 0
INCORRECT: 0
FAILED: 1 (remaining 9 not run)
EN_007: NOT_COMPLETED (HTTP read timeout)
ZH_044: NOT_RUN
TESLA_PERIOD: NOT_RUN
RAW_CLAIMS: NOT_AVAILABLE_TIMEOUT
UNSUPPORTED_RAW_CLAIMS: NOT_AVAILABLE_TIMEOUT
REMOVED_CLAIMS: NOT_AVAILABLE_TIMEOUT
REWRITTEN_CLAIMS: NOT_AVAILABLE_TIMEOUT
FINAL_UNSUPPORTED_NUMERIC_CLAIMS: NOT_AVAILABLE_TIMEOUT
WRONG_COMPANY_CLAIMS: NOT_AVAILABLE_TIMEOUT
WRONG_PERIOD_CLAIMS: NOT_AVAILABLE_TIMEOUT
EVIDENCE_UTILIZATION_FULL: 0
EVIDENCE_UTILIZATION_PARTIAL: 0
EVIDENCE_UTILIZATION_FAILED: 1
OVER_SANITIZATION_COUNT: NOT_AVAILABLE_TIMEOUT
INPUT_TOKENS: NOT_AVAILABLE_TIMEOUT
OUTPUT_TOKENS: NOT_AVAILABLE_TIMEOUT
CACHED_TOKENS: NOT_AVAILABLE_TIMEOUT
MAIN_QUERY_COST: UNKNOWN_TIMEOUT
EVALUATOR_COST: $0 (no evaluator/provider call)
TOTAL_SMOKE_COST: UNKNOWN_TIMEOUT
READY_FOR_FINAL_100Q_BENCHMARK: NO
```

The request path was configured to capture raw answer/grounding audit data in the backend's temporary path (`/tmp/p1_3_real_provider_smoke.jsonl`). Since the first request timed out before a response envelope, no exportable raw-answer record was produced. No token, password, API key, or authorization header was written to the repository artifacts.

## Runtime recovery

- `ALLOW_REAL_PROVIDER` restored to `false` in the backend container.
- `P1_3_SMOKE_AUDIT_PATH` restored to empty/default.
- Docker Compose services are healthy after recovery.
- `GET /api/v1/health`: 200.
- `GET /api/v1/ready`: 200.
- Existing volumes were preserved; no `down -v`, prune, or data deletion was used.

## Artifacts

- Frozen selection: `evaluation/datasets/p1_3_real_smoke_10.json`
- Safe summary: `evaluation/results/p1_3_real_provider_smoke/summary.json`
- Failure record: `evaluation/results/p1_3_real_provider_smoke/failure.json`
- No `smoke_results.json` or raw answer export exists because the first request timed out.

## Validation

- `ruff check evaluation/p1_3_real_provider_smoke.py core/core_engine.py`: PASS
- `docker compose config -q`: PASS
- `git diff --check`: PASS
- Docker health and health/readiness endpoints: PASS after recovery

## Gate decision

`READY_FOR_FINAL_100Q_BENCHMARK: NO`.

Per the smoke protocol, this run is stopped. The timeout must first be converted into an offline regression, reproduced and fixed, followed by a complete offline release gate before a future smoke request. No second smoke was run in this task.
