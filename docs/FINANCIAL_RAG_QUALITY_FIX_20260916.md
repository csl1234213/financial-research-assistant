# Financial RAG answer quality fix — 2026-09-16

## Scope

This change addresses the four findings from the 100-question semantic review:

- 33 `INCORRECT` and 1 `FAILED` answers caused by insufficient production
  context and weak unsupported-evidence handling;
- citations that were structurally valid but not bound to a claim;
- English/Chinese follow-up drift caused by losing the previous company scope.

No new DeepSeek requests were made for this fix. Existing live answers remain
historical evidence and are not regraded as newly generated model output.

## Production changes

1. Retrieval context is now scope-aware: fact/comparison/risk requests receive
   a bounded wider context, while summary/analysis requests retain headline,
   statement and cash-flow coverage.
2. Hybrid lexical probes cover natural phrasing (`margins`,
   `service-related`, risk/forward-looking language and table labels) without
   turning uncertain metadata into a hard filter.
3. Follow-up turns inherit the latest company from conversation history before
   planning and retrieval, preventing Tesla/Apple/NVIDIA context drift.
4. API citations are reduced to evidence explicitly bound to the sanitized
   answer. Unused retrieved chunks remain diagnostics, not claim citations.
5. No-evidence responses are localized for Chinese requests and remain an
   explicit insufficiency result rather than a malformed empty answer.

## Verification

- Retrieval, grounding and evaluation regression tests: **428 passed, 2 skipped**
- Ruff: **PASS**
- Python compile check: **PASS**
- Docker backend/agent-worker rebuilt without volume deletion; all six logical
  services healthy
- `GET /api/v1/health`: **200**
- `GET /api/v1/ready`: **200**
- No real Provider calls made by this fix (`ALLOW_REAL_PROVIDER=false`).

The historical 100-question semantic counts must be regenerated after a
deliberately approved Provider run; they are not silently rewritten by this
offline change.
