# P1.4.1 Real Provider Fact Ledger Recheck — Retry

Date: 2026-09-15  
Scope: exactly one production HTTP request for each fixed case: `ZH-013`, `EN-016`, `EN-019`, `ZH-019`, `ZH-008`. No evaluator call, no retry, no 10Q/100Q run.

## Gate result

```text
FACT_LEDGER_RECHECK_STATUS: FAIL
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
CORRECT (automated ledger coverage): 3/5
PARTIAL: 2/5
INCORRECT: 0
FAILED: 0
REQUIRED_FACT_FULL: 3/5
EVIDENCE_UTILIZATION_FULL: 3/5
```

The rebuilt image did contain the P1.4 implementation. Fact Ledger data was
present for all five requests (`33` extracted facts total), but two cases did
not achieve required-fact coverage. The semantic review below is stricter than
the generic company-only comparison plan and therefore keeps the release gate
closed.

## Per-question review

| ID | HTTP/app | Automated coverage | Manual semantic result | Finding |
|---|---:|---:|---:|---|
| ZH-013 | 200 / PASS | PARTIAL | PARTIAL | Ledger extracted spurious `revenue=10`, `gross_margin=10`, and an EPS share-count value `14,673,278`; required Apple Q2 net sales/net income/cash flow were not available in the live context. |
| EN-016 | 200 / PASS | PARTIAL | PARTIAL | `operating_cash_flow=82,627` was extracted as undated, so the Q2 2026 Required Fact Plan correctly marked it unavailable and did not complete the answer. |
| EN-019 | 200 / PASS | FULL* | PARTIAL | Company partitions existed, but the answer/citations foregrounded duplicate tenant `tesla_report.pdf` with undated `$82.4B` and `$24.9B`; the frozen expected Tesla Q2 table anchor `$22,496m` was not preserved. |
| ZH-019 | 200 / PASS | FULL* | PARTIAL | Same duplicate/undated Tesla evidence and missing frozen Tesla Q2 `$22,496m` anchor; Chinese answer cannot pass the comparison criterion. |
| ZH-008 | 200 / PASS | FULL | CORRECT | NVIDIA Q1 FY2027 Data Center revenue `$75.2B` was available in the ledger and deterministically completed into the final answer. |

`*` The automated generic comparison plan accepts any company revenue fact
when no period is specified. This is insufficient for the frozen comparison
criteria, which require Tesla Q2 2025 and NVIDIA Q1 FY2027 anchors.

## Fact Ledger / grounding observations

```text
FACT_LEDGER_FACTS: 33
SUPPORTED_CLAIMS: 20
SUPPORTED_CLAIMS_KEPT: 20
UNSUPPORTED_CLAIMS: 6
UNSUPPORTED_CLAIMS_REJECTED: 6
GROUNDING_KEEP_RATE: 1.0
GROUNDING_REJECTION_RATE: 1.0
DETERMINISTIC_COMPLETIONS: 4
OVER_SANITIZATION: 0 (no available planned fact was silently deleted)
```

The current harness's secondary numeric re-scan reports `62`, but that scan is
not used as the production gate because it re-parses the complete formatted
Research Report. The production grounding audit recorded six unsupported
claims and rejected all six. Critical semantic issues remain in fact
availability/period binding and in the choice of duplicate tenant evidence.

## Runtime and cost

```text
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
INPUT_TOKENS: 11612
OUTPUT_TOKENS: 20982
CACHED_TOKENS: 1024
MAIN_QUERY_COST: $0.028360944
EVALUATOR_COST: $0
LATENCY_P50: 22077.45 ms
LATENCY_MAX: 30660.64 ms
```

Automated counters reported `WRONG_COMPANY=0`, `WRONG_PERIOD=0`, and
`WRONG_METRIC=0`; those counters are not sufficient to clear this run because
the undated Tesla tenant facts and the missing Tesla Q2 table anchor are
semantic period/source failures rather than literal company-name mismatches.

## Artifacts

- [summary.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck_retry/summary.json)
- [ZH-013.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck_retry/ZH-013.json)
- [EN-016.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck_retry/EN-016.json)
- [EN-019.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck_retry/EN-019.json)
- [ZH-019.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck_retry/ZH-019.json)
- [ZH-008.json](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck_retry/ZH-008.json)
- [raw_grounding_audit.jsonl](../evaluation/results/p1_4_1_real_provider_fact_ledger_recheck_retry/raw_grounding_audit.jsonl)

Each case artifact contains the raw answer, final API response, retrieved and
final evidence, Fact Ledger, Required Fact Plan, generation check,
deterministic completions, removed lines, and claim bindings.

## Guard and service state

After the five requests, backend and agent-worker were recreated with the
Provider disabled:

```text
ALLOW_REAL_PROVIDER: false
P1_3_SMOKE_AUDIT_PATH: empty
/api/v1/health: 200
/api/v1/ready: 200
frontend/backend/agent-worker/postgres/redis/chromadb: healthy
```

No token, password, API key, or Authorization header was written to the
artifacts. No volume was deleted and no commit or push was performed.

## Final decision

```text
FACT_LEDGER_RECHECK_STATUS: FAIL
READY_FOR_FINAL_10Q_RELEASE_SMOKE: NO
```

Required offline follow-up before another real-provider window:

1. Make period binding explicit for operating cash flow (`Q2_2026` versus
   six-month/undated table values).
2. Prevent numeric extraction from treating page numbers/share counts as
   Apple revenue/EPS facts.
3. Exclude or demote duplicate tenant Tesla evidence when the frozen public
   Tesla Q2 source is required, and enforce the `$22,496m` Q2 anchor.
