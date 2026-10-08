# Financial RAG P1.4.9 — Offline Repair

Date: 2026-09-16

## Scope

This repair addresses the failures observed in the P1.4.8 real five-question
run. No new DeepSeek request was made in this sprint and no benchmark
expectations or financial source files were changed.

## Root causes confirmed

1. The same filing was present in both the public corpus and a tenant upload.
   Retrieval deduplication included the document identity, so byte-equivalent
   chunks could reach the prompt under two source names. This was a citation
   provenance problem, not a missing financial fact.
2. The production answer boundary appended verified ledger facts but retained
   repeated provider refusal placeholders. This made supported answers look
   incomplete and created avoidable over-sanitization findings.
3. The semantic recheck compared display strings instead of financial value
   semantics. Values such as `82.627 billion` and `82,627 million` were
   incorrectly counted as missing.

## Changes

- `core/citation_gate.py` now collapses byte-equivalent evidence by company
  and normalized content, preferring `source_authority=public_filing` when
  both public and tenant records exist. A non-duplicate tenant upload remains
  eligible and stored data is not deleted.
- `core/answer_policy.py` removes repeated refusal-only fragments when a
  trusted requested fact is available, while preserving one refusal when no
  supporting fact exists. Explanatory evidence-limit sentences are retained.
- `evaluation/p1_3_5_real_provider_semantic_recheck.py` grades the final
  sanitized answer/final evidence and uses scale-aware numeric equivalence.
  The API audit appendix is no longer mistaken for user-visible claims.

## Verification

- Offline backend suite before the final document-fingerprint assertion: **2224 passed, 23 skipped**.
- Final focused regression suite after that assertion: **31 passed**; the
  full suite remains covered by the preceding run and the added assertion is
  a pure extension of the same gate.
- Focused citation/answer policy suite: **17 passed**.
- Evidence-first/context/grounding suite: **57 passed**.
- Ruff: **PASS**.
- `git diff --check`: **PASS**.
- Docker image `financial-rag-assistant-runtime:8.2.0`: **built**.
- Backend and agent-worker recreated without deleting volumes.
- Six services: **running/healthy**.
- `GET /api/v1/health`: **200**.
- `GET /api/v1/ready`: **200**.
- `ALLOW_REAL_PROVIDER=false` verified in the backend after restart.

## Next gate

The fix is ready for a separately authorized real 5Q verification. This turn
did not rerun DeepSeek and did not spend provider quota.
