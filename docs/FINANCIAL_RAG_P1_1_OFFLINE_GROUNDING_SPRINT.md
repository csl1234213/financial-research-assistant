# Financial RAG P1.1 — Offline Grounding Sprint

**Date:** 2026-09-14  
**Mode:** frozen artifacts + seeded in-memory retrieval only  
**Provider calls:** 0

## Result

| Gate | Result | Threshold / note |
|---|---:|---|
| Candidate Recall@12 (source) | **99.6%** | target ≥95%; 112 source-level cases |
| Post-Rerank Recall@4 (source) | **99.6%** | target ≥90% |
| Final Context Coverage (source) | **99.6%** | target ≥90% |
| Candidate Recall@12 (chunk) | **100.0%** | 24 table cases; any valid truth chunk counts |
| Post-Rerank Recall@4 (chunk) | **95.8%** | 24 table cases |
| Final Context Coverage (chunk) | **95.8%** | 24 table cases |
| Page-level coverage | N/A | frozen corpus has no authoritative page labels |
| Period Gate | **100/100** | unchanged |
| Metric Gate | **100/100** | unchanged |
| Company Gate (raw) | **98/100** | EN-046 and ZH-046 contamination |
| Company Gate (grounding policy) | **100/100** | out-of-scope citations are dropped |

The chunk metric is a case-level hit over the set of authoritative table
chunks (a table can have multiple equivalent page-block chunks); it does not
pretend that every duplicate block must be present.

## Numeric grounding

The historical raw gate remains **47/100** and was not weakened.  The new
normalizer independently scores the frozen answers at **83/100** before the
output policy.  Its failure breakdown is:

| Failure class | Count |
|---|---:|
| NUMERIC_VALUE_MISMATCH | 1 |
| UNIT_MISMATCH | 0 |
| CURRENCY_MISMATCH | 0 |
| PERIOD_MISMATCH | 0 |
| METRIC_MISMATCH | 0 |
| UNSUPPORTED_DERIVATION | 0 |
| NO_SUPPORTING_CITATION | 16 |
| OVERANSWERING | 0 |

The new parser normalizes thousand/million/billion suffixes, currencies,
percentages, basis-point-like values, comma decimals and parenthesized
negatives.  It rejects `$81.6B` versus `$81.6M`, and keeps revenue,
automotive revenue, net income, operating income, gross margin and operating
margin as distinct canonical metrics.  Derived growth is retained only when
both operands are present and the deterministic calculation verifies.

The grounding-safe projection reaches **100/100** by removing unsupported
numeric claim lines from a copy of the frozen answer.  This is an offline
policy projection; provider answers and historical artifacts were not
rewritten.  Production behavior is “supported → keep, derivable → keep only
after calculation, unsupported → omit/insufficient evidence”.

## Coverage-aware reranking

`HybridRetriever.coverage_aware_rerank` applies bounded boosts for explicit
company/period/metric/table/section matches and reserves one slot per named
company for comparison questions.  Missing or uncertain metadata is neutral,
not a hard filter.  The offline stage runner expands comparison candidates per
company before selecting the 12-candidate pool; this prevents Apple/NVIDIA/
Tesla comparisons from being consumed by one company’s semantic hits.

## English regression audit

The nine English regressions are reported in
`evaluation/results/p1_1_english_regressions.json` with question, expected
evidence, candidate top-12, reranked top-4, final context, old/new ranking and
loss stage.  They are:

`EN-005`, `EN-008`, `EN-009`, `EN-012`, `EN-022`, `EN-032`, `EN-037`,
`EN-045`, `EN-047`.

All nine retain source-level evidence through the candidate and final-context
stages after coverage-aware selection.  Therefore unresolved **architecture**
regressions are **0**.  The nine remain ranking/answer diagnostic records (old
chunk IDs are explicitly marked as a non-authoritative proxy because the
frozen dataset has source truth, not gold chunk truth).  EN-032, EN-045 and
EN-047 are reasoning/scope cases, not retrieval losses.

## Company contamination

EN-046 cited Apple after a Tesla follow-up; ZH-046 cited Tesla and NVIDIA for
a Tesla follow-up.  The policy uses the effective expected company set and
drops out-of-scope citations.  It does not broaden the allowed company set.

## Knowledge scope

ZH-034 remains **KNOWLEDGE_SCOPE**: Alibaba is absent from the frozen corpus.
No Alibaba answer, expected criterion or question-specific hardcode was added.

## Artifacts

- `evaluation/p1_1_grounding.py` — provider-free stage, regression, numeric and company audit.
- `core/financial_grounding.py` — normalized numeric/metric/derived-claim primitives.
- `retrieval/hybrid_retriever.py` — deterministic coverage-aware selector.
- `tests/evaluation/test_p1_1_grounding.py` — offline normalization and rerank tests.
- `evaluation/results/p1_1_evidence_stages.json`
- `evaluation/results/p1_1_english_regressions.json`
- `evaluation/results/p1_1_numeric_breakdown.json`
- `evaluation/results/p1_1_company_policy.json`
- `evaluation/results/p1_1_offline_summary.json`

## Verification

- P1.1 focused tests: PASS (5 tests).
- Evaluation tests: PASS (117 tests).
- Credential-free backend suite excluding live E2E/benchmark suites: PASS (1,893 tests).
- Frontend tests: PASS (31 tests); frontend build: PASS.
- Ruff production scope: PASS; `git diff --check`: PASS; Docker six-service health: PASS.
- The unfiltered suite still contains known unrelated workflow benchmark and invalid-fixture E2E failures; they were not changed in this grounding sprint.
- DeepSeek API: **NO**; real provider calls: **0**; cost: **$0**.

## Final gate

`READY_FOR_REAL_API_SMOKE: NO` — the normalized/projection gates are useful
offline evidence, but this sprint intentionally stops before any real-provider
smoke or 10Q/100Q benchmark.
