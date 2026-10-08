# Financial RAG Assistant — P1.3.3 Remaining 9Q Real Provider Smoke

**Run date:** 2026-09-15  
**Frozen input:** `evaluation/datasets/p1_3_real_smoke_10.json`, excluding the already completed EN-007 canary.

## Execution boundary

The nine remaining frozen questions were sent in their existing order. Each question had exactly one HTTP harness request; no harness retry, evaluator request, question substitution, prompt change, or timeout increase was used. The run stopped after all nine because no critical runtime failure occurred. The 100Q benchmark was not run.

```text
P1_3_2_CANARY: EN-007, PASS, 1 HTTP request
P1_3_3_CONTINUATION: 9 HTTP requests
FROZEN_SMOKE_TOTAL: 10 HTTP requests across two runs
EVALUATOR_CALLS: 0
```

## Runtime gate

```text
REMAINING_9Q_HTTP_SUCCESS: 9/9
REMAINING_9Q_APPLICATION_SUCCESS: 9/9
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
CRITICAL_RUNTIME_FAILURES: 0
REQUEST_DEADLINE: 120s
CONNECT_TIMEOUT: 10s
READ_TIMEOUT: 45s
```

No request exceeded the deadline. ZH-044 and EN-033 intentionally completed through production short-circuit paths without a provider usage record: ZH-044 is the required direct-chat concept route and EN-033 is the required insufficient-evidence route. The remaining seven continuation requests recorded one DeepSeek usage call each.

## Deterministic semantic review

| ID | Grade | Evidence utilization | Finding |
| --- | --- | --- | --- |
| EN-002 | CORRECT | FULL | Tesla Q2-2025 revenue `$22,496m` retained; Q4 YoY was not applied to Q2. |
| EN-019 | PARTIAL | PARTIAL | Comparison exists, but `$24.9B` Q4 material is mixed with a Q2 label and the Q2 `$22,496m` anchor is omitted. |
| ZH-044 | CORRECT | FULL | General gross-margin explanation; no financial citations. |
| ZH-007 | CORRECT | FULL | NVIDIA Q1 FY2027 revenue, Data Center, margin, and EPS anchors retained. |
| ZH-013 | INCORRECT | PARTIAL | Claims Apple headline figures are unavailable and omits required Q2 FY2026 metrics. |
| EN-016 | INCORRECT | PARTIAL | Reports only supplemental tax cash and misses six-month operating cash flow `$82,627m`. |
| ZH-008 | PARTIAL | FAILED | Correct NVIDIA evidence is present in context, but the main answer is replaced by insufficient-evidence text. Over-sanitization flagged. |
| EN-033 | CORRECT | FULL | Insufficient-evidence answer with no irrelevant company citation. |
| ZH-019 | PARTIAL | PARTIAL | Comparison and non-contemporaneous caveat are present, but Tesla Q2 anchor is omitted and Q4 material is mixed into Q2-labeled context. |

```text
CORRECT: 4
PARTIAL: 3
INCORRECT: 2
FAILED: 0
CRITICAL_WRONG_COMPANY: 0
CRITICAL_WRONG_PERIOD: 2
FINAL_UNSUPPORTED_NUMERIC_CLAIMS: 0
EVIDENCE_UTILIZATION_FULL: 4
EVIDENCE_UTILIZATION_PARTIAL: 4
EVIDENCE_UTILIZATION_FAILED: 1
OVER_SANITIZATION_COUNT: 1
```

The two wrong-period findings are semantic review findings in the Tesla/NVIDIA comparisons, not HTTP/provider failures. Raw grounding contained 10 unsupported claims; the sanitizer removed 10 and rewrote 4 derivable claims. The per-question raw and final answers, citation lists, grounding dispositions, and retrieved/final context evidence (including frozen public chunk text) are preserved in `smoke_results.json` and `audit.jsonl`.

## Usage and latency

```text
P1_3_2_CANARY_PROVIDER_CALLS: 1
P1_3_3_PROVIDER_CALLS: 7
TOTAL_PROVIDER_CALLS: 8
TOTAL_INPUT_TOKENS: 13307
TOTAL_OUTPUT_TOKENS: 24069
TOTAL_CACHED_TOKENS: 11648
MAIN_QUERY_COST: UNKNOWN (request timestamps/pricing invoice not emitted)
EVALUATOR_COST: $0
TOTAL_SMOKE_COST: UNKNOWN

LATENCY_P50: 7944.60ms (nearest-rank, frozen 10Q)
LATENCY_P90: 21174.22ms (nearest-rank, frozen 10Q)
LATENCY_MAX: 31248.52ms
OVER_45S: 0
OVER_60S: 0
OVER_120S: 0
```

These are smoke observations, not an SLA benchmark.

## Final gate

```text
SMOKE_STATUS: FAIL
ALLOW_REAL_PROVIDER_RESTORED: true
READY_FOR_FINAL_100Q_BENCHMARK: NO
```

The failure is semantic, not runtime: the frozen 10Q quality requirements are not met because `CORRECT + PARTIAL = 7/10`, there are two wrong-period findings, one failed evidence-utilization case, and one over-sanitization finding. Per the runbook, no additional real request is made. These findings must become offline regressions and pass the offline release gate before another smoke is requested.
