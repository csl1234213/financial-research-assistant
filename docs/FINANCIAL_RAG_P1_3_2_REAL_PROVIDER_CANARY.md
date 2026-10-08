# Financial RAG Assistant — P1.3.2 EN-007 Real Provider Canary

**Run date:** 2026-09-15  
**Fixed question:** `EN-007 — Summarize NVIDIA's financial performance in Q1 FY2027.`

## Execution safety

Exactly one production HTTP request was sent to `POST /api/v1/chat`. The request used the frozen EN-007 wording and was not retried. No evaluator request, remaining 9Q, 10Q, or 100Q was run.

```text
REAL_PROVIDER_CALLS: 1
EVALUATOR_CALLS: 0
DEEPSEEK_API_USED: YES (one authorized canary request)
```

The request ran through the production Router → Planner → Retriever → Reranker → Context Builder → DeepSeek → Grounding Validator → Sanitizer → API response path. Raw and final artifacts were captured in `evaluation/results/p1_3_2_real_provider_canary/`.

## Runtime result

```text
CANARY_STATUS: PASS
HTTP_STATUS: 200
APPLICATION_SUCCESS: true
TOTAL_LATENCY: 15.456s (client wall clock)
APPLICATION_EXECUTION_TIME: 15.396s
REQUEST_DEADLINE: 120s
CONNECT_TIMEOUT: 10s
READ_TIMEOUT: 45s
EMPTY_OUTPUT: false
RUNTIME_FALLBACK: false
PROVIDER_ERROR: false
```

The response completed well below the total deadline. No retry was performed.

Stage-level timing fields were not exposed in the HTTP response, and the short-lived canary container's stdout was rotated during the mandated guard restoration. Therefore the following are reported as **not observable**, not estimated:

```text
ROUTING_LATENCY: NOT_OBSERVABLE
PLANNING_LATENCY: NOT_OBSERVABLE
RETRIEVAL_LATENCY: NOT_OBSERVABLE
RERANK_LATENCY: NOT_OBSERVABLE
CONTEXT_LATENCY: NOT_OBSERVABLE
PROVIDER_LATENCY: NOT_OBSERVABLE
GROUNDING_LATENCY: NOT_OBSERVABLE
SANITIZER_LATENCY: NOT_OBSERVABLE
```

## EN-007 quality and grounding

The final answer retained the required NVIDIA Q1 FY2027 facts:

- Revenue: **$81.6 billion**
- Data Center revenue: **$75.2 billion**
- Q1 FY2027 period ended April 26, 2026
- GAAP/non-GAAP gross margin and EPS values

All retrieved and final evidence records were NVIDIA Q1 FY2027 PDF chunks. The deterministic gate result is:

```text
EN_007_GRADE: CORRECT
EVIDENCE_UTILIZATION: FULL
SUPPORTED_CLAIMS: 6
DERIVABLE_CLAIMS: 0
UNSUPPORTED_CLAIMS: 0
REMOVED_CLAIMS: 0
REWRITTEN_CLAIMS: 0
WRONG_COMPANY: 0
WRONG_PERIOD: 0
UNSUPPORTED_NUMERIC: 0
```

`audit.jsonl` contains both `raw_llm_answer` and `final_sanitized_answer`, plus grounding dispositions and retrieved/final evidence. In this canary the sanitizer did not remove or rewrite any claim; the final answer retained the required core facts.

## Usage and cost

The provider returned usage metadata:

```text
INPUT_TOKENS: 1475
OUTPUT_TOKENS: 1578
CACHED_TOKENS: 1280
MAIN_QUERY_COST: UNKNOWN (pricing is not emitted by the runtime)
EVALUATOR_COST: $0
TOTAL_CANARY_COST: UNKNOWN
```

No cost was guessed from token counts.

## Guard restoration and final gate

Immediately after the single request, the backend was recreated with the real-provider guard disabled and the audit path cleared. Final verification reported `ALLOW_REAL_PROVIDER=false`; all six Compose services remained healthy.

```text
ALLOW_REAL_PROVIDER_RESTORED: true
READY_FOR_REMAINING_9Q_SMOKE: YES
```

This result authorizes a separately requested remaining-9Q smoke only. It does not execute or authorize an automatic follow-up in this run.

