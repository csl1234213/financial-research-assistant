# Financial RAG semantic repair — 2026-09-16

## Scope

This repair targets the grounding path used by the production response builder. No
Provider calls are made by the offline regression suite.

## Root causes found

1. Number parsing treated a closing parenthesis in explanatory text as a negative
   sign (`$22.496 billion)`), producing a false value mismatch.
2. PDF extraction may insert a space in decimals (`$75. 2 billion`); the parser
   previously split that value into two numbers.
3. Filing tables often expose bare million-scale values while the ledger stores
   normalized billion values. The validator now compares both representations only
   within the cited chunk and its matched filing period.
4. Narrative chunks can carry metric/period retrieval metadata without structured
   rows. Their raw numbers are accepted only when the metadata scope matches and all
   claimed operands are present in that same chunk.
5. Provider evidence ranks can drift after retrieval deduplication. For Chinese
   cited clauses, a failed rank is remapped only to a semantically filtered chunk
   that proves every number; wrong-company and wrong-period evidence is not opened
   by this fallback.
6. Citation-only page labels and `[Evidence N]` labels are excluded from numeric
   claim extraction.
7. A non-numeric heading or limitation line no longer inherits every trusted
   citation; only clauses with supported/derivable facts receive citations.
8. Multi-turn planning now merges an inherited company with a newly named
   comparison company (for example, Apple → “compare it with Tesla”), keeping
   both company partitions in retrieval.
9. Explicit citation markers are narrowed to chunks that support the numeric
   clause; prose markers use a conservative lexical-support check and are
   removed when no supporting chunk is present.
10. Metric, financial-summary, segment/driver, and risk queries receive bounded
    retrieval probes so a semantically similar narrative chunk cannot hide the
    requested statement table.
11. Hybrid coverage reranking now applies a bounded exact-term tie-breaker. It
    preserves distinctive query intent when vector and BM25 scores are nearly
    tied, without changing configured vector/lexical weights or applying a hard
    metadata filter.

## Verification

- Offline grounding/evaluation/retrieval/benchmark/planning/runtime/backup tests:
  **570 passed, 2 skipped**.
- Grounding contract tests: **11 passed**.
- Full offline pytest with evaluation quota bypass disabled for the process:
  **2230 passed, 23 skipped** (no real-provider opt-in).
- Ruff: **PASS**.
- Python compileall: **PASS**.
- `git diff --check`: **PASS**.
- Offline replay of five latest real answers: **0 unsupported numeric claims**.
- Controlled five-question production recheck: **5/5 correct**, required-fact
  coverage **5/5**, evidence utilization **5/5**, HTTP/application **5/5**.

The controlled recheck used the existing fixed 5-question set and restored
`ALLOW_REAL_PROVIDER=false` immediately afterwards. No evaluator calls were made.

## Provider pause and partial 100Q audit

The user stopped the second 100-question provider run to prevent further cost.
The persisted artifact `evaluation/results/formal_20260916_repair_partial/`
contains 94/100 completed HTTP-200 application responses (the final six were
not executed), with the Provider switch restored to false before this report.
Because the semantic evaluator was not run, no new answer-grade, citation-
entailment, or bilingual-parity totals are claimed here. The historical
33/1/223/19 counts therefore remain historical until a later, explicitly
authorized evaluation window. Per the user's cost-control instruction, no
further DeepSeek or evaluator calls are permitted before the offline repair is
accepted; the next real run is intentionally blocked.

## Next gate

The earlier 100-question semantic counts (33 incorrect, 1 failed, 223 citations
without sufficient entailment, and 19 bilingual mismatches) are historical results;
they are not rewritten by this repair. A fresh 100-question semantic re-evaluation
requires generating a new 100-answer corpus and incurs Provider/evaluator cost.
This repository is not yet cleared for that run while the Provider is paused;
the offline gate and a user-approved evaluation window must precede it.
