# Financial RAG P1.4.7 — Real Provider 5Q Verification

Date: 2026-09-16

## Scope

This was one fixed five-question run using the existing semantic recheck set:
`ZH-013`, `EN-016`, `EN-019`, `ZH-019`, and `ZH-008`. Each question made one
HTTP request. No automatic retry, evaluator request, question replacement, or
100Q run was performed.

## Result

```text
TEST_STATUS: FAIL
REAL_PROVIDER_CALLS: 5
HTTP_SUCCESS: 5/5
APPLICATION_SUCCESS: 5/5
CORRECT: 2/5
PARTIAL: 3/5
INCORRECT: 0
FAILED: 0
REQUIRED_FACT_FULL: 2/5
EVIDENCE_UTILIZATION_FULL: 2/5
WRONG_COMPANY: 2
WRONG_PERIOD: 0
UNSUPPORTED_NUMERIC: 7
OVER_SANITIZATION: 1
EMPTY_OUTPUT: 0
RUNTIME_FALLBACK: 0
PROVIDER_ERROR: 0
EVALUATOR_CALLS: 0
EVALUATOR_COST: $0
```

## Per-question result

| ID | HTTP | Grade | Required facts | Evidence utilization | Wrong company | Wrong period | Unsupported numeric | Over-sanitization |
| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: |
| EN-016 | 200 | CORRECT | FULL | FULL | 0 | 0 | 1 | 0 |
| EN-019 | 200 | PARTIAL | PARTIAL | PARTIAL | 1 | 0 | 1 | 0 |
| ZH-008 | 200 | CORRECT | FULL | FULL | 0 | 0 | 0 | 0 |
| ZH-013 | 200 | PARTIAL | PARTIAL | PARTIAL | 0 | 0 | 3 | 1 |
| ZH-019 | 200 | PARTIAL | PARTIAL | PARTIAL | 1 | 0 | 2 | 0 |

The exact response and audit records are in
`evaluation/results/p1_4_7_real_provider_5q_20260916/`.

## Cost and latency

```text
INPUT_TOKENS: 35722
OUTPUT_TOKENS: 15522
CACHED_TOKENS: 1408
MAIN_QUERY_COST: $0.028929048
TOTAL_SMOKE_COST: $0.028929048
LATENCY_P50_MS: 7234.04
LATENCY_MAX_MS: 36983.27
```

Usage values are the provider-reported values saved in each response. No
evaluator call was made.

## Interpretation

The runtime path completed all five requests without empty output, fallback,
provider error, HTTP error, or wrong-period detection. The gate still fails:

- EN-019 and ZH-019 included unexpected Tesla/NVIDIA sample sources in the
  final citation set, so the company-consistency gate is not clean.
- EN-019, ZH-013, and ZH-019 did not preserve all required facts under the
  deterministic checker, despite the generated text containing some completed
  facts.
- Seven numeric claims were not supported by the final evidence binding, and
  ZH-013 was flagged for over-sanitization.

These are real-provider observations, not converted into a pass by relaxing
the citation gate. The next action is an offline regression for source
filtering, answer completion, and Chinese multi-fact sanitation. Do not run the
remaining smoke questions until that offline gate passes.

## Root cause analysis

The failure has three distinct causes:

1. **Duplicate source identity and provenance contamination.** The tenant has
   uploaded/sample copies alongside the canonical public filings. The retriever
   returned both, for example `Tesla_sample.pdf` plus `Tesla_Q2_2025.pdf` and
   `NVIDIA_sample.pdf` plus `NVIDIA_Q1_FY2027.pdf`. The run's `wrong_company`
   counter is actually driven by `unexpected_citation_sources`; it does not prove
   that Tesla evidence was used for an NVIDIA claim. The real defect is missing
   canonical-document deduplication/source-authority precedence.

2. **The live checker used a stricter and partly incompatible representation
   check.** It inspected the complete API report (including the report wrapper),
   while the production audit's `final_grounding_result` recorded zero unsupported
   numeric claims for all five answers. It also looked for raw million strings;
   valid grounded values such as `22.496 billion USD` and `29.578 billion USD`
   were therefore marked missing even though they are equivalent to 22,496m and
   29,578m. The reported `UNSUPPORTED_NUMERIC: 7` is consequently a mixture of
   report-level revalidation noise and real answer-composition problems, not seven
   confirmed wrong financial values.

3. **Answer composition remained over-conservative for multi-fact questions.**
   For EN-019, ZH-019, and ZH-013, the model emitted repeated “Insufficient
   evidence” sections. The deterministic completion later appended the verified
   facts, but did not replace every earlier refusal or unsupported narrative.
   That is why required-fact coverage/evidence utilization was only PARTIAL even
   when the final grounding audit showed the appended facts as supported. This is
   the remaining production-quality defect.

There was no evidence of a provider failure, timeout, wrong-period claim, or
database/embedding outage in this run: HTTP and application success were 5/5,
wrong-period was 0, and fallback/provider-error counts were 0.

## Runtime restoration

```text
ALLOW_REAL_PROVIDER: false
P1_3_SMOKE_AUDIT_PATH: unset
frontend: healthy
backend: healthy
agent-worker: healthy
postgres: healthy
redis: healthy
chromadb: healthy
/api/v1/health: 200
/api/v1/ready: 200
```

Existing PostgreSQL, Redis, Chroma, uploads, and logs volumes were preserved.

## Decision

```text
NEXT_REAL_PROVIDER_STAGE: BLOCKED_PENDING_OFFLINE_REPAIR
READY_FOR_REMAINING_5Q: NO
READY_FOR_100Q: NO
```
