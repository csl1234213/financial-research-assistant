# Financial RAG — P0 Quality Sprint 1.1

## Sprint status

`QUALITY FAIL / RUNTIME RECOVERED`

Sprint 1 semantic fixes remain frozen. This sprint addressed runtime completion
and evaluation integrity; it did not widen retriever or prompt scope.

## Failure inventory (frozen 100-request run)

| ID | Language | Category | Route | Model | Input | Output | Finish | Retrieval | Failure class |
|---|---|---|---|---|---:|---:|---|---:|---|
| EN-001 | EN | single_company | rag | deepseek-v4-flash | 2545 | 8192 | length | 4 | A — output exhaustion |
| ZH-014 | ZH | single_company | rag | deepseek-v4-flash | 1683 | 8192 | length | 4 | A — output exhaustion |
| ZH-019 | ZH | comparison | parallel | deepseek-v4-flash | 3021 | 8192 | length | 8 | A — output exhaustion |
| ZH-028 | ZH | unsupported | direct_llm | deepseek-v4-flash | 63 | 8192 | length | 0 | A — output exhaustion |
| ZH-045 | ZH | multi_turn | — | — | — | — | — | 0 | B — provider HTTP 402 |
| ZH-046 | ZH | multi_turn | — | — | — | — | — | 0 | B — provider HTTP 402 |
| ZH-047 | ZH | multi_turn | — | — | — | — | — | 0 | B — provider HTTP 402 |
| ZH-048 | ZH | multi_turn | — | — | — | — | — | 0 | B — provider HTTP 402 |
| ZH-049 | ZH | adversarial | — | — | — | — | — | 0 | B — provider HTTP 402 |

The four empty responses all exhausted the shared thinking/answer budget. The
five fallback responses were stopped before planning/retrieval by the DeepSeek
account balance error; no evidence indicates a planner, retriever, parser, or
context-overflow defect in those five requests.

## Changes in 1.1

- `llm/adapters/deepseek_provider.py` now performs one bounded recovery request
  (`thinking=disabled`, at most 2048 answer tokens) when a V4 response has an
  empty visible body and `finish_reason=length`. It never exposes
  `reasoning_content` as the answer and does not raise the global token limit.
- `services/agent_runtime/runtime.py` labels balance/rate-limit failures as a
  safe `[Provider Error]`, distinct from an actual `[Agent Runtime Fallback]`.
- `evaluation/live_100.py` adds `application_success`: HTTP 200, non-empty
  report, complete execution/workflow envelope, and no classified failure.
  Provider errors and runtime fallbacks are therefore not counted as success.
- Focused tests cover the recovery request, provider-error classification, and
  the application-success gate.

## Verification

- Focused pytest: **27 passed** (`tests/test_deepseek_provider_v4.py`,
  `tests/evaluation/test_semantic_review_contract.py`,
  `tests/security/test_runtime_error_redaction.py`).
- Docker backend and worker rebuilt and recreated without volume deletion.
- Six services healthy after rebuild; `/api/v1/health` returned 200 with
  version `8.2.0`; `/api/v1/ready` returned 200.
- `ruff` targeted scope: **PASS**.
- Frontend tests: **31 passed**; frontend production build: **PASS**.
- `git diff --check`: **PASS** (only pre-existing line-ending warnings were emitted by Git).

## Evaluation gate

| Gate | Result |
|---|---|
| EMPTY_OUTPUT_BEFORE | 4 |
| EMPTY_OUTPUT_AFTER | 0 (focused 9-question rerun) |
| RUNTIME_FALLBACK_BEFORE | 5 (all five traced to HTTP 402) |
| RUNTIME_FALLBACK_AFTER | 0 (focused 9-question rerun) |
| APPLICATION_SUCCESS_RATE | 9/9 (100%) |
| 429 / 503 / timeout attempts | Existing isolated drill; unchanged |
| Semantic grading | Focused 9 completed: 4 CORRECT, 3 PARTIAL, 2 INCORRECT |
| Focused strict accuracy | 4/9 (44.44%); EN 1/1, ZH 3/8 |
| Focused citation support | 13/20 citations VALID_SUPPORTED; 4/9 answers with supported claims |

The focused run is an incremental recovery check, not a replacement for the
frozen 100-question release gate. It exposed remaining quality defects in
unsupported-hire refusal (`ZH-028`) and Apple/Tesla follow-up retrieval
(`ZH-048`); those are quality findings, not runtime-completion failures.

Focused raw and review evidence:
`evaluation/results/formal_20260914_p0_quality_sprint1_1_focus/`.

The original provider HTTP 402 is now cleared. The nine-question live rerun
and resumed semantic grading completed without changing the original 100
answers or frozen dataset. One evaluator formatting issue was normalized and
ZH-046 was regraded as CORRECT; no synthetic judge output was created.

## Fresh frozen 100-question release gate

A new isolated run was prepared and executed after the DeepSeek balance was
restored. Its raw answers and semantic reviews are stored separately from the
earlier blocked run:

`evaluation/results/formal_20260914_p0_quality_sprint1_1_final/`

| Metric | Result |
|---|---:|
| HTTP 200 | 100/100 |
| Application-complete responses | 100/100 |
| Empty model content | 0 |
| Runtime fallbacks | 0 |
| Provider errors | 0 |
| Semantic reviews completed | 100/100 (one answer graded `FAILED`: `ZH-034`) |
| Strict CORRECT | 39/100 (39%) |
| English strict CORRECT | 18/50 (36%) |
| Chinese strict CORRECT | 21/50 (42%) |
| Citation support | 122/243 (50.21%) |
| Answers with at least one supported citation | 51/100 (51%) |
| Mean latency | 10,949.48 ms |
| P50 latency | 9,049.46 ms |
| P95 latency | 29,417.85 ms |
| P99 latency | 32,157.75 ms |
| Measured provider cost estimate | $0.240071874 |

The application-completion gate passes, but the release-quality gate fails the
Sprint 1 targets (strict accuracy ≥55%, Chinese accuracy ≥45%, and citation
support ≥65%). These semantic grades were produced by the configured
LLM-assisted reviewer and are not an independent human gold-label audit;
`ZH-034` is a genuine failed unsupported-data response and remains a product
quality finding.
No additional retriever or prompt changes were made in this run.

`429_ATTEMPTS`, `503_ATTEMPTS`, and `TIMEOUT_ATTEMPTS` are unchanged by this
sprint and remain covered by the existing isolated failure drill.
