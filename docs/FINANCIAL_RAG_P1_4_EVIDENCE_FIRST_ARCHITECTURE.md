# Financial RAG Assistant — P1.4 Evidence-First Answer Architecture

Date: 2026-09-15  
Scope: offline architecture and regression work only. No DeepSeek, 5Q, 10Q, 100Q, or evaluator calls were made.

## Final gate

```text
SPRINT_STATUS: PASS
DEEPSEEK_API_USED: NO
REAL_PROVIDER_CALLS: 0
API_COST: $0

FACT_LEDGER: PASS
FACT_PRECISION: 100% (focused fixtures)
FACT_RECALL: 100% (focused fixtures)
REQUIRED_FACT_PLAN: PASS (5/5)
COMPANY_PARTITION: PASS
PERIOD_BINDING: PASS
METRIC_BINDING: PASS
GENERATION_MUTATION_CASES: 30
GENERATION_MUTATION_PASS: 30/30
SUPPORTED_FACT_KEEP: 100%
UNSUPPORTED_FACT_REJECT: 100%
WRONG_COMPANY_ACCEPTED: 0
WRONG_PERIOD_ACCEPTED: 0
WRONG_METRIC_ACCEPTED: 0
UNSUPPORTED_NUMERIC_ACCEPTED: 0
AVAILABLE_REQUIRED_FACT_OMITTED: 0

P1.3.5_OFFLINE_REPLAY: 5/5 CORRECT
READY_FOR_REAL_PROVIDER_FACT_LEDGER_RECHECK: YES
```

The replay pairs the five saved P1.3.5 raw model answers with frozen authoritative evidence fixtures. It is an offline production-pipeline check, not a claim that a new Provider call was made or that the prior live retrieval response changed.

## Architecture changes

### Financial Fact Ledger

[core/fact_ledger.py](../core/fact_ledger.py) introduces `FinancialFact` and `FactLedger`. Every extracted fact carries:

- canonical `metric_id` (`revenue`, `operating_cash_flow`, `cash_paid_for_taxes`, `data_center_revenue`, etc.);
- normalized value, unit, and currency;
- document reporting period plus fact/table row/column period;
- company partition, document, page, section, chunk ID, evidence text, and confidence;
- deterministic `fact_id` provenance.

`operating_cash_flow` and `cash_paid_for_taxes` are separate IDs and cannot satisfy one another.

### Required Fact Plan

[core/required_fact_plan.py](../core/required_fact_plan.py) creates scope-aware required facts for FACT, SUMMARY, and COMPARE questions. Comparisons receive one plan entry per named company. Available facts are mapped before generation, and a deterministic completion step adds omitted verified facts without a second Provider call.

### Production integration

[core/core_engine.py](../core/core_engine.py) now builds a partitioned verified-fact context before the LLM call, records the plan and ledger in internal planning metadata, checks generated claims against fact IDs, completes available required facts, and applies a ledger-backed numeric safety pass before report serialization. The existing sanitizer remains the final safety net.

### Synthetic generation mutations

[tests/evaluation/test_p1_4_evidence_first.py](../tests/evaluation/test_p1_4_evidence_first.py) covers 32 offline tests, including 30 mutations across the five P1.3.5 cases:

- supported amount and unit-normalized amount → KEEP;
- wrong metric (`cash_paid_for_taxes` for operating cash flow) → REJECT;
- omitted available fact → COMPLETE;
- wrong numeric value → REJECT.

## Offline replay artifacts

- [P1.4 evidence fixtures](../evaluation/regression/p1_4_evidence_first/cases.json)
- [Replay script](../evaluation/replay_p1_4.py)
- [Replay summary](../evaluation/results/p1_4_offline_replay/summary.json)
- [Replay case artifacts](../evaluation/results/p1_4_offline_replay/)

The replay produced `ZH-013`, `EN-016`, `EN-019`, `ZH-019`, and `ZH-008` as `CORRECT`, with no remaining unsupported numeric claims or omitted available required facts.

## Verification

```text
BACKEND_OFFLINE_TESTS: 2139 passed, 23 skipped, 1 warning
FOCUSED_P1.4_TESTS: 32 passed
FRONTEND_TESTS: 31 passed
RUFF: PASS
BUILD: PASS
GIT_DIFF_CHECK: PASS
DOCKER_COMPOSE_CONFIG: PASS
DOCKER: six services healthy
/api/v1/health: 200
/api/v1/ready: 200
```

The only Ruff issue found during the full run was an import-order formatting issue in the existing period-aware retrieval test; it was corrected mechanically with Ruff and no test behavior changed.

## Provider guard

The entire sprint kept real Provider access disabled. The running backend was checked with `ALLOW_REAL_PROVIDER=false`; no API key, token, password, or authorization header was written to the report or artifacts.

No commit, push, volume deletion, database reset, or benchmark execution was performed.

## Next gate

The architecture is ready for a future, explicitly authorized five-question real semantic recheck:

```text
READY_FOR_REAL_PROVIDER_FACT_LEDGER_RECHECK: YES
```

The next live run must still be limited to `ZH-013`, `EN-016`, `EN-019`, `ZH-019`, and `ZH-008`; it must not jump directly to 10Q or 100Q.
