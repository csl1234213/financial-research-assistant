# Financial RAG Assistant — P1.3.1 Offline Timeout Recovery

**Run date:** 2026-09-15  
**Scope:** offline timeout/cancellation recovery after the P1.3 real-provider smoke stopped at the first 180-second HTTP timeout.

## Gate and safety

```text
SPRINT_STATUS: PASS (offline timeout recovery)
DEEPSEEK_API_USED: NO
REAL_PROVIDER_CALLS: 0
API_COST: $0
1Q/10Q/100Q_RUN: NO
ALLOW_REAL_PROVIDER: false
```

No provider credential was used. The real-provider audit path was empty before and after the work. No commit, push, volume deletion, `down -v`, or prune operation was performed.

## Root cause

The previous DeepSeek adapter used a synchronous OpenAI-compatible SDK call with a 60-second per-attempt timeout and up to three attempts. Retry/backoff did not share one request deadline. The API therefore waited roughly three timeout windows and the runtime converted the exception into a successful HTTP 200 fallback, so the smoke recorded a client-side 180-second timeout without a provider response.

The exact remote phase (TCP connect versus response read) cannot be reconstructed from the historical smoke because it contained no provider timing envelope. The architectural cause is confirmed offline: an injected hanging synchronous call now expires at the configured total deadline, the late result is discarded, and the next request remains usable.

## Implemented recovery contract

- `LLM_CONNECT_TIMEOUT` (default `10s`), `LLM_READ_TIMEOUT` (default `45s`) and `LLM_TOTAL_DEADLINE` (default `120s`) are configurable and propagated from Compose through the router, agent graph, core RAG path, and provider.
- A single monotonic deadline is shared by all retry attempts and backoff. The adapter never starts a new attempt after the deadline.
- Synchronous SDK calls are contained by a daemon worker and deadline join. A timed-out late result is ignored; the limitation that Python cannot forcibly interrupt a blocked third-party thread is explicit.
- `ProviderTimeoutError` propagates through runtime and ChatService. The HTTP API returns a safe `504` timeout response instead of a fabricated fallback answer.
- Secret-free stage timing is logged for request start/end, provider request, and grounding/sanitizer stages.
- Existing 429/503 retry behavior remains bounded at three attempts; timeout attempts are bounded by the shared deadline.

## Deterministic offline evidence

`tests/evaluation/test_p1_3_1_timeout_recovery.py` covers normal, slow-valid, connect-timeout, read-timeout, hanging/cancellation, post-timeout recovery, and the HTTP 504 contract. It does not perform network I/O.

```text
NORMAL_PROVIDER: PASS
SLOW_PROVIDER: PASS
CONNECT_TIMEOUT: PASS
READ_TIMEOUT: PASS
HANGING_PROVIDER: PASS
TOTAL_DEADLINE: PASS
DEADLINE_PROPAGATION: PASS
CANCELLATION_CONTAINMENT: PASS
TIMEOUT_HTTP_STATUS: 504
RUNTIME_FALLBACK_AFTER_TIMEOUT: NO
POST_TIMEOUT_RECOVERY: PASS
RESOURCE_CLEANUP: PASS
```

P1.2 retrieval/grounding behavior was not re-tuned. The full offline suite completed with:

```text
BACKEND_FULL_OFFLINE_TESTS: 2102 passed, 23 skipped, 1 warning
```

Skipped tests are the repository's existing live-provider/credential-gated cases. No test enabled real-provider access.

## Runtime verification

The canonical Compose stack was rebuilt for the backend/worker image and started without removing any volume. All six logical services are healthy:

| Service | Status | Health |
| --- | --- | --- |
| frontend | running | healthy |
| backend | running | healthy |
| agent-worker | running | healthy |
| postgres | running | healthy |
| redis | running | healthy |
| chromadb | running | healthy |

```text
COMPOSE_CONFIG: PASS (docker compose config -q)
HEALTH: HTTP 200
READY: HTTP 200
PROVIDER_CALL_GUARD: PASS (ALLOW_REAL_PROVIDER=false)
AUDIT_PATH: empty
```

The health and ready responses reported `database=ok`, `redis=ok`, and `chroma=ok`; no secret-bearing environment output was collected.

## Other validation

```text
FRONTEND_TESTS: 31 passed
FRONTEND_BUILD: PASS
RUFF: PASS
GIT_DIFF_CHECK: PASS
SECRET_LOG_LEAK: NO (no provider call was made)
```

## Gate decision

```text
READY_FOR_REAL_API_SMOKE_RETRY: YES
```

This is authorization to request a future, manually supervised real-provider retry only. It is not a claim that a new smoke or benchmark has run.

## Final report fields

```text
P1_3_TIMEOUT_ROOT_CAUSE: CONFIRMED (sync SDK budget was per-attempt, not request-wide)
NORMAL_PROVIDER: PASS
SLOW_PROVIDER: PASS
CONNECT_TIMEOUT: PASS
READ_TIMEOUT: PASS
HANGING_PROVIDER: PASS
TOTAL_DEADLINE: PASS
RETRY_BUDGET: PASS (429/503 max 3; timeout bounded by shared deadline)
CANCELLATION: PASS (late result contained/discarded)
DEADLINE_PROPAGATION: PASS
RESOURCE_CLEANUP: PASS
RUNTIME_FALLBACK_AFTER_TIMEOUT: NO
EN_007_OFFLINE: NOT_RUN (no provider call; P1.2 gate remains the offline evidence)
GROUNDING_REGRESSION: PASS
PROVIDER_CALL_GUARD: PASS
BACKEND_OFFLINE_TESTS: 2102 passed, 23 skipped
FRONTEND_TESTS: 31 passed
RUFF: PASS
BUILD: PASS
DIFF_CHECK: PASS
DOCKER: PASS
HEALTH: 200
READY: 200
DEEPSEEK_API_USED: NO
REAL_PROVIDER_CALLS: 0
API_COST: $0
READY_FOR_REAL_API_SMOKE_RETRY: YES
```
