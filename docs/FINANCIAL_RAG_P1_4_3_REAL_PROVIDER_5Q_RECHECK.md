# P1.4.3 Real Provider 5Q Recheck

Date: 2026-09-15  
Scope: the fixed five questions `ZH-013`, `EN-016`, `EN-019`, `ZH-019`, and `ZH-008`.

## Runtime gate

```text
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
EVALUATOR_CALLS: 0
MAIN_QUERY_COST: $0.013500330 (reported usage)
```

The provider was enabled only for this one run and was restored to
`ALLOW_REAL_PROVIDER=false` immediately afterwards.  No retry or replacement
request was issued.

## Per-question result

| ID | Coverage | Evidence utilization | Result |
|---|---|---|---|
| ZH-013 | FULL | FULL | PASS |
| EN-016 | FULL | FULL | PASS |
| EN-019 | PARTIAL | PARTIAL | BLOCKED by Tesla period binding |
| ZH-019 | PARTIAL | PARTIAL | BLOCKED by Tesla period binding |
| ZH-008 | FULL | FULL | PASS |

```text
CORRECT: 3/5
PARTIAL: 2/5
INCORRECT: 0/5
FAILED: 0/5
WRONG_COMPANY: 0
WRONG_PERIOD: 0
```

## Failure diagnosis

The two comparison questions reached the production path with both Tesla and
NVIDIA evidence, but the tenant-scoped Tesla duplicate carried the sentinel
reporting period `Unknown`.  The required-fact planner counted that sentinel
as a reporting period and produced `tesla:revenue:Unknown`, so it conservatively
declined to claim a same-period comparison.  The public filing evidence does
contain Tesla `Q2_2025` revenue; the next offline regression must ignore
`Unknown`/`Undated` sentinels when selecting a reporting period and then rerun
the complete offline gate before another live smoke is authorized.

This is a production mixed-scope metadata issue, not a Provider error or a
missing financial-report value.

## Service state after run

```text
frontend: healthy
backend: healthy
agent-worker: healthy
postgres: healthy
redis: healthy
chromadb: healthy
/api/v1/health: 200
/api/v1/ready: 200
ALLOW_REAL_PROVIDER: false
```

No secret, token, password, API key, or Authorization header was written to
this report.  No volume was deleted and no commit or push was performed.

## Decision

```text
P1.4.3_STATUS: FAIL
READY_FOR_NEXT_REAL_PROVIDER_RUN: NO
```

Per the smoke protocol, stop here.  Convert the `Unknown` period selection to
an offline regression, repair it offline, and rerun the full offline release
gate before requesting another live 5Q smoke.

## Offline repair follow-up (2026-09-15)

The period selector now treats `Unknown`, `Undated`, and equivalent sentinel
values as missing metadata.  A mixed-scope regression fixture (tenant Tesla
duplicate plus public Tesla Q2 2025 filing) now resolves to:

```text
tesla: Q2_2025
nvidia: Q1_FY2027
```

The rebuilt Docker backend was checked against the real Chroma mixed-scope
retrieval path (`tenant_id=1`, public evidence included): 8 candidates were
retrieved, 5 passed semantic gating, and the required-fact plan selected the
two periods above.  No provider call was made during this repair.

```text
OFFLINE_REPAIR_STATUS: PASS
OFFLINE_PROVIDER_CALLS: 0
BACKEND_OFFLINE_TESTS: 107 passed
FRONTEND_TESTS: 31 passed
FRONTEND_BUILD: PASS
RUFF: PASS
DIFF_CHECK: PASS
DOCKER: six services healthy
/api/v1/health: 200
/api/v1/ready: 200
ALLOW_REAL_PROVIDER: false
READY_FOR_NEXT_REAL_PROVIDER_RUN: YES
```

## Chinese comparison retrieval repair (2026-09-15)

The first offline repair fixed the period sentinel, but the next 5Q run showed
that the Chinese comparison query could still select an unheaded Tesla page-31
fragment.  That fragment contains the revenue row without its quarter-column
header, so the parser could not prove that `22,496` belonged to `Q2_2025`.

The Chinese comparison enrichment now appends the same column-aware table
terms as the English path: `financial summary quarterly total revenues`.  In
the rebuilt Docker mixed-scope retrieval check, the exact Chinese question
now resolves to Tesla `Q2_2025` and NVIDIA `Q1_FY2027`, and deterministic
completion preserves `22.496 billion` and `81.615 billion`.

```text
CHINESE_COMPARISON_REPAIR: PASS
OFFLINE_PROVIDER_CALLS: 0
OFFLINE_TESTS: 108 passed
RUFF: PASS
DIFF_CHECK: PASS
READY_FOR_NEXT_REAL_PROVIDER_RUN: YES
```
