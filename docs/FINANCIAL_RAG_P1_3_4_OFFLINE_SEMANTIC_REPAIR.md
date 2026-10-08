# Financial RAG Assistant P1.3.4 — Offline Semantic Repair

Date: 2026-09-15  
Provider policy: `ALLOW_REAL_PROVIDER=false` throughout this sprint

## Gate status

```text
DEEPSEEK_API_USED: NO
REAL_PROVIDER_CALLS: 0
API_COST: $0
READY_FOR_REAL_PROVIDER_SEMANTIC_RECHECK: YES
```

No 5Q, 10Q, or 100Q provider run was performed. The five regressions below
were replayed from the saved P1.3.3 raw answers and frozen evidence corpus.

## Evidence pipeline findings

| Case | Previous failure stage | Offline repair | Replay result |
|---|---|---|---|
| ZH-013 | Context | bounded summary metric probes and required-fact completion | FULL |
| EN-016 | Context | operating-cash-flow metric distinction and required-fact completion | FULL |
| EN-019 | Context / period semantics | comparative-table column scoping; unsupported Tesla Q4 claim removed | FULL |
| ZH-019 | Context / period semantics | same row-period rule; Tesla Q2 fact retained | FULL |
| ZH-008 | Sanitizer | Chinese `亿/亿美元` normalization and partial-line preservation | FULL |

The production path remains:

```text
retrieval → semantic gate → context probes → provider answer
         → grounding validator → sanitizer → required-fact completion
         → response report
```

Required-fact completion is conservative: it only adds values found in a
metric-labelled, company/period-compatible evidence row. It never invents a
value and does not run for direct/general-concept chat.

## Rules repaired

1. Chinese financial units are normalized (`亿`, `万`, `美元`, `人民币`). A
   provider rendering such as `75.2 亿美元` is rewritten to the equivalent
   evidence-backed `752 亿美元` rather than silently treating it as `$7.52B`.
2. Comparative tables use row/column period semantics. A filing/document
   quarter or filename is not allowed to validate a different table column.
3. An unsupported operand can no longer be rescued by a valid derived
   percentage on the same line. Mixed-company lines retain supported clauses
   while replacing only unsupported fragments.
4. Cash paid for taxes is not treated as operating cash flow.
5. Summary/FACT/COMPARE scopes expose required-fact coverage in planning
   metadata and append only missing facts that are already present in final
   context.

## Offline replay output

The replay is reproducible with:

```text
python evaluation/replay_p1_3_4.py
```

Artifacts:

- `evaluation/regression/p1_3_4_semantic_cases/cases.json`
- `evaluation/regression/p1_3_4_semantic_cases/README.md`
- `evaluation/results/p1_3_4_offline_semantic_repair/replay.json`
- `evaluation/results/p1_3_4_offline_semantic_repair/summary.json`

Final replay gates:

```text
CASES: 5/5
EVIDENCE_UTILIZATION_FULL: 5
EVIDENCE_UTILIZATION_PARTIAL: 0
EVIDENCE_UTILIZATION_FAILED: 0
FINAL_UNSUPPORTED_NUMERIC: 0
WRONG_COMPANY: 0
WRONG_PERIOD: 0
OVER_SANITIZATION: 0
```

Raw unsupported claims are retained in the replay artifact for audit. They
are not returned as final numeric claims; unsafe fragments are removed or
replaced with an insufficiency statement.

## Validation

```text
pytest -q
2107 passed, 23 skipped

pytest tests/evaluation/test_p1_3_4_semantic_repair.py -q
5 passed

frontend: npm test -- --runInBand
31 passed

frontend: npm run build
PASS

ruff check <changed Python files>
PASS

git diff --check
PASS

docker compose config -q
PASS
GET /api/v1/health
200
GET /api/v1/ready
200
```

Docker services were healthy during validation: `frontend`, `backend`,
`agent-worker`, `postgres`, `redis`, and `chromadb`.

## Retrieval baseline (unchanged)

```text
Candidate Recall@12: Source 99.6%, Chunk 100.0%
Rerank Recall@4:     Source 99.6%, Chunk 95.8%
Final Context:       Source 99.6%, Chunk 95.8%
```

The sprint did not retune BM25/vector weights, RRF, candidate multipliers, or
global Top-K. Summary metric probes are bounded context-coverage probes.

## Files changed for P1.3.4

```text
core/answer_grounding.py
core/core_engine.py
core/evidence_coverage.py
core/financial_grounding.py
retrieval/periods.py
evaluation/replay_p1_3_4.py
evaluation/regression/p1_3_4_semantic_cases/cases.json
evaluation/regression/p1_3_4_semantic_cases/README.md
tests/evaluation/test_p1_3_4_semantic_repair.py
```

Existing unrelated working-tree changes and historical artifacts were not
removed, reset, staged, committed, or pushed.

## Final decision

```text
P1.3.4 OFFLINE SEMANTIC REPAIR: PASS
READY_FOR_REAL_PROVIDER_SEMANTIC_RECHECK: YES
```

The next step, if authorized separately, is one controlled real-provider
semantic recheck. This sprint itself stops here.
