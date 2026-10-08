# P1.4.2 Real Provider 5Q Validation

Date: 2026-09-15  
Scope: the fixed five questions `ZH-013`, `EN-016`, `EN-019`, `ZH-019`, and `ZH-008`. No evaluator call, no additional retry, and no 10Q/100Q run.

## Runtime result

The five requests were sent through the production HTTP chat path with the
Provider enabled only for the temporary runner process. PostgreSQL records
five `chat_request` events and five successful agent traces. The runner then
stopped while copying its audit file because the backend container does not
contain the Docker CLI. Therefore the wire-level response capture and raw
grounding audit are not available for this run; they must not be inferred from
the persisted final messages.

```text
REAL_PROVIDER_CALLS: 5
APPLICATION_TRACES: 5/5 success
EMPTY_OUTPUT: 0 (all five persisted assistant messages are non-empty)
RUNTIME_FALLBACK: 0 observed
PROVIDER_ERROR: 0 observed
EVALUATOR_CALLS: 0
TOKENS/COST: UNKNOWN (not persisted by the API)
AUDIT_CAPTURE: INCOMPLETE — runner docker-copy failure
```

## Deterministic answer review

| ID | Result | Persisted answer evidence |
|---|---|---|
| ZH-013 | PARTIAL | Apple revenue `111,184` and net income `29,578` retained; the expected operating-cash-flow anchor was not retained in the final answer. |
| EN-016 | CORRECT | Apple operating cash flow `82,627` retained. |
| EN-019 | CORRECT | Tesla `22,496` and NVIDIA `81.6`/`81,615` retained. |
| ZH-019 | PARTIAL | Both company anchors are present, but the answer also declines a same-period comparison because Tesla period binding remains conservative. |
| ZH-008 | CORRECT | NVIDIA Q1 FY2027 Data Center revenue `75.2 billion` retained. |

```text
CORRECT: 3/5
PARTIAL: 2/5
INCORRECT: 0/5
FAILED: 0/5
```

This is a validation result, not an accuracy benchmark. The two partial cases
remain offline regression candidates. A future retry must first fix the audit
capture path and must be explicitly authorized; this run is not silently
repeated.

## Guard and service state

```text
ALLOW_REAL_PROVIDER: false
/api/v1/health: 200
/api/v1/ready: 200
frontend/backend/agent-worker/postgres/redis/chromadb: healthy
```

No secret, token, password, API key, or Authorization header was written to
this report. No volume was deleted and no commit or push was performed.

## Final decision

```text
P1.4.2_STATUS: PARTIAL
READY_FOR_NEXT_REAL_PROVIDER_RUN: NO
```

## Offline repair verification (2026-09-15)

The two partial cases were repaired without another provider call.  The
previous ZH-013 review used a strict comma-form token check; the persisted
answer already contained the equivalent normalized value `82.627 billion`.
The offline production-path replay now validates that value and the remaining
summary facts against the ledger.

For unqualified summary questions, the required-fact plan now binds to the
document reporting period (Apple `Q2_2026`).  When a chunk contains both a
component row and a total row, completion prefers the explicit authoritative
total row.  For comparison questions, each company is bound to its own filing
period: Tesla `Q2_2025` and NVIDIA `Q1_FY2027`.

```text
OFFLINE_REPAIR_STATUS: PASS
ZH-013_OPERATING_CASH_FLOW: 82.627 billion — PASS
ZH-019_TESLA_Q2_2025_REVENUE: 22.496 billion — PASS
ZH-019_NVIDIA_Q1_FY2027_REVENUE: 81.615 billion — PASS
OFFLINE_PROVIDER_CALLS: 0
ALLOW_REAL_PROVIDER: false
```

The focused offline suite passed (`96 passed`), Ruff passed, `git diff
--check` passed, and the six Docker services remained healthy with `/health`
and `/ready` both returning `200`.  No new real-provider run was performed;
the historical live result above remains unchanged and a future live recheck
still requires explicit authorization.
