# Financial RAG — offline semantic repair checkpoint

Date: 2026-09-17

## Safety status

```text
DEEPSEEK_API_USED: NO
REAL_PROVIDER_CALLS: 0
EVALUATOR_CALLS: 0
API_COST: $0
ALLOW_REAL_PROVIDER: false for the offline replay and test processes
```

No answer was regenerated and no frozen benchmark label or historical result
was edited. This checkpoint is not a semantic re-grade of the 100 answers.

## Frozen baseline provenance

The requested historical counts **33 INCORRECT / 1 FAILED**, **223
VALID_BUT_NOT_SUPPORTED**, and **19 bilingual grade mismatches** come from
``evaluation/results/formal_20260916/``. Its frozen semantic review contains
100 answers and 341 citation reviews (118 supported, 223 not supported under
that evaluator's rubric). The counts are audit inputs, not current-code test
results; those files are not edited by this repair.

Do not confuse this baseline with the earlier, separately frozen
``evaluation/results/formal_20260914_p0_quality_sprint1_1_final/`` artifact. It
has different historical labels (35 incorrect, 1 failed, 121 not-supported
citations over 243 citation reviews) and is not the source for the 33/223/19
gate.

## Offline changes

- Qualitative citations on period-specific questions must now have period
  evidence in the cited text or period-specific metadata. A Q4/FY risk passage
  cannot support a Q2-specific narrative claim solely because it is from the
  same company/report. Numeric table claims continue to use their exact row and
  column period validation.
- English/Chinese financial query normalization now recognizes Services and
  Automotive business/segment wording, and British ``data centre`` spelling.
- Chinese business-performance follow-ups are classified as summaries. A
  requested specific metric with no matching evidence no longer silently falls
  back to an unrelated total-revenue fact.
- Generic bilingual margin follow-ups are planned against available gross and
  operating margin facts only. The plan carries the inherited issuer and
  reporting period when those are present in the conversation context.
- The new replay harness feeds frozen raw answers and exact frozen citation
  chunks through ``core.answer_policy.finalize_grounded_answer`` and mirrors the
  production API's citation projection. It refuses to run if real Provider use
  is enabled and never overwrites an existing output directory.
- The ingestion guide records the GitHub-derived safeguards: structured
  format adapters, table/prose isolation, preserved locators, and source order
  independent of embedding similarity.
- The semantic-review contract now separates three questions that were
  previously conflated: whether a cited passage entails the exact attached
  answer claim, whether that claim is relevant to the user's question, and
  whether a retrieved passage was cited at all. A valid but tangential cited
  claim can be locally supported while the overall answer remains incomplete;
  an unreferenced retrieval candidate is recorded as
  ``UNUSED_RETRIEVED_CONTEXT`` rather than as an unsupported answer citation.
- This separation was prompted by inspection of frozen review records such as
  EN-014, where locally quoted wording was judged against whole-question
  coverage. The old rubric therefore mixed citation entailment and answer
  completeness. This is a measurement defect, not evidence that those old
  citations were all correct.
- The evaluator change only affects future explicitly authorized reviews. No
  historical semantic review, benchmark grade, or artifact was rewritten.
- Both report finalizers now preserve and display the separate unused-context
  category when present. When consuming a legacy ledger with no such field,
  they say it was not measured instead of emitting a misleading zero. Manual
  supported-rank overrides do not relabel an unreferenced chunk as a user-facing
  cited claim.
- Added an offline EN-046-style retrieval regression that resolves the prior
  Tesla Q2 2025 user turn, verifies the plan binds the follow-up to Tesla plus
  ``Q2_2025``/``gross_margin``, then retrieves only Tesla's Q2 comparative-row
  evidence from a mixed Apple/NVIDIA/Tesla candidate pool. This exercises the
  deterministic planner/retriever boundary; it does not simulate or claim a
  new HTTP/provider answer.
- Follow-up scope resolution now stops at a standalone companyless user
  question instead of reaching across a topic change to resurrect an older
  issuer. Chained referential turns such as “What about margins?” followed by
  “And operating margin?” still retain the active entity.
- The EN-045-style elliptical follow-up “What was the main growth driver?” is
  now recognized as referential even without a pronoun, so the immediately
  preceding NVIDIA request supplies the issuer and keeps the turn on the
  document-QA path rather than direct chat. The equivalent Chinese elliptical
  follow-up is covered by the parallel growth-driver vocabulary.
- Growth-driver reranking now reserves issuer-specific reported commentary
  before the generic company slot. Previously a high-scoring safe-harbor chunk
  could consume that slot ahead of a lower-scoring but substantive
  AI-factory/agentic-AI passage. Company metadata that is absent still has a
  generic driver-evidence fallback; this is a ranking coverage rule, not a
  hard filter on uncertain metadata.
- Added a mixed-company bilingual regression: both English and Chinese
  follow-ups inherit NVIDIA, plan document QA, exclude an Apple growth chunk,
  and retrieve the reported NVIDIA driver passage ahead of safe-harbor
  boilerplate. This is a deterministic retrieval test, not a regenerated
  answer or a regrade of the historical pair.
- Risk/constraint questions now use separate per-company coverage slots for
  substantive risk factors and explicitly requested operating constraints.
  On multi-company risk questions, a resolved company mismatch is excluded
  from final context while missing/unknown issuer metadata remains eligible.
  The same bounded issuer-mismatch exclusion now applies to explicit
  multi-company financial comparisons; unknown issuer metadata stays eligible.
  If the query yields no concrete risk evidence, retrieval returns an empty
  evidence set rather than padding with boilerplate. Regression cases cover
  statutory “Litigation Reform Act” wording, routine “regulatory conditions,”
  table-of-contents hits, safe-harbor prose, real Apple-style “materially and
  adversely affected” wording, and Tesla-style “important factors … could
  cause” wording. The focused hybrid retrieval suite passes **29 tests** with
  BLAS/OpenMP thread counts constrained; no Provider/evaluator call was made.
  The tests prove the offline retrieval contract only; they do not re-grade the
  historical 100 answers.
- Grounding no longer treats an English filing date such as ``April 26, 2026``
  as an ungrounded financial amount, and period parsing accepts the canonical
  metadata key ``Q1_FY2027`` as well as its display form. A provider-free
  regression uses NVIDIA's actual three-month table header and the historically
  over-sanitized EN-007 reporting-period sentence.
- A real checked-in Apple Q2 FY2026 PDF was parsed through the canonical PDF
  loader and passed through the public hybrid retrieval entry point with a fake
  embedding store. Revenue retrieval returns the actual `$111,184m` vs
  `$95,359m` row; the cash-flow query returns the actual six-month operating
  cash-flow figure `$82,627m`. This is an offline retrieval integration test,
  not a model-answer or semantic-accuracy re-grade.
- Broad, metric-unspecified summary queries now add compact multi-metric
  highlights and non-boilerplate growth-driver chunks to the candidate pool,
  then reserve those evidence types ahead of generic company/context fillers.
  This addresses a reproduced NVIDIA Q1 failure where top-k contained income
  statement/cash-flow chunks and a shareholder-return paragraph but omitted
  the report's Data Center headline and AI-factory/agentic-AI drivers. A new
  canonical `NVIDIA_sample.pdf` test asserts revenue and growth, Data Center
  revenue/growth, gross margins, diluted EPS, and reported drivers all fit in
  the four-result context, while the Q2 `$91.0B` outlook is not substituted for
  Q1 actuals. No retrieval weights, RRF constant, or top-k were changed.
- English ``financially`` questions now classify as broad summaries rather
  than falling through to FACT. A canonical Apple Q2 FY2026 10-Q replay exposed
  a second format-specific problem: detailed statements split across adjacent
  table-row chunks lost revenue/net-income/EPS facts to narrative slots in the
  four-chunk context. When structured statement-of-operations evidence is
  detected, the selector now reserves revenue, net income, gross margin, and
  diluted EPS rows before optional narrative. It recognizes a ``Diluted`` row
  as EPS only when the same table text explicitly supplies an ``Earnings per
  share`` heading. Apple regression coverage checks Q2 net sales 111,184,
  operating income 35,885, net income 29,578, and diluted EPS 2.01 (USD
  millions except per-share amount). The NVIDIA earnings-release regression
  still follows the compact-highlight + substantive-driver path. No issuer ID,
  exact question, benchmark row, retrieval weight, or final top-k is hardcoded.
- Metric extraction now preserves simultaneous gross/operating-margin intent;
  unqualified “margins” means both measures instead of a gross-margin-only
  filter. Explicit multi-metric questions get per-metric evidence slots and a
  wider candidate pool without increasing final top-k. Structured financial
  table rows are recognized even when their headers only appear as row-label
  metadata. A canonical Tesla FY2025 PDF regression retrieves the historical
  Q2-2025 values (gross margin 17.2%, operating margin 4.1%) rather than a
  nearby FY2025/Q4 summary.
- The approved synthetic multi-company risk contract was rerun through the
  public hybrid retrieval entry point: both requested issuers retain their
  substantive risk evidence, known third-issuer evidence is excluded, and
  safe-harbor boilerplate does not occupy the context. **4 passed**; no
  Provider/evaluator request.

## Verification

- Focused grounding, answer-policy, query-scope, and cross-format contracts:
  **45 passed**.
- Semantic-review contract suite after rubric separation:
  **15 passed** (no Provider/evaluator request).
- PDF/XLSX/DOCX/CSV format and document-loader regressions:
  **77 passed** (no Provider/evaluator request).
- Semantic-review plus frozen-report contract tests:
  **21 passed** (no Provider/evaluator request).
- EN-046 inherited-company/period retrieval regression:
  **1 passed** (no Provider/evaluator request).
- EN-045 bilingual growth-driver follow-up plus issuer-aware retrieval
  regression: **passed** (no Provider/evaluator request).
- Hybrid retrieval and period-aware retrieval suites, including the canonical
  Apple PDF retrieval integration: **36 passed** (no Provider/evaluator
  request).
- Agent Runtime, prompt, answer-policy, grounding-contract, and query-scope
  suites: **103 passed** with ``ALLOW_REAL_PROVIDER=false`` (no
  Provider/evaluator request).
- Combined changed-area suite (semantic-review/reporting, ingestion formats,
  hybrid retrieval, period-aware retrieval, and Agent Runtime):
  **142 passed**; Ruff and ``git diff --check`` pass.
- Latest cross-format, retrieval, Agent Runtime, grounding, and semantic-review
  focused suite: **181 passed**. This includes the bilingual EN-045 growth-driver
  regression and existing PDF/XLSX/DOCX/CSV canonical-fact fixtures.
- Full backend suite with plan-limit evaluation bypass disabled for the test
  process (earlier checkpoint): **2,332 passed, 23 skipped**.
- Final full backend suite with ``ALLOW_REAL_PROVIDER=false``, evaluation-plan
  bypass disabled only for the pytest process, and ordinary plan limits enabled:
  **2,341 passed, 23 skipped**, one deprecation warning. This run made no
  Provider/evaluator calls and did not modify the local ``.env``.
- Latest full backend suite after EN-045 and rerank coverage changes:
  **2,344 passed, 23 skipped**, one deprecation warning in 255.07s. The
  process used ``ALLOW_REAL_PROVIDER=false`` and made no Provider/evaluator
  calls.
- Authoritative full backend rerun for this checkpoint, with
  ``ALLOW_REAL_PROVIDER=false``, ``EVALUATION_BYPASS_PLAN_LIMITS=false``, and
  ``CHAT_PLAN_LIMITS_ENABLED=true`` explicitly set for the test process:
  **2,352 passed, 23 skipped**, one Starlette/httpx deprecation warning in
  256.82s. This was the previous full-suite checkpoint. An initial run without
  explicit plan switch values produced seven quota-test failures because the
  evaluation bypass behavior was active; the seven cases passed both in
  isolation and in this correctly configured full run. No billing
  implementation was changed.
- Latest full backend suite after the summary-evidence coverage change, using
  ``ALLOW_REAL_PROVIDER=false``, ``EVALUATION_BYPASS_PLAN_LIMITS=false``, and
  ``CHAT_PLAN_LIMITS_ENABLED=true``: **2,354 passed, 23 skipped**, one
  Starlette/httpx deprecation warning in 261.23s. No Provider/evaluator call
  was made.
- Previous hybrid retrieval + period-aware retrieval checkpoint: **37 passed**.
- Latest hybrid retrieval, period-aware retrieval, and query-scope suites:
  **41 passed**, one Starlette/httpx deprecation warning. This includes the
  public Apple/NVIDIA/Tesla PDF integrations, the multi-company risk evidence
  contract, and financial-summary scope classification.
- Latest changed-area grounding, answer-policy, hybrid/period retrieval, and
  final-answer contract suite: **84 passed**, one deprecation warning.
- Latest full backend suite after all summary and multi-metric retrieval fixes,
  with ``ALLOW_REAL_PROVIDER=false``, ``EVALUATION_BYPASS_PLAN_LIMITS=false``,
  and ``CHAT_PLAN_LIMITS_ENABLED=true``: **2,357 passed, 23 skipped**, one
  Starlette/httpx deprecation warning in 266.36s. No Provider/evaluator call
  was made.
- Ruff: **PASS**.
- ``git diff --check``: **PASS** (Git reports existing line-ending conversion
  notices for dirty files; no whitespace errors).
- Frozen 100-answer deterministic production-policy replay:
  **100/100 replayed**, **0 unsupported numeric claims after the policy**,
  **49/50 bilingual required-fact coverage pairs equal**. These are
  deterministic policy/coverage measurements, not semantic answer grades.
- Latest immutable-input replay at
  ``evaluation/results/offline_grounding_replay_20260917_v8`` again processed
  **100/100** rows and **341** input citation records with **0** unsupported
  numeric claims after policy projection. It retained historical counts of
  **33 INCORRECT / 1 FAILED** and **49/50** required-fact parity; its one
  mismatch remains frozen EN/ZH-046 because this projection intentionally uses
  only each old answer's original citations, not today's retrieval path.
- Post-date-parser immutable-input replay at
  ``evaluation/results/offline_grounding_replay_20260917_v9`` processed
  **100/100** historical rows and **341** original citation records with **0**
  final unsupported numeric claims. It preserved the requested-period sentence
  in EN-007 that v8 had replaced, retained **100%** deterministic required-fact
  coverage for the EN/ZH-007 pair, and left the frozen **33/1/223/19** labels
  unchanged. This is a grounding-policy replay, not a semantic re-grade; one
  other required-fact parity difference remains at EN/ZH-046 because replay
  intentionally uses each historical answer's original citations.
- In the frozen replay, the remaining mismatch is multi-turn ``046``: the
  historical English answer carries only Apple evidence after a Tesla
  follow-up, while the historical Chinese answer carries Tesla evidence. A new
  offline regression now proves the current deterministic planner/retriever
  selects Tesla Q2 margin evidence from mixed-company candidates, and the
  production finalizer projects the same supported facts in both languages.
  This does not alter the frozen **49/50** historical measurement or verify a
  live Docker request; no new Provider response was requested.

### 2026-09-18 offline follow-up

- Re-ran the multi-company risk regression through public
  ``HybridRetriever.retrieve`` with local synthetic chunks and a fake vector
  store: **5 passed**. Apple and Tesla each retain their own concrete risk
  evidence; unrelated NVIDIA risk content and generic safe-harbor disclaimers
  do not occupy the requested result slots. This verifies retrieval behavior,
  not generated answer quality.
- Re-ran the frozen 100-answer deterministic grounding replay into
  ``evaluation/results/offline_grounding_replay_20260918/``: **100/100**
  rows processed, **0** final unsupported numeric claims, **0** Provider or
  evaluator calls, and **$0** cost. The historical answer labels remain
  unchanged. This citation-only replay snapshot reports **48/50** required-
  fact parity pairs (EN/ZH-037 and EN/ZH-046 differ); it predates the
  current-path repair below and cannot regenerate evidence missing from the
  frozen answers.
- Applying the current deterministic citation annotation contract read-only
  to all **341** frozen citation records separates **127**
  ``UNUSED_RETRIEVED_CONTEXT`` records (122 previously labeled
  ``VALID_BUT_NOT_SUPPORTED``, 5 previously labeled
  ``VALID_SUPPORTED``), **113** cited ``VALID_SUPPORTED`` records, and
  **101** cited records retaining the old ``VALID_BUT_NOT_SUPPORTED``
  annotation. This only checks rank-marker usage and exact source/quote
  validity; it is not a semantic re-review of the 101 claims and does not
  rewrite the frozen labels.
- Fixed the reproducible ZH-037 route split: “iPhone maker” / “做 iPhone 的
  公司” now resolves to Apple in the canonical entity extractor, the runtime
  intent router reuses that extractor instead of a divergent alias map, and
  “业绩” is recognized as a company-performance cue. The bare product query
  “What is an iPhone?” remains direct chat. Planner, runtime-router,
  required-fact parity, and real Apple Q2 FY2026 PDF retrieval regressions
  pass; both language variants retrieve the same headline rows, and the
  six-month operating-cash-flow fact remains explicitly labeled as cumulative.
- The complete adjacent planning, hybrid/period retrieval, query-scope,
  citation-gate, grounding, and answer-policy suite now has **183 passed**.
  The additional runtime intent-router and AgentRuntime regressions have
  **95 passed** after centralizing company extraction; the former “unknown
  Microsoft” fixture now uses an actually unknown issuer (Acme), while
  Microsoft follows the canonical single-company route.
  Ruff, Python compilation, and ``git diff --check`` pass. Processes set
  ``ALLOW_REAL_PROVIDER=false``; no Provider/evaluator calls were made.
- Final full backend offline suite after the alias and runtime-router repairs:
  **2,365 passed, 23 skipped** in 261.82s. The process explicitly used
  ``ALLOW_REAL_PROVIDER=false``, ``EVALUATION_BYPASS_PLAN_LIMITS=false``,
  and ``CHAT_PLAN_LIMITS_ENABLED=true``; no Provider/evaluator calls were
  made.
- These offline regressions do not re-grade or modify the frozen **33
  INCORRECT / 1 FAILED / 223 VALID_BUT_NOT_SUPPORTED / 19** baseline. The
  production semantic-quality gate remains open.

### 2026-09-18 follow-up: unsupported metric fail-closed

- A production-policy defect was reproduced with synthetic local evidence:
  an unsupported request for a future stock-price target could become an
  empty answer when the retrieved Tesla filing contained an unrelated revenue
  fact. ``_compact_refusal_fragments`` had treated any fact in the ledger as
  support for the requested answer and removed the grounding refusal. It now
  removes refusal placeholders only when a required fact for this question is
  actually available and present in the completed answer.
- Specific requests for stock-price targets/forecasts, market share, and gross
  hires now remain evidence-seeking ``FACT`` queries instead of falling
  through the generic ``What is`` definition branch. The final answer policy
  now requires the metric phrase and every claimed number to co-occur in the
  same cited local source fragment. A metric word on one row and a matching
  number on another row can no longer be combined. Adjacent facts such as
  revenue, vehicle volume, or headcount cannot stand in for these metrics.
  Missing evidence yields an explicit localized insufficiency response; a
  matching cited target-price fixture remains answerable. Generic definitions
  (``What is gross margin?`` and ``什么是毛利率？``), summaries, analyses, and
  company/period-scoped ordinary financial facts retain their prior behavior.
- Added contract coverage for stock target, 2027 expected stock price, China
  market share, gross hires vs. headcount, bilingual refusal, and a genuinely
  cited price-target fact. The affected answer-policy, scope, retrieval,
  grounding, and bilingual-routing group reports **132 passed**. Ruff passes
  for changed Python modules and tests; ``git diff --check`` passes.
- Replayed the frozen 100 answers through the current deterministic
  production finalizer into
  ``evaluation/results/offline_grounding_replay_20260918_v3/``: **100/100**
  processed, **0** final unsupported numeric claims, **0** Provider/evaluator
  calls, and **$0** cost. Historical grades remain **29 CORRECT / 37 PARTIAL /
  33 INCORRECT / 1 FAILED**. Deterministic required-fact parity is still
  **48/50** (the same 037 and 046 citation-only differences); this replay is
  not a semantic re-grade and cannot repair facts absent from a frozen answer's
  cited evidence.
- Tightened the new unstructured-metric boundary after a counterexample showed
  that a keyword and a coincidentally matching number on different table rows
  could still be joined by chunk-level validation. A cited price target now
  passes only when its value is in the same local source fragment; market
  share cannot borrow a neighboring revenue percentage. Added a regression
  proving that split-row evidence fails closed. The focused suite now reports
  **133 passed**.
- Replayed once more after this stricter check into
  ``evaluation/results/offline_grounding_replay_20260918_v4/``: **100/100**
  processed, still **0** final unsupported numeric claims, **0** Provider and
  evaluator calls, and **$0** cost. Frozen grades remain unchanged and
  deterministic required-fact parity remains **48/50**.
- Full backend test run: **2,366 passed, 23 skipped, 1 failed**. The one
  failure was the existing perf-marked 10,000-increment latency assertion
  (170.38 ms vs. its 100 ms threshold during the full suite); an isolated
  rerun of that same test passed. No test was skipped or xfailed to conceal a
  failure. Provider guard was explicitly set to ``false`` throughout.
- After the same-metric/same-row grounding check was added, the complete
  non-performance backend suite was rerun with real Providers disabled:
  **2,349 passed, 23 skipped, 19 perf-marked tests deselected**, 260.85s. The
  isolated performance assertion passed separately, and the 100-answer
  offline production replay remained at zero unsupported numeric claims.
- The 19 historical bilingual grade mismatches and 223 old
  ``VALID_BUT_NOT_SUPPORTED`` annotations remain frozen. The quality/semantic
  gates remain open: deterministic grounding improvements do not establish
  that the prior model answers are semantically correct or that citations
  entail every natural-language statement.
- Read-only GitHub review was performed because the ingestion design must
  survive diverse statement layouts, not just a new embedding model. RAGFlow
  exposes parser-backend dispatch (including Docling and MinerU) in
  ``rag/app/naive.py`` and its project describes dedicated PDF/table parsing;
  Docling documents multi-format conversion, PDF layout/reading-order/table
  structure, OCR, XBRL financial reports, local processing, and structured
  JSON export. These point to a parser/provenance/validation boundary before
  embedding, plus format-specific golden ingestion tests. No dependency was
  installed and no parser migration or data reindex was performed in this
  offline repair; parser selection is a separate change to benchmark on the
  three public sample filings first. References:
  [RAGFlow parser dispatch](https://github.com/infiniflow/ragflow/blob/main/rag/app/naive.py),
  [RAGFlow](https://github.com/infiniflow/ragflow),
  [Docling](https://github.com/docling-project/docling),
  [Docling hybrid chunking example](https://github.com/docling-project/docling/blob/main/docs/examples/hybrid_chunking.ipynb).

### 2026-09-18 citation-review false-negative audit

- Rechecked the frozen ``formal_20260916`` citation ledger against the actual
  ``[Evidence N]`` markers in each answer, without changing its rows. Of 341
  annotations, **122** old unsupported labels are unused retrieved context,
  **5** old supported labels are also unused, **113** supported labels are
  actually cited, and **101** actually cited labels retain the old unsupported
  annotation. This confirms that the headline 223 is not 223 user-visible
  unsupported citations.
- Among those 101 cited/unsupported records, **41 across 20 answers** do not
  pass the evaluator's own exact-span contract: the attached claim is missing,
  too short, or not an exact main-answer substring, and/or the attached quote
  is missing, too short, or not an exact cited-chunk substring. These records
  cannot be treated as proven unsupported claims from the stored annotation.
  The other **60** have structurally verifiable quote/claim spans but still
  need a fresh local-entailment review; no semantic relabeling was performed.
- Reapplying the corrected offline annotation contract to all 341 frozen rows
  yields **113** cited ``VALID_SUPPORTED``, **127** ``UNUSED_RETRIEVED_CONTEXT``,
  **60** cited ``VALID_BUT_NOT_SUPPORTED``, and **41**
  ``REVIEW_INDETERMINATE``. This is a deterministic accounting pass over the
  stored answer markers and exact spans; it does not override or rewrite the
  frozen 223-label count and does not semantically resolve the 60 remaining
  claims.
- A reason-text scan also found **10** of the 101 records whose rationale
  explicitly discusses off-topic/tangential relevance. This is a targeted
  review queue, not a claim that those 10 citations are supported: relevance
  and entailment must be adjudicated separately.
- Fixed the *future review contract* so invalid/missing exact spans produce
  ``REVIEW_INDETERMINATE`` rather than ``VALID_BUT_NOT_SUPPORTED``. A valid
  unsupported label is retained only when both the exact cited quote and exact
  answer claim can be verified. New retest reports now display indeterminate
  annotation counts separately. Added offline tests for malformed annotations
  and for preserving a verifiable unsupported judgment. Frozen **33/1/223/19**
  labels and raw answers remain unchanged; this does not re-grade history or
  claim to have fixed natural-language answer quality.

### 2026-09-18 source-period binding and bilingual fact projection

- Strictly replayed all 100 frozen questions against the three checked-in
  public source PDFs using the current production HybridRetriever, deterministic
  retrieval probes, fact ledger, and answer finalizer. The denominator contains
  142 exact company/metric/period/value facts extracted from those PDFs.
- The v19 audit had reached 138/142 facts retrieved (97.18%) and 134/142
  projected into the final answer (94.37%). Investigating the remaining
  projection gaps exposed two implementation defects rather than a need for
  more embedding recall:
  - Tesla's Q4/FY2025 narrative states full-year operating cash flow of
    $14.7B and Q4 cash flow of $3.8B in one passage. The full-year amount was
    incorrectly assigned the filing's Q4 period. Narrative amounts now bind to
    an immediately stated annual period, while the structured Q4 table remains
    authoritative for the quarterly value ($3.813B).
  - Decimal normalization rendered $840 million as ``8.4E+2 million`` during
    deterministic completion. The final grounding pass rejected that valid
    claim, leaving an obsolete insufficiency response. User-facing normalized
    values now use plain decimal formatting; an end-to-end regression verifies
    that Tesla's supported Q4 net income survives final grounding.
- Strict audit v21: **142/142** source facts retrieved, **142/142** exact facts
  projected, **0** unsupported numeric/fact claims, and **0/50** English/Chinese
  pairs differ in source targets, retrieved facts, or context-plan facts.
  EN-021 and ZH-021 now both include Tesla Q4 net income ($840M) and Q4
  operating cash flow ($3.813B), each with period-correct evidence.
- Frozen-history production-grounding replay v30: **100/100** processed,
  **0** final unsupported numeric claims, **0** provider/evaluator calls, and
  **$0** cost. It still reports five answer-fact-coverage differences across
  50 bilingual pairs when restricted to historical citation chunks; these
  are not semantic grades and do not contradict the current full retrieval
  audit. The replay retains the original frozen grade labels unchanged.
- Focused tests after these fixes: **130 passed** (one upstream Starlette
  deprecation warning); Ruff and ``git diff --check`` passed. The strict audit
  records ``provider_calls=0``, ``evaluator_calls=0`` and ``api_cost_usd=0``.

### 2026-09-18 qualitative citation-boundary repair

- A focused NVIDIA growth-driver regression exposed two mismatched contracts:
  the main evidence filter accepted report-period metadata such as ``periods``
  while the qualitative citation selector did not read that key; separately,
  a synthetic ``Growth-driver source excerpt`` prefix was being parsed as part
  of the factual sentence, so the word ``growth`` triggered trend-direction
  checking against a verbatim source quote. Qualitative evidence selection now
  reads the same period metadata aliases as the main filter, and generated
  source excerpts use a distinct heading plus quoted, individually cited source
  passages.
- Chinese-language fallback had also discarded those verified English source
  excerpts together with untranslated provider prose. It now keeps only the
  deterministic fact projection plus the independently sourced, exact quoted
  driver passages; it does not preserve the untranslated model narrative.
- Strict qualitative sanitation now treats blank lines as layout, not as
  unsupported prose claims. This fixes a phantom unsupported-claim count when
  localized facts and source excerpts are separated by a paragraph break.
- Added/updated provider-free regressions. The focused grounding, policy,
  retrieval-probe, ledger, and query-scope suites report **147 passed**. Ruff
  reports clean and ``git diff --check`` exits successfully (Git emits only
  existing line-ending normalization warnings). One upstream Starlette/httpx
  deprecation warning remains.
- Historical raw-answer replay v31:
  ``evaluation/results/offline_grounding_replay_20260918_v31/``. All **100**
  frozen answers were replayed through current retrieval and production
  grounding with **0** Provider/evaluator calls and **$0** cost. The finalizer
  projected **142/142** audited source facts; its final unsupported numeric and
  qualitative-claim counters were both **0**. Source-fact projection differs
  for **0/50** English/Chinese pairs. These are deterministic policy/replay
  results, not semantic answer re-grades; the frozen labels remain
  **29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED**, and the paired grade
  mismatch count remains **19**. The old citation-review annotations remain
  frozen; the 60 structurally verifiable unsupported annotations still need
  source-grounded local-entailment adjudication.
- The credential-free full backend rerun initially exposed an additional
  cross-quarter leak in a mixed-company answer: after the parsed fact ledger
  scoped Tesla revenue to the filing's Q2-2025 column, raw table-number
  supplementation could re-add the neighboring Q4-2025 value. Raw numeric
  supplementation is now limited to the period/metric row when a comparative
  table is recognized, and fails closed if that row cannot be mapped. The
  existing mixed-company regression and **119** focused policy/grounding tests
  pass after the fix.
- Final full offline backend suite after that repair:
  **2,478 passed, 2 skipped, 40 deselected** (``live`` and ``perf``), with
  ``ALLOW_REAL_PROVIDER=false``; the only warning is the upstream
  Starlette/httpx deprecation.
- Historical production-grounding replay v32:
  ``evaluation/results/offline_grounding_replay_20260918_v32/``. It processed
  **100/100** answers with **0** Provider/evaluator calls and **$0** cost;
  final unsupported numeric/qualitative counters are **0/0**, source facts
  projected are **142/142**, and source-fact projection differs for **0/50**
  language pairs. The stricter quarter boundary flags **194** unsupported raw
  numeric claims versus **186** in v31; that is a conservative removal count,
  not an accuracy gain, and warrants per-claim over-sanitization review. Only
  EN-001 and ZH-035 final replay text changed from v31; all frozen semantic
  grades remain unchanged. No conclusion is drawn that the 33 incorrect,
  1 failed, 223 original citation labels, or 19 paired grade mismatches are
  resolved.
- The v32 comparison exposed that an answer bullet omitting its period was
  defaulting to the filing-level quarter even when the question explicitly
  requested one historical quarter. Numeric grounding now inherits a single
  explicit query period for unqualified answer claims; explicit periods in a
  claim still take precedence, and queries without a period still use the
  source's default/reporting-period evidence. Comparative table recovery stays
  bounded to the matching metric row/period. An offline regression verifies
  that Tesla Q2-2025 total revenue of $22,496m is retained from an unqualified
  bullet while the adjacent Q4-2025 value of $24,901m is rejected for that Q2
  query.
- Replay v33:
  ``evaluation/results/offline_grounding_replay_20260918_v33/`` processed
  **100/100** frozen answers with **0** Provider/evaluator calls and **$0**
  cost. Source facts remain **142/142**, final unsupported numeric/qualitative
  counters remain **0/0**, and source-fact projection differs for **0/50**
  bilingual pairs. Relative to v32, final text changed in five rows; notably,
  the Q2 Tesla revenue/operating-income/net-income bullets were restored for
  EN-001 and ZH-035. Raw unsupported numeric claims decreased from **194** to
  **191**. Frozen grades and the 19 paired grade mismatches remain unchanged;
  this replay is not a semantic re-grade.
- Full offline backend suite after query-period inheritance:
  **2,479 passed, 2 skipped, 40 deselected** (``live`` and ``perf``), with
  ``ALLOW_REAL_PROVIDER=false``. Ruff and ``git diff --check`` also pass; the
  only test warning is the upstream Starlette/httpx deprecation.

## Gates that remain open

The following are retained as historical findings, not claimed fixed or
re-evaluated:

```text
historical answer grades: 33 INCORRECT / 1 FAILED
historical citation review: 223 VALID_BUT_NOT_SUPPORTED
historical bilingual grade mismatches: 19
```

The historical ``223 VALID_BUT_NOT_SUPPORTED`` value is a label count under the
old rubric. That rubric required a citation to support a material claim
answering the whole question, so it did not cleanly distinguish local claim
entailment from answer relevance/completeness; additionally, old result rows
could include retrieved chunks not actually cited in the user-visible answer.
The number is preserved unchanged for auditability and is **not** reinterpreted
as either 223 proven hallucinations or 223 supported citations. A future
authorized re-review must report separate local-entailment, query-relevance,
and unused-context counts. It must not overwrite these frozen records.

The offline policy can validate exact numeric/company/period support and can
project verified requested facts. It cannot independently determine whether
all natural-language paraphrases entail their citations or whether newly
generated answers have become semantically correct. Doing so requires a
source-grounded human review or an explicitly authorized evaluator run; neither
was performed. The one frozen 046 context mismatch also remains unresolved by
answer post-processing alone.

```text
OFFLINE_REPAIR: PARTIAL
READY_FOR_DEEPSEEK: NO
```

Do not enable or call DeepSeek until the remaining offline reproducible failure
cases have been converted into and passed as regressions, and a separately
authorized review can re-evaluate semantic answer quality. No Docker rebuild,
live E2E, commit, or push was done.

## Follow-up evidence audit (2026-09-18, v34)

The latest immutable historical replay is
``evaluation/results/offline_grounding_replay_20260918_v34/``. It retains the
frozen grades and makes no Provider/evaluator calls. Across the 34 frozen
``INCORRECT``/``FAILED`` rows, 19 have at least one audited source-backed
required fact; all 19 of those rows had every such fact retrieved and
projected by the current deterministic production grounding path. The other
15 rows have no structured source-fact target in this ledger. That does **not**
prove the report lacks the requested information: qualitative claims, routing,
and knowledge-scope cases require separate source review. Thus missing report
content is a valid explanation for some cases, but cannot explain all the
known failures.

Failure-mode labels on those 34 historical rows include 27 ``Reasoning
Failure``, 23 ``Data Missing``, 21 ``Retrieval Failure``, 9 ``Citation
Failure``, and 9 ``LLM Hallucination`` (labels overlap per question). These are
the original evaluator annotations, not independently adjudicated causes.
The v34 finalizer reports zero unsupported numeric and qualitative claims and
142/142 audited source facts projected; those safety/coverage numbers do not
change the frozen semantic grades.

The previously approved public ``HybridRetriever.retrieve`` synthetic
multi-company risk check was rerun with real-provider access disabled:
**4 passed**. It confirms that, in the tested cases, each requested company’s
concrete risk evidence survives retrieval while generic safe-harbor text does
not consume the limited result slots. This is a focused regression, not proof
that every PDF layout or risk disclosure parses correctly.

The subsequent full offline backend rerun exposed three canonical-PDF
regressions that the retrieval-only risk checks did not cover: Apple revenue
performance, NVIDIA Q1 FY2027 summary, and Apple/Tesla income comparison. The
source rows were present. Root cause was intent reuse: a predicate that
allowed financial summaries to receive extractive growth-driver text was also
used to activate driver-only retrieval, removing statement rows from summary
context. Retrieval now uses a narrower explicit-driver intent while the
answer-policy layer can still add cited driver excerpts to broad summaries.
The Chinese Apple summary also exposed stale citation ranks on synthesized
English source excerpts after incompatible candidates were filtered; the
excerpt is now rebuilt against the trusted evidence order.

Verification after these repairs:

```text
focused canonical-PDF/query-intent regressions: 6 passed
full provider-disabled offline backend suite: 2,488 passed, 2 skipped, 40 deselected
Ruff (changed Python files): PASS
git diff --check: PASS
DeepSeek/provider calls: 0
```

The full suite is regression evidence, not semantic re-grading of the frozen
100 answers. Historical grades remain 33 ``INCORRECT`` / 1 ``FAILED``, and
the 19 answer-grade mismatches and citation-entailment review remain open.
The overall gate therefore remains ``OFFLINE_REPAIR: PARTIAL`` and
``READY_FOR_DEEPSEEK: NO``.

## Source-presence and bilingual scope audit (2026-09-18, v26)

The question “were the facts absent from the filings?” was checked against the
actual frozen corpus, rather than inferred from old model refusals. The local
source references confirm, for example:

- Apple Q2 FY2026 reports **$30.976B** Services net sales and says the increase
  was primarily from advertising, the App Store, and cloud services; it also
  attributes iPhone net-sales growth to higher Pro-model sales.
- NVIDIA Q1 FY2027 reports **$81.6B** total revenue and **$75.2B** Data Center
  revenue, and discusses AI factories, agentic AI, and Data Center compute and
  networking growth.
- Tesla's Q4/FY2025 update contains a historical Q2-2025 column, including
  **$22.496B** total revenue and **$16.661B** automotive revenue. That supports
  Q2 numeric answers, but does not make Q4 narrative a Q2-specific explanation;
  the answer must disclose that limitation.
- Alibaba is absent from the three-document corpus, so ZH-034 remains a
  genuine knowledge-scope case.

This confirms a mixed diagnosis: some requested narrative is not in the
selected filing/period, but several prior “evidence missing” answers were
retrieval/context failures even though the facts are present. Historical
examples include Apple Services (EN/ZH-040) and Tesla margin follow-up
(EN/ZH-046); the current deterministic source audit now finds and projects the
required values for both language variants. This is retrieval/projection
evidence, not a new semantic grade of a generated answer.

The v25 audit also exposed seven English/Chinese scope-label differences.
Generic routing rules now classify business-driver requests as analysis,
multi-company superlative rankings as comparisons, broad business-status
questions as summaries, and coreferential margin follow-ups as metric facts.
The new benchmark-wording regressions pass. After the change, the v26 local
source audit reports **142/142** required source facts retrieved and projected,
**0** unsupported projected claims, and **0/50** bilingual differences in
source targets, retrieved facts, or required-fact context plans. Scope-label
differences fell from **7 to 2**. The remaining pair 002 (“what does the report
say about revenue?” vs. “how did revenue perform?”) and pair 047 (“focus on
drivers” vs. “compare their drivers”) differ in wording/intent; the frozen
dataset was not rewritten to force artificial parity.

Verification for this change:

```text
tests/evaluation/test_query_scope.py + tests/planning/test_bilingual_financial_routing.py: 40 passed
Ruff (changed scope/test files): PASS
full provider-disabled backend suite after this change: 2,492 passed, 2 skipped, 40 deselected
current source audit v26: 142/142 retrieved and projected; provider/evaluator calls 0; cost $0
git diff --check: PASS (only line-ending normalization warnings)
```

These results do not adjudicate semantic correctness, do not alter the 19
historical answer-grade mismatches, and do not close the separate citation
entailment review.

### 2026-09-18 Chinese growth-driver wording regression

The v26 source audit showed that the filing content was present but the
English/Chinese answer paths diverged for the frozen NVIDIA Q1 FY2027 growth
question. The broad query scope was already ``ANALYSIS`` in both languages;
the narrower explicit-driver detector missed the Chinese word order
``增长的主要驱动因素`` (and the punctuation variant ``增长，主要驱动因素``).
Consequently, Chinese retrieval did not enter the driver-evidence selection
path and the answer finalizer left an insufficiency response, while the
English variant extracted the report passage.

The detector now accepts general Chinese word-order variants for main/core/key
growth drivers, causes, and drivers/power, without a benchmark ID or exact
question rule. The answer policy distinguishes an explicit financial
attribution (a financial outcome and causal link in the same source passage)
from related industry commentary. Only period/company-compatible explicit
attribution may remove a driver insufficiency statement. Context-only passages
are labeled as related filing context, explicitly not as an attribution of
reported-period growth; the insufficiency qualification is preserved. The
checked-in NVIDIA release includes commentary about AI-factory buildout and
agentic AI; it does **not** quantitatively attribute Q1 revenue growth to
those themes, so the synthesized answer presents them as source context, not
as a proven causal decomposition of the quarter.

Offline regressions now check the Chinese variants in scope and explicit
intent classification, actual ``NVIDIA_sample.pdf`` retrieval alongside its
English counterpart, and finalization through the production grounding
boundary with company/period constraints. A direct-causation fixture removes
the refusal; commentary-only evidence retains the caveat. The synthetic
safe-harbor, wrong-issuer, and wrong-period cases remain excluded. After the
direct-attribution/context distinction, source audit v28 repeats **142/142**
source-fact recall/projection, **0** unsupported projected facts, and **0/50**
bilingual source-target, retrieval, or context-plan differences. EN-009 and
ZH-009 retrieve the same NVIDIA page-1 chunk and receive the same cited source
excerpt under a “related filing context” heading; it explicitly says this is
not an attribution of reported-period growth and preserves the insufficiency
qualification.

Current-retrieval historical raw-answer replay v15 processes **100/100** rows,
projects **142/142** source facts, retains **0** final unsupported
numeric/qualitative claims, and reports **0/50** differences in exact source-
fact projection. Frozen historical grades remain **29 CORRECT / 37 PARTIAL /
33 INCORRECT / 1 FAILED**; this is not a semantic re-grade. The raw answers
still contain **187** unsupported numeric and **881** unsupported qualitative
claim fragments before final grounding, so historical answer quality is not
claimed fixed.

Verification after the context-vs-attribution change:

```text
tests/evaluation/test_query_scope.py + tests/evaluation/test_final_answer_policy.py: 69 passed
focused growth-driver / canonical NVIDIA PDF regressions: 5 passed
full backend offline suite (ALLOW_REAL_PROVIDER=false, not live/perf): 2,495 passed, 2 skipped, 40 deselected
Ruff (changed Python files): PASS
source audit v28: 142/142 retrieved and projected; 0/50 bilingual evidence-plan differences
historical replay v15: 100/100; 142/142 projected; 0 final unsupported numeric/qualitative claims
Provider calls: 0; evaluator calls: 0; API cost: $0
```

These tests prove deterministic evidence-path and grounding contracts, not
that all historical prose is semantically correct. No Provider/evaluator call
was made.

### 2026-09-18 Apple Services evidence-path regression

The Apple Q2 FY2026 Form 10-Q **does contain** the requested explanation: it
says Services net sales increased primarily due to higher net sales from
advertising, the App Store, and cloud services. The earlier English
"service-related business" wording did not retrieve that MD&A paragraph in its
final top-k context, while the Chinese wording happened to retrieve it. This
was a retrieval/coverage asymmetry, not missing filing content.

For a query that names a reportable segment, the retriever now promotes only
same-issuer, requested-segment causal passages into the bounded candidate
pool, then reserves a same-period passage beside the period-matched numeric
row when one exists. This does not make filename metadata authoritative and
does not relax company/period checks. A real-PDF regression verifies both
English and Chinese Apple Services questions retain the $30.976B row and the
three reported drivers. It also guards against treating the 10-Q cover's
"emerging growth company" checkbox boilerplate as financial-driver evidence.
The general AI-factory narrative detector also accepts the filing's closed
"buildout" spelling; it remains explicitly labeled as related context rather
than a financial causal attribution.

Verification after this retrieval-coverage change:

```text
Focused query/final-answer/real-PDF regressions: 13 passed
Ruff (changed retrieval, evidence, and regression-test files): PASS
Full provider-disabled backend suite (ALLOW_REAL_PROVIDER=false, not live/perf): 2,497 passed, 2 skipped, 40 deselected
Current source audit v29: 142/142 source facts retrieved and projected; 0 unsupported projection claims; 0/50 bilingual target/retrieval/context-plan differences
Historical raw-answer replay v16: 100/100 rows; 142/142 projected; 0 final unsupported numeric/qualitative claims; 0/50 exact source-fact projection differences
Historical grades unchanged: 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED (not semantically re-graded)
Provider calls: 0; evaluator calls: 0; API cost: $0
```

The offline evidence-path issue is fixed for the covered Apple Services
regression, but the historical 33 INCORRECT / 1 FAILED ratings and the broader
semantic citation/bilingual review remain unresolved. No Provider/evaluator
call was made.

### 2026-09-18 NVIDIA paired-margin basis and period binding

`NVIDIA_sample.pdf` page 1 explicitly reports Q1 FY2027 GAAP and non-GAAP gross
margin as 74.9% and 75.0%, respectively. The fact parser's ordinary
single-metric window treated the second margin label as a boundary, dropping
the second value. When both values were retained, positional mapping across
the whole PDF chunk incorrectly assigned the second value to a later
comparative period. In addition, summary and comparison plans used one generic
margin requirement even when retrieved evidence explicitly distinguished both
accounting bases.

The parser now preserves only this explicit paired-margin clause, qualifies
each extracted value with its corresponding GAAP basis, and binds both values
to the same period slot. Summary, comparison, and fact plans now require both
bases only when both are separately supported in the evidence. Regression
coverage checks English and Chinese final answers, summary/comparison planning,
and a page containing multiple comparative periods. A direct extraction and
production-finalizer check against the actual NVIDIA PDF confirms Q1 facts
74.9% GAAP and 75.0% non-GAAP; Q2 outlook remains separately period-scoped.

Verification after the paired-margin change:

```text
Focused final-answer / evidence-first / fact-ledger tests: 151 passed
Full backend suite with ALLOW_REAL_PROVIDER=false: 2,518 passed, 23 skipped
Ruff (changed Python files): PASS
git diff --check (changed Python files): PASS
Historical raw-answer grounding replay v19: 100/100 rows; 142/142 source facts projected; 0 final unsupported numeric/qualitative claims; 0/50 exact source-fact projection differences
EN-007, EN-010, EN-023 and Chinese pairs: both NVIDIA Q1 gross-margin bases retained
Frozen historical grades unchanged: 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED (not semantically re-graded)
Provider calls: 0; evaluator calls: 0; API cost: $0
```

The paired-margin extraction/period-binding regression is closed for the
covered filing and offline cases. This does not resolve or re-grade the
historical answer-quality failures, semantic citation support, or the full
bilingual quality audit. No Provider/evaluator call was made.

### 2026-09-18 Basis-aware source-target audit

The first current-code source audit after splitting margin requirements by
basis reported 142/148 projected facts. Inspection showed its source-target
builder selected a preferred value from all facts sharing company/metric/period
without filtering by `accounting_basis`. For a GAAP target that caused it to
select the distinct non-GAAP 75.0% value, so the correct answer was falsely
counted as missing. This was an audit/replay validation defect, not a new
retrieval or production-answer defect.

The source audit now selects target facts through the same basis-aware
requirement filter used by the production fact plan and stores basis identity
in each target. Historical replay also checks the cited answer against that
basis. Regression coverage verifies GAAP/non-GAAP target values and confirms
that swapping their labels fails projection.

Verification after the audit-target correction:

```text
Focused source-target / final-answer / evidence-first / fact-ledger tests: 153 passed
Full backend suite with ALLOW_REAL_PROVIDER=false: 2,519 passed, 23 skipped
Frontend tests: 33 passed
Frontend production build (TypeScript + Vite): PASS
Current source audit v31: 148/148 source facts retrieved and projected; 0 unsupported projected claims; 0/50 bilingual target/retrieval/context-plan differences
Historical raw-answer grounding replay v20: 100/100 rows; 148/148 basis-aware source targets projected; 0 final unsupported numeric/qualitative claims; 0/50 exact source-fact projection differences
Frozen historical grades unchanged: 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED (not semantically re-graded)
Provider calls: 0; evaluator calls: 0; API cost: $0
```

This closes the false-positive projection gap caused by dropping accounting
basis in the audit target. The historical semantic grades, citation entailment
reviews, and full bilingual answer-quality equivalence remain separate open
gates. No Provider/evaluator call was made.

### 2026-09-18 Review-scope audit: explicit source restrictions

The frozen ZH-050 question explicitly asks the assistant to use only Apple's
filings to answer a question about NVIDIA Data Center growth. The frozen
answer says no relevant evidence was found and cites nothing. However, the
historical semantic reviewer was supplied the NVIDIA PDF based on the dataset's
`company: [NVIDIA]` metadata, and its rubric did not explicitly state that a
user's allowed-source restriction takes precedence over that metadata. The
review therefore may have penalized a refusal for not using evidence outside
the requested source scope. This is an evaluator-scope risk, not proof that the
frozen grade is wrong; the historical grade remains unchanged pending a
properly scoped adjudication.

The semantic-review rubric now explicitly says that user source restrictions
are binding, and that other-company PDFs and benchmark metadata cannot override
them. A provider-free contract test locks this rule. The original frozen
criteria, answer, reviews, and grades were not edited, and no semantic re-grade
was run.

Verification:

```text
ALLOW_REAL_PROVIDER=false pytest -q tests/evaluation/test_semantic_review_contract.py: 20 passed
Ruff (semantic reviewer and contract test): PASS
git diff --check (touched evaluation files): PASS
Provider/evaluator calls: 0; API cost: $0
```

### 2026-09-23 structured comparison-growth binding and TypeSafe frontend audit

The checked-in Tesla report does contain the Q4-2025 YoY value ``-3%``. It
does **not** provide a Q2-2025 YoY value in the comparative row. The previous
parser could attach that trailing YoY cell to the wrong period when the PDF
table was flattened into text. The ledger now binds a labelled growth cell to
the last explicit period column immediately before that label and fails closed
when a multi-period row cannot prove the binding. Regression tests cover both
the real Tesla PDF and synthetic Q2/Q4 cross-period borrowing and derivation.

The current-source audit was rerun without a Provider call. It now reports
170/170 authoritative required facts retrieved and projected, with no
English/Chinese source-target or context-plan differences. The corresponding
historical replay remains a grounding replay, not a semantic re-grade: the
frozen grades are still 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED.

The requested TypeSafe review used the available ``narrow-react-prop-types``
skill because no literal ``TypeSafe`` skill is installed. Live React call
sites were checked before narrowing props. Production knowledge/chat paths now
require their live upload, refresh, and demo-question handlers; unsupported
mock-only branches were removed. Auth, health, quota, upload, task polling,
and document-delete responses now pass through runtime contract parsers before
entering typed UI state. This prevents malformed API payloads from being
accepted through unchecked generic casts.

Verification after this change:

```text
frontend contract tests: 38 passed
frontend TypeScript + Vite build: PASS
current source audit v33: 170/170 source facts retrieved/projected; 0/50 bilingual differences
historical grounding replay v21: 100/100; 170/170 projected; 0 final unsupported numeric/qualitative claims
structured Tesla growth regressions: 3 passed
Provider calls: 0; evaluator calls: 0; API cost: $0
```

This closes the proven structured-growth period-binding defect and the
frontend API/prop type-safety gaps covered above. It does not claim that the
frozen 33 INCORRECT / 1 FAILED semantic grades, 341 citation entailment
review, or full bilingual semantic audit have been re-graded or resolved.

The follow-up TypeSafe pass removed the remaining unchecked casts from the
chat, document-detail, and retrieval response boundaries. Citation, reasoning,
plan, routing, planning, execution, workflow, document, and chunk fields are
now rebuilt from validated primitives; the routed model name is preserved for
the completion UI. KnowledgeList, DocumentCard, and Sidebar props were
narrowed to the handlers used by the actual production call sites, removing
inert optional callback branches.
The shared JSON client now returns `unknown` instead of exposing a generic
unchecked `TResponse` cast, so every current endpoint must validate its own
payload before updating UI state.

Follow-up verification:

```text
frontend contract tests: 41 passed
TypeScript compiler (tsc -b): PASS
Vite production build: PASS
Provider calls: 0; evaluator calls: 0; API cost: $0
```

### 2026-09-24 TypeSafe-shaped production citation review

The `typesafe-ai` review was applied to the evidence boundary without adding a
cloud dependency or enabling a Provider. `core/typesafe_citation.py` now emits
typed, code-consumable judgments for an explicitly cited chunk:

```text
relation: SUPPORTS | CONTRADICTS | SAYS_NOTHING | FABRICATED
action:   ACCEPT   | REVIEW       | REJECT
confidence: float
```

The deterministic precheck covers exact-quote integrity when a quote is
available, company and period scope, normalized numeric values, and a
conservative qualitative overlap check. A missing quote is never treated as
proof. Unlabeled financial-table values are deliberately returned as `REVIEW`
so the existing fact ledger can resolve units and column headers; the generic
typed layer must not overrule that domain-specific parser. The production
`sanitize_answer` path records these judgments for every explicit citation,
while the existing ledger/grounding gate remains the final financial policy
owner.

This is an offline TypeSafe-shaped contract, not a claim that TypeSafe cloud
inference has been enabled. No TypeSafe API key, DeepSeek call, evaluator call,
or new network dependency was introduced.

Verification:

```text
TypeSafe citation contract + citation/grounding regressions: 117 passed, 1 warning
Provider calls: 0; evaluator calls: 0; API cost: $0
```

The historical semantic gates remain open: the frozen raw-answer grades are
still 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED, the 341 citation
entailment review is not complete, and the 19 bilingual semantic pairs have
not been re-adjudicated. Typed judgments improve observability and fail-closed
handling; they do not by themselves prove those historical semantic failures
are resolved.

### 2026-09-24 local Ollama generation boundary

For cost-free test generation, the local Ollama service was verified through
the existing OpenAI-compatible adapter using the installed
`qwen3.5-uncensored:9b-q4km` model. The test process temporarily supplied the
local base URL and a non-secret local placeholder key; production `.env`,
DeepSeek settings, and the default Provider guard were not changed.

```text
LOCAL_PROVIDER: openai-compatible Ollama endpoint
LOCAL_MODEL: qwen3.5-uncensored:9b-q4km
CONTENT_PRESENT: True
LATENCY: 83.81s (single connectivity request)
USAGE_TOTAL_TOKENS: 224
DeepSeek calls: 0
```

This verifies local generation connectivity only. It is not a formal Provider
quality score, does not replace the frozen benchmark criteria, and should not
be used to claim DeepSeek accuracy or semantic parity.

### 2026-09-24 guidance-period contamination repair

The local end-to-end probe exposed a production-path fact-binding defect that
was not visible in the earlier isolated citation checks. A single NVIDIA PDF
chunk contained both a Q1 FY2027 actuals table (`$81,615` million) and a later
Q2 FY2027 outlook (`$91.0` billion), while its carried metadata said
`Unknown`. The ledger used the table's first period for both values. The
grounding policy then correctly rejected the misbound `$91.0B` Q1 claim, but
the language fallback had no clean Q1 candidate left and dropped the valid
`$81.615B` answer.

`core/fact_ledger.py` now detects guidance/outlook cues and binds a value only
to an explicit period in that clause. If the clause has no provable period, it
keeps the fact undated rather than borrowing a comparative table header. An
explicit, non-`Unknown` metadata period remains a safe fallback for isolated
legacy chunks. This is generic period-scope logic; it does not mention EN-007,
NVIDIA, or any benchmark question ID.

Verification:

```text
guidance-period fact-ledger regressions: 3 passed
production answer-policy regression (Q1 actual + Q2 guidance): 1 passed
evaluation + retrieval suite: 411 passed, 1 warning
Ruff (changed grounding files/tests): PASS
git diff --check: PASS
WinError 1450: not observed; no system repair was required
DeepSeek calls: 0; evaluator calls: 0; API cost: $0
```

### 2026-09-24 local Ollama quality-priority probe

The local runtime was verified separately from the paid-provider gate. The
selected model was `qwen3.5-uncensored:9b-q4km` through Ollama at
`127.0.0.1:11434`, with `think=false`, an 8192-token context window, and a
bounded 2048-token output budget. `ALLOW_REAL_PROVIDER=false` remained set;
DeepSeek/evaluator calls remained zero.

The first probe exposed a real context-budget defect: the Apple summary case
assembled about 27k characters of narrative evidence, which is too large for
an 8192-context local model once the response budget is reserved. The
evidence-first context builder now accepts an optional `max_context_tokens`
budget, retains required-fact chunks first, and adds narrative chunks in
stable order until the budget is reached. The structured fact ledger remains
complete, so truncation cannot remove required numeric facts. A regression
test covers required-fact retention and overflow exclusion.

The local five-case probe (`EN-007`, `EN-019`, `ZH-008`, `ZH-013`, `ZH-044`)
then completed 5/5 with no empty output and zero final unsupported numeric
claims. This is a local-model/pipeline compatibility result, not a DeepSeek
smoke or a semantic regrade of the historical 100-question labels. Raw and
final probe artifacts are under the ignored runtime directory
`evaluation/results/local_ollama_quality_probe_20260924_v3/`.

The first bounded probe was intentionally audited rather than accepted at
face value: EN-019 still reached the model's 8192-token ceiling because the
ledger rendered every candidate-derived fact even after narrative truncation.
The constrained context path now renders only facts required by the current
plan, while retaining the complete in-memory ledger for grounding and audit.
The probe also treats `done_reason=length` as a failed/truncated generation;
it is never counted as an application success.

The resulting v7 probe (`context_tokens=4096`, `max_tokens=2048`) reports:

```text
cases: 5
application_success: 5
empty_output: 0
output_truncated: 0
final_unsupported_numeric_claims: 0
paid_provider_calls: 0
```

### 2026-09-24 scope-aware offline replay contract repair

The production answer policy already treats ``GENERAL_CONCEPT`` questions as
Direct Chat: it strips accidental filing citation markers, keeps explanatory
examples, and returns no filing citations. The historical 100-question replay
had a separate post-check that unconditionally re-ran every final answer
through the financial citation gate. That made educational examples such as
``100 - 60 = 40%`` look like unsupported financial claims, even though the API
would not apply that gate to the same question.

The replay post-check now follows the same scope contract as production: it
uses the production ``GroundingResult`` for general-concept turns and keeps
the strict financial post-check for financial turns. This is a diagnostic
correctness fix, not a relaxed financial gate. A regression test covers the
Chinese gross-margin definition (ZH-044) with no citations.

Provider-free replay evidence against the v57 current-source audit:

```text
artifact: evaluation/results/current_policy_replay_20260924_v85_scope_aware/
questions: 100
source facts available/retrieved/projected: 310/310/310
source-fact projection coverage: 100%
final unsupported numeric claims: 0
final unsupported qualitative claims: 0
English/Chinese source-fact projection differences: 0
real provider calls: 0
evaluator calls: 0
API cost: $0
```

The frozen semantic labels remain unchanged (39 CORRECT / 25 PARTIAL /
35 INCORRECT / 1 FAILED in this source set); this replay is a grounding and
policy check, not a new semantic grade. The separate frozen-formal replay now
also applies the same scope rule and reports zero final unsupported numeric
claims, while its legacy source snapshot still has seven deterministic
required-fact parity differences. Those differences are not used to claim
semantic accuracy; the current-source audit is the authoritative parity check.

Regression evidence:

```text
replay/policy focused tests: 104 passed, 1 warning
Ruff (changed replay files): PASS
git diff --check: PASS
DeepSeek/provider calls: 0
```

### 2026-09-24 major-segment coverage, bilingual probes, and flattened-table operand repair

The next source audit exposed three generic gaps in broad segment questions. The
required-fact plan kept only segment rows and dropped consolidated context;
Chinese segment-overview retrieval did not reserve issuer-scoped headline rows;
and flattened Apple comparison tables could give a quarter request a cumulative
YTD operand when deriving YoY. The repair is intent-based (major/summary/compare
segment overviews), not benchmark-ID-specific:

* broad segment overviews retain available revenue, net income, margin, EPS and
  (when disclosed) six-month operating-cash-flow context;
* each named issuer receives segment and headline retrieval probes, including
  Chinese queries;
* segment comparisons receive period-compatible filing driver excerpts for each
  named issuer;
* revenue operand selection prefers the quarter cluster over a cumulative
  duplicate when table-column metadata is flattened.

The production-path regression suite now covers the two-company driver excerpt,
headline context, Chinese segment probes, and the cumulative-operand case.

Provider-free source audit:

```text
artifact: evaluation/results/current_source_retrieval_audit_20260924_v57_zh_segment_probes/
required facts: 310
source facts retrieved: 310/310 (100%)
source facts projected: 310/310 (100%)
unsupported numeric/fact claims in projection: 0
English/Chinese source-fact parity differences: 0
provider/evaluator calls: 0/0
```

The current ZH-024 projection contains Apple Q2 FY2026 segment values and
drivers, Apple consolidated revenue/net income/EPS/margins and six-month cash
flow, plus NVIDIA Q1 FY2027 revenue/net income/margins/EPS and Data Center/Edge
Computing values and drivers. ZH-011 and EN-011 now project the same NVIDIA
headline and segment facts without cross-company contamination.

The local Qwen3.8 production-shaped probe was rerun after these changes:

```text
artifact: evaluation/results/local_ollama_quality_probe_20260924_qwen38_v58/
model: srchmnmichael/Qwen3.8-Uncensored:Q4_K_M
context_tokens: 8192
application_success: 5/5
empty_output: 0
output_truncated: 0
final_unsupported_numeric_claims: 0
real_provider_calls: 0
paid_provider_calls: 0
```

The local replay also confirmed that the erroneous Apple ``-56.39%`` YoY
claim is removed by the current deterministic policy; the verified projection
uses the quarter-to-quarter-comparable ``16.6%`` value. The direct-chat replay
for ZH-044 now passes no filing evidence and returns a citation-free definition.
The local semantic reviewer remains diagnostic only: long Chinese answers can
occasionally fail its JSON-output contract, so that reviewer is not presented
as a semantic release gate. Frozen historical labels remain unchanged at
``29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED``.

Final offline verification for this repair:

```text
full offline pytest: 2598 passed, 23 skipped, 1 warning
frontend tests: 41 passed
frontend build: PASS
Ruff: PASS
git diff --check: PASS
Docker services: 6 healthy
health/ready: 200/200
recent backend/worker secret, paid-provider, and WinError 1450 log hits: 0
DeepSeek/provider calls: 0
```

This closes the reproduced retrieval, period-binding, grounding, and direct
chat routing defects. It does not claim the frozen 100-question semantic
accuracy labels have changed, and it does not authorize a DeepSeek run.

Runtime verification after the final backend/worker rebuild:

```text
docker compose config -q: PASS
frontend: healthy
backend: healthy
agent-worker: healthy
postgres: healthy
redis: healthy
chromadb: healthy
/api/v1/health: 200
/api/v1/ready: 200
recent migration log: PASS
recent Secret/paid-provider/WinError 1450 pattern scan: NONE
frontend tests: 41 passed
frontend build: PASS
full Ruff: PASS
git diff --check: PASS (CRLF normalization warnings only)
```

The same probe exposed and covered a second source-period defect in Apple's
Q2 table: quarterly and six-month net income shared the `Q2_2026` label.
Duration-aware grounding now rejects the six-month net-income value for an
unqualified quarterly summary while preserving the explicitly requested
six-month operating cash-flow total. The regression prevents `71,675` from
being presented as quarterly net income and retains the correct `29,578`.

### 2026-09-24 reported-growth display-unit repair

The current-source historical replay found one deterministic projection gap in
the Tesla automotive summary pair (EN-039/ZH-039). The parser correctly
extracted the reported Q4-2025 YoY value `-11%`, but the growth fact inherited
the base revenue row's amount-only `display_unit= million`. Completion rendered
that percentage as `-11 million`, after which grounding correctly rejected it.

`_growth_fact` now clears the amount display hint whenever it creates a
percentage growth fact. The regression covers both the ledger invariant and
the final answer contract (`-11%` is retained and `-11 million` is impossible).

The latest provider-free replay using the v33 current-source audit reports:

```text
source fact targets: 170
source facts projected: 170
projection coverage: 100%
final unsupported numeric claims: 0
final unsupported qualitative claims: 0
English/Chinese source-fact projection differences: 0
historical semantic grades: unchanged 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED
DeepSeek/evaluator calls: 0; API cost: $0
```

The post-change source audit (`evaluation/results/current_source_retrieval_audit_20260924_v43/summary.json`)
remained at 192/192 source-available required facts retrieved and projected,
0 unsupported projected claims, and 0 bilingual source/context differences.

The same release replay also exposed a parser synonym gap in NVIDIA's release:
the prose label `earnings per diluted share` was not included in the EPS alias
set even though retrieval supplied the chunk. The fact ledger now recognizes
that ordering (including the paired GAAP/non-GAAP values), and the regression
asserts both `$2.39` and `$1.87` are recovered without borrowing share-count or
net-income rows.

### 2026-09-24 local historical failed-case regrade

The frozen 34-case historical failure set was replayed with the local
`qwen3.5-uncensored:9b-q4km` model at `num_ctx=8192` through the current
retrieval, prompt, grounding, and sanitizer path. No paid provider or
evaluator was called. All 34 local application replays completed without a
runtime error and retained zero unsupported numeric claims. The previous
summary over-answering defect was reproduced and then removed by the narrow
FACT/SUMMARY growth planning guard.

```text
artifact: evaluation/results/local_ollama_historical_regrade_20260924_v2/
cases: 34
application_success: 34/34
final_unsupported_numeric_claims: 0
DeepSeek/evaluator calls: 0; API cost: $0
```

`ZH-050` remains a knowledge-scope case: the prompt explicitly restricts
evidence to Apple's filings while asking about NVIDIA. The production gate
rejects the NVIDIA chunks instead of emitting a wrong-company citation. The
frozen historical label expected the opposite behavior; that conflict is
reported, not hidden or “fixed” by weakening the source-only constraint.

This closes the reproducible growth-rendering defect; it is not a semantic
re-grade of the frozen historical answers.

Post-fix regression verification:

```text
full backend pytest: 2546 passed, 23 skipped, 1 warning
Ruff: PASS
git diff --check: PASS (existing CRLF normalization warnings only)
DeepSeek/evaluator calls: 0
```

The same full production RAG path was then exercised with local Ollama
(`qwen3.5-uncensored:9b-q4km`, native `think=false`, temporary `num_ctx=16384`)
without changing repository Provider settings. It returned the Q1 actual as
`81.615 billion USD` and did not expose the Q2 `$91B` guidance as the Q1 value;
the final grounding result had zero unsupported claims. This is a local-model
integration probe, not a DeepSeek release gate or a semantic benchmark pass.

The subsequent Qwen3.8/8192 local five-question probe also exposed a smaller
grounding presentation defect: a cited qualitative risk sentence mentioning
the product identifier ``4680 cells`` was treated as a financial amount and
replaced by ``Insufficient evidence to support this numeric claim.``. The
sanitizer now distinguishes currency/scale/percentage/financial-metric claims
from bare product identifiers and validates the latter through the qualitative
evidence path. The identifier remains visible when its cited passage supports
the sentence; unsupported financial amounts remain fail-closed.

Verification:

```text
product-identifier qualitative grounding regression: PASS
evaluation + retrieval suite before this change: 411 passed, 1 warning
DeepSeek calls: 0; evaluator calls: 0; API cost: $0
```
### 2026-09-24 quality-priority 8192 follow-up: flattened margin table basis

The local Qwen3.8 probe at `num_ctx=8192` exposed a production-path omission
for the generic NVIDIA Q1 FY2027 margin question. Retrieval contained both
reported values (GAAP 74.9% and non-GAAP 75.0%), but flattened PDF table rows
did not retain the accounting-basis header in each ledger fact. The generic
margin plan therefore saw one unqualified metric and the final projection
kept only one value. This was not missing source data.

`FactLedger` now inherits the nearest explicit `GAAP`/`Non-GAAP` table header
for margin rows when the row text itself has no basis label. The plan can then
require one fact per accounting basis and the production finalizer emits both
values with their original evidence ranks. Regression coverage includes both
the ledger parse and final answer contract; no provider call is needed.

The same probe also verified that removed raw-provider claims are retained in
the raw grounding/removed-lines audit fields rather than counted as claims in
the user-visible final grounding gate. A follow-up EPS regression fixed the
numeric classifier to recognize compact canonical metric ids such as `EPS`;
the value remains subject to the exact evidence validator.

Final verification after these fixes:

```text
full backend pytest: 2545 passed, 23 skipped, 1 warning
evaluation + retrieval: 415 passed, 1 warning
frontend contract tests: 41 passed
frontend TypeScript + Vite build: PASS
Ruff: PASS
git diff --check: PASS (CRLF normalization warnings only)
DeepSeek calls: 0; evaluator calls: 0; API cost: $0
```

### 2026-09-24 quality-priority local Ollama probe at 8192 context

With the local runtime switched to quality priority, the fixed five-question
probe was rerun against Ollama `qwen3.5-uncensored:9b-q4km` using the native
`num_ctx=8192`, `think=false`, and a bounded `num_predict=2048`. This remains
strictly local; the paid-provider guard stayed disabled throughout.

Results (`evaluation/results/local_ollama_quality_probe_20260924_v8/`):

```text
cases: 5
application success: 5/5
empty output: 0
output truncated: 0
final unsupported numeric claims: 0
raw unsupported claims removed by production grounding: 40
DeepSeek/evaluator calls: 0; API cost: $0
```

The raw-claim count is intentionally reported: it demonstrates that the
grounding/sanitizer layer is still doing safety work and must not be mistaken
for a semantic re-grade of the frozen 100-question benchmark.

Runtime verification after the probe:

```text
frontend, backend, agent-worker, postgres, redis, chromadb: running/healthy
/api/v1/health: HTTP 200 (database/redis/chroma: ok)
/api/v1/ready: HTTP 200 (database/redis/chroma: ok)
ALLOW_REAL_PROVIDER: false
```

### 2026-09-24 growth-narrative comparison and source-constraint repair

The current-source replay exposed a reproducible retrieval defect for
questions such as “Which of Apple, NVIDIA and Tesla reports the strongest
growth narrative?”. The classifier recognized only explicit causal-driver
wording, so the comparison fell back to statement probes and could select an
Apple certification page instead of Apple’s reported growth commentary. The
retriever now recognizes growth-narrative intent, adds growth/MD&A probes,
reserves one narrative evidence slot per issuer, and prefers explicit
financial-attribution passages over filing-cover text. A regression using
three synthetic issuers and a real three-PDF replay protects the behavior;
the replay now returns Apple Services growth, NVIDIA growth commentary, and
Tesla operating/revenue-change evidence.

Explicit source-only wording is also fail-closed. For example, a request for
NVIDIA revenue that says “use only Apple’s financial reports” no longer falls
back to a rejected NVIDIA chunk; the citation gate returns insufficient
evidence instead. This prevents a valid third-party source from being shown as
support for a prohibited source scope.

Verification after the repair:

```text
focused citation/retrieval/query-scope/finalizer tests: 146 passed, 1 warning
Ruff (changed backend/retrieval/tests): PASS
git diff --check: PASS (existing CRLF normalization warnings only)
DeepSeek/evaluator calls: 0; API cost: $0
```

The same repair also covers a local-model language mismatch on qualitative
comparisons: if an English question receives Chinese prose, the finalizer now
keeps the cited, source-language growth passages instead of reducing the
response to a generic refusal or reintroducing unsupported numbers. A focused
regression covers this case and preserves the existing strict numeric
language-safety behavior.

### 2026-09-24 quality-priority replay and follow-up comparison repair

The local historical replay was repeated with Ollama `qwen3.5-uncensored:9b-q4km`,
native `num_ctx=8192`, `think=false`, and `ALLOW_REAL_PROVIDER=false`. No
DeepSeek or evaluator request was made. The replay confirmed that unsupported
market-share, hiring-count, and price-target questions remain fail-closed.

Two additional production-path defects were closed:

* A driver question with only general AI/management commentary no longer turns
  that commentary into a reported-period financial cause. The answer keeps a
  deterministic limitation and, when safe, a cited background excerpt; a
  structured segment fact may still be projected independently.
* A follow-up such as “Now compare it with Tesla” after “Analyze Apple's
  report” now expands the bounded metric probes and the comparison fact plan
  across both issuers. This prevents Apple certification chunks from crowding
  out Apple financial rows.

Current-source audit after the follow-up repair:

```text
evaluation/results/current_source_retrieval_audit_20260924_v40/
provider_calls: 0
evaluator_calls: 0
source fact retrieval: 192/192
source fact projection: 192/192
unsupported numeric/fact projection: 0
bilingual retrieval/context differences: 0
```

Provider-free local replay artifacts:

```text
growth comparison (EN-022/ZH-022): 2/2 application success; final unsupported claims: 0
follow-up/driver replay (EN-048/ZH-048/ZH-036/EN-045): 4/4 application success; final unsupported numeric claims: 0
EN-048 at 8192 context: Apple and Tesla core comparison facts projected
DeepSeek/evaluator calls: 0; API cost: $0
```

The frozen semantic labels (33 INCORRECT / 1 FAILED) remain historical labels;
the local model replay is diagnostic evidence, not a paid-provider semantic
re-grade and does not change the benchmark expected answers.

### 2026-09-24 quality-priority contextual comparison projection

With the local Qwen context raised to 8192, the Chinese `ZH-048` replay still
showed a reproducible presentation defect: the source facts were correct, but
the provider draft repeated alternate table values and attached a large,
non-deterministic citation list. The issue was not missing filing content. A
contextual follow-up comparison now uses the verified fact ledger whenever at
least one required fact is available, projects only those facts, and states
which requested metric is absent from the cited filing. This path is narrowly
limited to resolved follow-up comparisons and does not alter qualitative or
standalone comparison answers.

Regression coverage:

```text
contextual follow-up partial compare projection: PASS
EN-048/ZH-048 local Qwen replay (num_ctx=8192): 2/2 application success
final unsupported numeric claims: 0
full offline pytest after this change: 2559 passed, 23 skipped, 1 warning
DeepSeek/evaluator calls: 0; API cost: $0
```

### 2026-09-24 fiscal-quarter YoY binding and risk-context hardening

The Apple comparative statement uses explicit fiscal keys such as
`Q2 FY2026` and `Q2 FY2025`. The deterministic YoY planner previously only
recognized calendar-style `Q2_2026`, so a matching prior-fiscal-quarter
operand could be parsed but not used for a requested growth claim. The
period helper now supports both spellings and the answer grounding layer
admits only the matching prior-year operand for an explicit YoY clause. A
comparative row's unrelated quarter/YTD percentage is rejected rather than
borrowed.

Document-level risk sections are treated as related context only when the
issuer and period provenance are safe: an explicit conflicting period or an
unknown period on a filename that merely resembles the requested period is
not accepted as quarter-specific evidence. The final answer keeps the
source excerpt with a non-period-specific caveat when that is the only safe
evidence.

Verification:

```text
Apple fiscal-quarter comparative YoY contract: PASS
period-specific risk and comparative-column regressions: PASS
Ruff (changed backend/retrieval/tests): PASS
current-source audit: evaluation/results/current_source_retrieval_audit_20260924_v42/
provider_calls: 0
evaluator_calls: 0
source facts retrieved/projected: 192/192 and 192/192
unsupported projection claims: 0
bilingual source retrieval/context differences: 0
```

The checked-in semantic-repair fixture still contains mojibake Chinese text;
that fixture is not rewritten as part of the production repair and can fail
its language-specific assertion independently of the current source audit.

### 2026-09-24 narrow-fact overanswering guard

A Q1 FY2027 revenue question sharing a chunk with NVIDIA's Q2 guidance was
being expanded into an unsolicited YoY requirement. When the source exposed
current/prior operands but did not report a percentage directly, the finalizer
correctly kept the Q1 revenue yet appended an unnecessary insufficient-evidence
notice for the derived percentage. FACT plans now add YoY/QoQ requirements only
when the question explicitly asks for a change or comparison; SUMMARY plans
retain their existing reported-growth completion behavior.

Verification:

```text
Q1 actual with same-chunk Q2 guidance: PASS
focused grounding/citation regressions: 5 passed
full offline pytest: 2563 passed, 23 skipped, 1 warning
DeepSeek/evaluator calls: 0; API cost: $0
```

### 2026-09-24 EPS narrative alias and complete source audit

The NVIDIA Q1 FY2027 release states GAAP and non-GAAP earnings as
“earnings per diluted share”. The fact-ledger aliases previously recognized
“diluted earnings per share” but not this equivalent narrative form, so the
retrieved evidence was present while the structured source-of-truth plan
omitted EPS. The parser now recognizes the alias and binds the paired GAAP
/ non-GAAP values to the same reporting period without borrowing net-income or
share-count rows.

Verification:

```text
EPS narrative parser regression: PASS
full offline pytest: 2565 passed, 23 skipped, 1 warning
current-source audit: evaluation/results/current_source_retrieval_audit_20260924_v44/
documents parsed: 3
required facts: 194
source facts retrieved/projected: 194/194 and 194/194
unsupported numeric/fact projection: 0
bilingual retrieval/context differences: 0
DeepSeek/evaluator calls: 0; API cost: $0
```

The quality-priority local Ollama setting (`qwen3.5-uncensored:9b-q4km`,
`num_ctx=8192`) is permitted for offline diagnostic replay only. It does not
change the deterministic parser, grounding policy, or the disabled
DeepSeek gate. The ZH-050 source-only conflict remains classified as
`KNOWLEDGE_SCOPE`; the system must not cite NVIDIA evidence when the question
explicitly restricts sources to Apple filings.

### TypeSafe-shaped audit (provider-free)

The TypeSafe review was applied as an architecture check, not as an external
provider call. The production path follows the safe typed-judgment pattern:
candidate spans and source facts are found by code, citation checks return a
closed relation/action judgment (`SUPPORTS`, `REVIEW`, `REJECT`), and the
financial ledger remains the authority for numeric normalization, period,
company, metric, and table-column validation. Ambiguous qualitative overlap is
auditable `REVIEW`; it is never promoted to proof. This preserves the
provider-free gate and prevents a local model's confidence or prose from
inventing a financial value.

The follow-up local replay used the user's quality-priority Qwen runtime with
`num_ctx=8192` and `max_tokens=3072`: EN-007 completed with zero unsupported
numeric claims, ZH-050 completed with the expected source-only insufficiency,
and EN-037 still hit `LOCAL_MODEL_OUTPUT_TRUNCATED`. That last result is a
local generation-budget diagnostic, not a paid-provider or grounding verdict;
it is retained as an explicit limitation rather than being counted as a
successful semantic re-grade.

### 2026-09-24 accounting-basis preservation and runtime verification

The quality-priority local replay exposed a deterministic ambiguity in broad
financial comparisons: a prose chunk containing both ``GAAP net income`` and
``non-GAAP net income`` lost the basis label when the metric window began at
the shared ``net income`` alias. Preferred-fact selection could then choose
the larger non-GAAP value by magnitude. The fact ledger now restores an
explicit nearest GAAP/non-GAAP qualifier for scoped net-income, operating-
income, and EPS prose values, and default net-income selection scores that
qualifier. It also binds paired sentences such as ``GAAP and non-GAAP net
income were X and Y, respectively`` to the corresponding value. It does not
infer a basis from a filename, question, or numeric magnitude. Regressions
verify that an unqualified broad comparison keeps one default GAAP value and
does not repeat the non-GAAP value.

Verification:

```text
accounting-basis focused regressions: 5 passed
full offline pytest: 2568 passed, 23 skipped, 1 warning
frontend contract tests: 41 passed
Ruff (changed backend/retrieval/tests): PASS
current-source audit: evaluation/results/current_source_retrieval_audit_20260924_v45/
documents parsed: 3
required facts: 194
source facts retrieved/projected: 194/194 and 194/194
unsupported numeric/fact projection: 0
bilingual retrieval/context differences: 0
historical production replay: evaluation/results/offline_grounding_replay_20260924_v46/
historical labels unchanged: 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED
replay final unsupported numeric claims: 0 (not a semantic re-grade)
local Qwen probe: evaluation/results/local_ollama_quality_probe_20260924_v46/
local cases: 5/5 application success; empty/truncated: 0/0; final unsupported numeric: 0
local historical comparison replay: evaluation/results/local_ollama_historical_regrade_20260924_v47/
10/10 application success; final unsupported numeric: 0; paid-provider calls: 0
DeepSeek/evaluator calls: 0; API cost: $0
Docker: six services running/healthy; /health 200; /ready 200
ALLOW_REAL_PROVIDER in backend: false
recent-log secret scan: NO
git diff --check: PASS (CRLF normalization warnings only)
```

After adding the paired-value parser regression, the non-overwriting source
audit was repeated at
``evaluation/results/current_source_retrieval_audit_20260924_v46/`` with the
same result: 194/194 authoritative facts retrieved and projected, zero
unsupported projected claims, and zero bilingual retrieval/context
differences. The backend and worker images were rebuilt and recreated without
tearing down or deleting any volumes; all six Compose services remained
healthy and the real-provider guard remained disabled.

The follow-up source audit after the risk-gate change is
``evaluation/results/current_source_retrieval_audit_20260924_v47/``; it still
reports 194/194 authoritative facts retrieved and projected, zero unsupported
projection claims, and zero bilingual retrieval/context differences.

### 2026-09-24 document-level risk context with period caveat

The Tesla risk section is a document-level forward-looking disclosure in a
known Q4/FY2025 filing, while the user may ask about the historical Q2 column.
When the upload is named only ``Tesla_sample.pdf``, the earlier gate treated
the absent filename period as proof that the risk chunk was unusable. The gate
now accepts a known-period document-level risk section as ``related_context``
and forces the final response to disclose that it is not period-specific. A
chunk with unknown period metadata still fails closed; a conflicting explicit
period in the content is still rejected. This distinguishes generic risk
context from a claim about Q2 risks without allowing filename-based period
inference.

Verification:

```text
risk gate/finalizer regressions: 5 passed
EN-006 local production-path replay: application success; final unsupported numeric claims: 0
DeepSeek/evaluator calls: 0
```

The follow-up local replay at
``evaluation/results/local_ollama_historical_regrade_20260924_v50/`` also
confirmed that the Tesla risk response now contains complete source sentences
rather than mid-word PDF fragments, while retaining the period caveat.

The frozen historical grade counts and the five deterministic bilingual
required-fact parity differences remain unchanged because that artifact is a
replay of prior answers/evidence, not a fresh model re-grade. The repair is
therefore evidence for parser and production-grounding safety, not a claim
that the historical 100-question semantic score has been rewritten.

### 2026-09-24 quality-priority risk comparison fallback

The quality-priority local Qwen replay exposed a production-output failure in
the Chinese Tesla/Apple risk comparison path: the model produced a long
multi-section paraphrase, but the qualitative citation gate could not prove
each paraphrase against the retrieved chunks. The old final response retained
empty numbered headings and a dangling fragment beside a refusal. This was not
evidence that the filings contained no risks; it was an evidence-to-prose
alignment failure.

The finalizer now removes only empty outline markers after claim grounding. If
a substantial risk answer collapses to a refusal while trusted risk evidence
exists, it falls back to a bounded, issuer-labelled verbatim excerpt and runs
the same citation gate again. Source excerpts are explicitly exempted from
the model-language mismatch check, so a Chinese answer may safely include the
original English filing sentence without adding an unsupported translation.
The fallback is scope- and evidence-driven; it does not identify benchmark
question IDs or lower the citation standard.

Verification:

```text
finalizer/citation focused regressions: 96 passed
full offline pytest: 2569 passed, 23 skipped, 1 warning
local Qwen ZH-025 replay (qwen3.5-uncensored:9b-q4km, num_ctx=8192):
  application success: 1/1
  final unsupported numeric claims: 0
  final unsupported claims: 0
  paid-provider calls: 0
artifact: evaluation/results/local_ollama_historical_regrade_20260924_v55/
Ruff: PASS
git diff --check: PASS (CRLF normalization warnings only)
frontend contract tests: 41 passed
frontend build: PASS
Docker: six services running/healthy; /health 200; /ready 200
ALLOW_REAL_PROVIDER in backend: false
recent-log secret scan: NO
```

The frozen semantic label for ZH-025 remains unchanged in the replay artifact;
the local run above verifies production grounding safety and evidence use, not
a retroactive semantic re-grade. DeepSeek and evaluator calls remain disabled.

### 2026-09-24 quality-priority structural cleanup and production verification

The finalizer now also removes provider-produced structural residue that is not
a financial claim: empty outline headings, truncated comparison tails such as
``chip vs [Evidence...]``, and affirmative inference phrases that are not
supported by the cited evidence. These removals are retained in
``FinalAnswer.removed_lines`` for auditability; the raw local-model answer is
never overwritten. A language-safety fallback is represented as a grounded
refusal rather than an unsupported claim.

The frozen local Qwen raw fixtures from
``evaluation/results/local_ollama_historical_regrade_20260924_v56/`` were
replayed through the current production finalizer without any new model or
paid-provider call. The deterministic replay artifact is
``evaluation/results/local_ollama_historical_regrade_20260924_v57_deterministic/``.
It covers 34 historical raw answers and reports zero final unsupported claims,
zero final unsupported numeric claims, and zero remaining structural fragments.
This does not rewrite the frozen historical semantic labels (still
29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED); it verifies the current
grounding/sanitizer path against those preserved raw fixtures.

A subsequent finalizer replay at
``evaluation/results/local_ollama_historical_regrade_20260924_v58_deterministic/``
also removes generated generic numeric-refusal placeholders when at least one
requested ledger identity is available. It keeps refusals for unstructured
metrics with no matching ledger fact (for example market share or hiring
counts), so this is not a blanket refusal suppression.
Across the 34 preserved local raw fixtures, the current plan contained 109
required fact slots; 103 were available in trusted evidence and all 103 were
present in the final answer. The remaining six slots were unavailable in the
source evidence and were not fabricated.

Verification:

```text
finalizer/citation focused regressions: 99 passed, 1 warning
TypeSafe/local-probe/finalizer focused tests: 110 passed, 1 warning
full offline pytest: 2575 passed, 23 skipped, 1 warning
frontend contract tests: 41 passed
frontend build: PASS
Ruff: PASS
git diff --check: PASS (CRLF normalization warnings only)
Docker rebuild: backend and agent-worker rebuilt/recreated without down or volume deletion
Docker: frontend, backend, agent-worker, postgres, redis, chromadb running/healthy
/api/v1/health: 200
/api/v1/ready: 200
Alembic startup migration: observed
ALLOW_REAL_PROVIDER in backend: false
recent-log secret scan: NO
DeepSeek/evaluator calls: 0; API cost: $0
```

The runtime health payload reports database, Redis, and Chroma as ``ok``. The
embedding model remains ``not_loaded`` until an embedding operation is needed;
this is lazy loading, not a health failure. No real Provider smoke or 100Q
benchmark was run while the paid-provider prohibition remained in force.

### 2026-09-24 local Qwen quality-priority probe

The local Ollama runtime was checked directly rather than inferred from the UI:
the active process reported context ``8192``. Two provider-free five-case
probes then used the current prompt, retrieval, and production finalizer:

```text
qwen3.5:9b-q4_K_M, context 8192:
  5/5 application success
  empty output: 0
  truncated output: 0
  final unsupported numeric claims: 0
  artifact: evaluation/results/local_ollama_quality_probe_20260924_v59_qwen35_canonical/

srchmnmichael/Qwen3.8-Uncensored:q4_K_M, context 8192:
  5/5 application success
  empty output: 0
  truncated output: 0
  final unsupported numeric claims: 0
  artifact: evaluation/results/local_ollama_quality_probe_20260924_v57_qwen38/
```

The probe prefers the frozen UTF-8 dataset question and rebuilds any follow-up
marker instead of trusting a stale audit-row copy. This keeps model input
independent of Windows console rendering. The saved JSON artifacts contain the
Unicode code points for the Chinese questions and answers; no paid Provider
call was made.

### 2026-09-24 TypeSafe citation review and 100-case local replay

The production sanitizer now treats an explicitly cited TypeSafe ``REVIEW``
judgment as unresolved prose instead of silently promoting it to supported
evidence. A REVIEW line is retained only when it is an exact, explicitly quoted
excerpt; numeric and table claims continue through the financial ledger and
column-aware validators. The policy records the typed judgment and the removed
line for auditability. DeepSeek remains disabled.

The full offline suite after this change is green:

```text
full offline pytest: 2576 passed, 23 skipped, 1 warning
TypeSafe/grounding/local-probe focused tests: 157 passed, 1 warning
Ruff: PASS
git diff --check: PASS (CRLF normalization warnings only)
```

The current local-Qwen 100-case replay used ``qwen3.5:9b-q4_K_M`` with an
8192-token context and no paid Provider calls. The first pass completed 99/100;
ZH-024 reached the configured local output limit and was rerun once with a
larger local output budget (no DeepSeek retry). After that targeted retry:

```text
cases attempted: 100
application success after local retry: 100/100
final unsupported claims: 0
final unsupported numeric claims: 0
paid Provider calls: 0
artifacts:
  evaluation/results/local_ollama_historical_regrade_20260924_v63_full_qwen35_typesafe/
  evaluation/results/local_ollama_historical_regrade_20260924_v64_zh024_typesafe/
```

This replay is a production-path grounding and local-model regression check,
not a claim that the frozen historical semantic labels have been retroactively
fixed. Those preserved labels remain ``29 CORRECT / 37 PARTIAL / 33 INCORRECT /
1 FAILED`` until an explicitly authorized evaluator/Provider run is performed.

Docker was rebuilt/recreated for ``backend`` and ``agent-worker`` without
stopping the stack or touching volumes. All six services are healthy;
``/api/v1/health`` and ``/api/v1/ready`` both return 200. The backend flag is
``ALLOW_REAL_PROVIDER=false`` and the recent backend/worker log scan found no
secret or token leakage.

### 2026-09-24 follow-up: no-evidence and multi-company coverage fixes

Two additional reproducible policy gaps were closed offline:

1. The local historical replay's zero-evidence branch previously recorded an
   empty final answer even though the production API returns a deterministic
   localized insufficiency response. The replay now calls the same finalizer in
   that branch. ZH-034 replay is non-empty, contains no unsupported claims, and
   makes no Provider call (artifact:
   ``evaluation/results/local_ollama_historical_regrade_20260924_v65_zh034_no_evidence_fix/``).
2. A multi-company growth comparison could retain one issuer's supported
   claim while silently dropping the other issuers after claim-level grounding.
   The finalizer now checks post-grounding issuer coverage and appends only
   bounded, verbatim source excerpts for missing issuers. It also removes a
   contradictory generic retrieval-refusal line when supported claims remain.
   The ZH-022 replay now retains Apple, NVIDIA, and Tesla source context with
   the explicit limitation that the excerpts do not establish a complete
   ranking (artifact:
   ``evaluation/results/local_ollama_historical_regrade_20260924_v69_zh022_coverage_final_fix/``).

Regression evidence:

```text
answer-policy/query-scope focused tests: 101 passed, 1 warning
local-probe/TypeSafe focused tests: 95 passed, 1 warning
Ruff: PASS
git diff --check: PASS (CRLF normalization warnings only)
```

These changes do not alter frozen expected answers or historical semantic
labels, and they do not enable DeepSeek/evaluator calls.

The full local replay was repeated after the post-grounding coverage change:

```text
qwen3.5:9b-q4_K_M, context 8192:
  first pass: 99/100 application success
  one local output-length truncation: ZH-024
  targeted local retry (max_tokens 3072): success
  combined local result: 100/100 application success
  final unsupported claims: 0
  final unsupported numeric claims: 0
  paid Provider/evaluator calls: 0
artifacts:
  evaluation/results/local_ollama_historical_regrade_20260924_v70_full_qwen35_coverage/
  evaluation/results/local_ollama_historical_regrade_20260924_v71_zh024_coverage/
```

The prior frozen semantic labels remain a historical baseline rather than a
new local-model grade: ``29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED``.
The local replay now additionally proves that the former empty no-evidence
case is non-empty and that the multi-company growth comparison retains all
retrieved issuer excerpts after final grounding. Human/evaluator semantic
accuracy and a real Provider smoke remain intentionally pending.

Current deterministic coverage extracted from the same 100 local artifacts:

```text
required fact slots: 204
source-available slots: 194
available slots present in final answer: 194/194
final unsupported claims: 0
final unsupported numeric claims: 0
EN/ZH required-fact parity: 50/50 pairs equal
```

After the final coverage and no-evidence changes, the complete offline suite
was rerun once more: ``2579 passed, 23 skipped, 1 warning``. Frontend contract
tests remain ``41 passed`` and the production frontend build remains green.

### 2026-09-24 citation annotation audit

The existing 341-row citation artifact was revalidated with the repository's
offline annotation-integrity checker. This is not semantic evaluator output
and does not change the frozen answer labels. Of the historical 223
``VALID_BUT_NOT_SUPPORTED`` annotations, 122 reclassified as unused retrieved
context, 55 as indeterminate review, and 46 remained unsupported after the
deterministic checks. The audit also reported 37 claims not attached to a
 citation rank, 20 claims not exact in the main answer, 15 quotes not exact in
the cited chunk, 3 short/missing quotes, and 9 short/missing claims. These
findings explain why the old 223 count cannot be treated as 223 confirmed
semantic hallucinations; the remaining 46 still require semantic review.

### 2026-09-24 period-alignment repair

An actual reproducible comparison bug was found in the production fact plan:
an unqualified Apple/Tesla comparison selected Apple's Q2 FY2026 filing
period but Tesla's Q4 2025 filing period, even though Tesla's Q4/FY2025 update
contains a labelled Q2 2025 historical column. The planner now aligns on the
anchor company's quarter only when that same labelled quarter exists for every
named company; otherwise it preserves each reporting period and requires the
answer to label the non-contemporaneous comparison. It never infers a period
from a filename or silently relabels a row.

Regression evidence:

```text
mixed Q4-update table period regression: PASS
Tesla/NVIDIA non-shared-quarter behavior: PASS
focused fact/policy/retrieval suite: 233 passed, 1 warning
```

Provider-free replay on the affected current-source audit (v40) produced
7/7 application-successful answers, 0 unsupported claims, and 0 unsupported
numeric claims. EN-021, EN-048, and ZH-048 now plan Tesla Q2 2025 beside Apple
Q2 FY2026. This is an offline production-path result; no DeepSeek or evaluator
call was made.

The local Qwen semantic diagnostic was also run against the historical failure
set and an 8-case high-risk subset. Its grades are explicitly non-authoritative
diagnostics: it is sensitive to the breadth of frozen criteria and to safe
period-mismatch refusals, so its output was not used to lower gates or weaken
the grounding policy. It did, however, confirm the repaired Q2 period labels
in the affected comparison replay.

### 2026-09-24 complete local replay after period alignment

The complete 100-case historical replay was repeated after the period planner
repair using the local Ollama model ``qwen3.5:9b-q4_K_M`` with an 8192-token
context. This remains provider-free and is not a paid-provider benchmark.

```text
cases: 100
application_success: 100/100
local_errors: {}
final_unsupported_claims: 0
final_unsupported_numeric_claims: 0
real_provider_calls: 0
paid_provider_calls: 0
historical labels: 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED
artifact:
  evaluation/results/local_ollama_historical_regrade_20260924_v74_full_period_alignment/
```

The frozen historical labels are intentionally unchanged: this replay proves
production-path grounding and deterministic evidence safety, not semantic
accuracy. In particular, the local model output is not used to claim that the
33 historical ``INCORRECT`` or one ``FAILED`` case has been resolved. The
period-alignment fix is nevertheless exercised across the full replay; the
affected Apple/Tesla cases retain Tesla Q2 2025 evidence beside Apple Q2
FY2026 where the source tables support that shared quarter.

The paid DeepSeek/evaluator gate remains disabled (``ALLOW_REAL_PROVIDER=false``).

### 2026-09-24 multi-company attribution and ranking repair

The quality-priority local review exposed two additional production-path
issues that were reproducible without a Provider call:

1. A multi-company model answer could put a numeric sentence under an ``Apple``
   Markdown heading while citing a Tesla chunk. The sanitizer checked only
   issuers explicitly repeated in the sentence, so the implicit section issuer
   was lost. The grounding boundary now carries a single-issuer heading context
   to following bullets, rejects ambiguous unlabelled financial numbers in
   multi-company answers, and never allows a cited chunk from another issuer
   to satisfy the claim.
2. A fully covered growth ranking could be over-sanitized into a generic
   insufficiency response because the ranking inference was not a verbatim
   filing sentence. The policy now restores only a ranking whose recognized
   growth evidence covers every named issuer, and attaches the bounded source
   excerpts for those issuers. Partial coverage still fails closed.

The growth extractor also recognizes ``decreased`` as a financial change cue;
this is required to classify a documented Tesla contraction as evidence rather
than silently dropping the issuer.

Regression evidence:

```text
answer-grounding / final-policy focused suite: 120 passed, 1 warning
company-heading wrong-issuer numeric regression: PASS
fully-covered growth-ranking regression: PASS
Qwen3.8 diagnostic (34 historical cases, context 8192):
  12 CORRECT / 19 PARTIAL / 1 INCORRECT / 1 invalid-JSON review
```

The Qwen3.8 grades are diagnostic only and do not replace a formal evaluator
or alter frozen expected criteria. The diagnostic's sole ``INCORRECT`` case
was the reproducible EN-022 issuer attribution bug above; the ZH-022 refusal
was the reproducible over-sanitization case above. No DeepSeek/evaluator call
was made.

### 2026-09-24 quality-priority revalidation

The repository was revalidated with the local Ollama quality-priority profile
(``qwen3.5:9b-q4_K_M``, context ``8192``) and with the paid-provider guard still
disabled. A provider-free current-policy replay covered all 100 frozen answers:

```text
questions: 100
real_provider_calls: 0
evaluator_calls: 0
final_unsupported_numeric_claims: 0
final_unsupported_qualitative_claims: 0
source_fact_projection: 158/170 (92.94%)
English/Chinese source-fact projection parity: 50/50
artifact: evaluation/results/current_policy_replay_20260924_v75/
```

The historical semantic labels remain unchanged at ``29 CORRECT / 37 PARTIAL /
33 INCORRECT / 1 FAILED``. A second local-only diagnostic of the 36 historical
non-success cases completed without reviewer JSON errors and produced
``7 CORRECT / 18 PARTIAL / 7 INCORRECT / 4 FAILED``. This is deliberately not a
release gate: several reviewed rows contain mojibake in the frozen Chinese
dataset, and the reviewer incorrectly treats a safe source-scope refusal as a
failure in cases such as an Apple-only request about NVIDIA. Those rows require
criteria-aware human/evaluator adjudication, not a code change that weakens
source and period safety.

The full offline regression suite after the attribution/ranking repair is
``2583 passed, 23 skipped, 1 warning``; Ruff and ``git diff --check`` pass.
Docker was rebuilt without volume deletion; all six services are healthy and
``/api/v1/health`` plus ``/api/v1/ready`` return 200. No DeepSeek, evaluator,
commit, or push was performed.

### 2026-09-24 risk-context chunk-boundary repair

The quality-priority replay exposed a reproducible evidence-loss path for
period-specific risk questions. NVIDIA's PDF split the safe-harbor disclosure
across chunks: one chunk began with a lowercase continuation and contained the
``Important factors`` clause, while the same filing's Q2 outlook chunk carried
the constraint that China Data Center compute revenue was not assumed. The
risk filter previously rejected the latter because its text mentioned the
forward-looking Q2 period, then the excerpt renderer discarded the lowercase
continuation and returned only a heading/refusal.

The production citation gate now allows a risk-context chunk when its verified
filing-level period matches the requested period even if the chunk itself
mentions a forward-looking period; it remains marked ``related_context`` and
the answer explicitly says it is not a period-specific risk result. The
renderer trims a lowercase chunk prefix at a deterministic disclosure anchor,
recognizes constraints such as ``not assuming``, and marks truncated excerpts.
It still rejects a risk chunk from a different filing period.

Regression evidence:

```text
risk chunk-boundary + constraint test: PASS
risk/citation/query-scope suite: 35 passed, 1 warning
answer-policy focused suite: 120 passed, 1 warning
```

No benchmark ID or answer text was hardcoded; no Provider call was made.

The 100-case replay was repeated after this change as
``evaluation/results/current_policy_replay_20260924_v76_risk_context/``.
It retained ``0`` final unsupported numeric claims and ``0`` final unsupported
qualitative claims, with source-fact projection parity still ``50/50``.

### 2026-09-24 segment-disclosure retrieval and safe fallback repair

The quality-priority review of ZH-024 found a concrete retrieval/presentation
defect rather than an absent filing fact. Apple Products/Services rows were
stored under generic ``Three Months Ended`` table sections, so the segment
selector did not reserve them; the final answer could retain only an unrelated
NVIDIA margin sentence. The repair is format-agnostic: filing-native
Products/Services/iPhone labels and titled Data Center/Edge Computing sections
are recognized as segment evidence, while qualitative Services/iPhone driver
sentences are admitted only when the source itself contains the label and
growth clause. The final policy renders bounded source labels/excerpts and
does not invent a numeric segment value or causal attribution.

Regression evidence:

```text
segment retrieval/policy focused tests: 5 passed, 1 warning
full offline pytest: 2587 passed, 23 skipped, 1 warning
Ruff: PASS
git diff --check: PASS
```

The real three-PDF current-source audit was rerun without a provider:

```text
artifact: evaluation/results/current_source_retrieval_audit_20260924_v40_segment_context_final/
required facts retrieved: 194/194 (100%)
required facts projected: 194/194 (100%)
EN/ZH source-fact parity: 50/50
unsupported numeric/fact claims in projection: 0
ZH-024 final unsupported claims: 0
```

For ZH-024 the current production-path answer now cites Apple Products net
sales, Apple Services/iPhone disclosures, NVIDIA Data Center, and NVIDIA Edge
Computing, with the Apple Services and iPhone Pro-model source sentences where
retrieved. A local Ollama semantic diagnostic classified this answer as
``PARTIAL`` rather than ``INCORRECT``; that diagnostic is not a release gate
and its broader frozen criteria still ask for additional metrics and explicit
period prose. No DeepSeek/evaluator call was made.

The corresponding provider-free replay is
``evaluation/results/current_policy_replay_20260924_v78_segment_context_final/``:
historical labels remain unchanged (``29 CORRECT / 37 PARTIAL / 33 INCORRECT /
1 FAILED``), final unsupported numeric/qualitative claims remain ``0/0``, and
source-fact projection remains ``194/194``. These historical labels are not
claimed as newly resolved semantic accuracy.

### 2026-09-24 local Qwen3.8 provider-shaped semantic review

The local quality-priority profile was used for a five-question diagnostic with
``srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`` and an 8192-token Ollama context.
This is a local diagnostic only: it made ``0`` paid-provider calls and is not
DeepSeek accuracy evidence.

```text
cases: 5
historical grades: 3 CORRECT / 1 INCORRECT / 1 FAILED
local grades: 1 CORRECT / 3 PARTIAL / 1 FAILED
```

The review identified a production-policy defect in ZH-044 (a general
definition question was incorrectly forced through filing evidence and became
a refusal). General-concept answers now bypass the filing citation gate, strip
accidental ``[Evidence n]`` markers, and retain explanatory examples without
claiming company-specific support. A regression test covers the Chinese gross
margin definition and asserts that final citations are empty.

The local review also confirmed that EN-007, EN-001, and ZH-024 have available
evidence but still omit some benchmark-requested metrics. Those are answer
coverage issues, not evidence-safety failures; they remain open for a separate
deterministic fact-completion repair and were not hidden by lowering a gate.

Regression evidence for this policy change:

```text
answer-policy + query-scope suite: 104 passed, 1 warning
Ruff: PASS
DeepSeek/provider calls: 0
```

### 2026-09-24 flattened-table and explicit-period grounding repair

The source audit then found two concrete parser defects in the canonical PDFs.
Tesla's free-cash-flow table can flatten several rows onto one line; the
strict row-boundary matcher therefore dropped the ``2,034 / 664 / 146``
operating-cash-flow, capital-expenditure, and free-cash-flow values. The
retriever now recognizes the filing-verified free-cash-flow label without
loosening the table-context requirement. Segment comparison probes also reserve
all filing-native Products/Services/iPhone and Data Center/Edge Computing rows
for both issuers.

Allowing table values exposed a second risk: explicit period headers such as
``Q2 FY2026`` were being parsed as ``-2.026 billion`` facts. Fact-ledger table
amount extraction now rejects year/period-like tokens whenever the same window
contains an explicit quarter, fiscal-year, or standalone year marker. This
preserves real flattened financial rows while preventing header metadata from
becoming numeric evidence.

Provider-free source audit evidence:

```text
artifact: evaluation/results/current_source_retrieval_audit_20260924_v49_header_row_fix/
required facts: 224
source facts retrieved: 224/224 (100%)
source facts projected: 224/224 (100%)
unsupported projection claims: 0
English/Chinese source-fact parity differences: 0
DeepSeek/paid-provider calls: 0
```

The local Qwen3.8 quality-priority diagnostic was rerun after the repair using
the 8192-token local Ollama context. It is diagnostic evidence only and does
not change the frozen evaluator labels:

```text
artifact: evaluation/results/local_ollama_semantic_regrade_20260924_qwen38_5q_after_v48/
historical labels: 3 CORRECT / 1 INCORRECT / 1 FAILED
local Qwen labels: 4 CORRECT / 1 PARTIAL / 0 FAILED
```

The remaining ZH-024 ``PARTIAL`` is an answer-coverage limitation: the final
answer keeps the correctly period-bound Apple and NVIDIA segment numbers, but
does not yet include every broader benchmark-requested driver/margin detail.
The filing's Apple iPhone numeric row is still marked ``unverified_table`` and
is intentionally not promoted as authoritative numeric evidence. No unrelated
citation or wrong-period/company claim was introduced. The frozen 100-case
labels remain ``29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED``; this work
does not claim semantic release readiness.

Focused regression evidence:

```text
targeted retrieval/ledger/policy suite: 194 passed, 1 warning
full offline pytest after the flattened-header regression fix: 2592 passed, 23 skipped, 1 warning
current-source audit: evaluation/results/current_source_retrieval_audit_20260924_v49_header_row_fix/
Ruff: PASS
DeepSeek/provider calls: 0
READY_FOR_REAL_API_SMOKE: NO
```

The five-case local Qwen production-shaped probe was repeated against the v49
source audit. All five local calls returned non-empty output and passed the
grounding numeric gate; this is not a paid-provider or semantic-release score:

```text
artifact: evaluation/results/local_ollama_quality_probe_20260924_qwen38_5q_after_v49/
model: srchmnmichael/Qwen3.8-Uncensored:Q4_K_M
context_tokens: 8192
application_success: 5/5
empty_output: 0
final_unsupported_numeric_claims: 0
real_provider_calls: 0
paid_provider_calls: 0
```

### 2026-09-24 scope-aware replay and bilingual segment-growth parity

The next replay exposed two policy/test-contract issues. First, the offline
replay was applying the financial numeric sanitizer to ``DIRECT_CHAT``
definition answers. That incorrectly turned a valid non-financial explanation
into an unsupported-claim/refusal result. Replay now follows the production
scope contract: general concepts use the already grounded direct-chat result,
while FACT/COMPARE answers continue through the financial grounding policy.
The formal replay also counts unsupported *numeric* claims separately from
qualitative direct-chat prose.

Second, a named segment query such as English ``What happened to TSLA's
automotive business?`` and Chinese ``TSLA 的汽车业务最近表现如何？`` selected
different growth evidence. Reported growth for explicitly named metrics is now
retained for both languages without enabling derived growth; only an overall
summary keeps the narrower headline-growth allow-list. A regression test locks
the English/Chinese plan parity. Revenue-performance comparisons also use the
ledger-only projection when all requested company facts are available, so a
raw answer cannot mix an unlabeled Q4 number into a Q2 narrative.

Final provider-free source audit:

```text
artifact: evaluation/results/current_source_retrieval_audit_20260924_v67_bilingual_segment/
required facts: 318
source facts retrieved: 318/318 (100%)
source facts projected: 318/318 (100%)
English/Chinese source-fact and context-plan parity: 50/50
unsupported numeric/fact claims in projection: 0
DeepSeek/paid-provider calls: 0
```

Final current-policy replay:

```text
artifact: evaluation/results/current_policy_replay_20260924_v89_revenue_compare/
questions: 100
final unsupported numeric claims: 0
final unsupported qualitative claims: 0
source-fact projection: 318/318 (100%)
source-fact projection parity: 50/50
verified-facts-only projections: 13
historical labels (unchanged, not a new semantic score): 39 CORRECT /
25 PARTIAL / 35 INCORRECT / 1 FAILED
```

The local quality-priority model ``srchmnmichael/Qwen3.8-Uncensored:Q4_K_M``
was then used for a five-case diagnostic with an 8192-token context. It made
no DeepSeek or paid-provider calls:

```text
artifact: evaluation/results/qwen38_semantic_v65_v88_focus/
cases: 5
local grades: 4 CORRECT / 1 INCORRECT
EN-007: CORRECT
ZH-008: CORRECT
ZH-013: CORRECT
ZH-044: CORRECT (direct-chat, no citations)
EN-019: INCORRECT under the frozen benchmark criteria
```

EN-019 remains a benchmark/query-spec ambiguity, not a hidden retrieval
failure. The question gives no period and the checked-in filings report Tesla
Q4 2025 and NVIDIA Q1 FY2027. The production-safe answer now emits explicitly
labelled periods (Tesla Q4 2025 and NVIDIA Q1 FY2027) instead of combining a
Tesla Q2 narrative with a Q4 number. The frozen historical criterion expects a
Tesla Q2 column from the same multi-period PDF; changing the expected answer or
hardcoding the question would be invalid, so this case stays documented as a
manual policy decision rather than being claimed as semantically resolved.

Regression and runtime evidence after the final changes:

```text
full offline pytest: 2602 passed, 23 skipped, 1 warning
Ruff: PASS
git diff --check: PASS (only existing CRLF normalization warnings)
Docker services: frontend/backend/agent-worker/postgres/redis/chromadb healthy
GET /api/v1/health: 200
GET /api/v1/ready: 200
backend/worker logs: no secret/JWT/Authorization/WinError 1450 matches
DeepSeek/provider calls: 0
```

### 2026-09-24 full local-Qwen failure classification and growth-period binding

To stop repeating the same audit loop, the 35 historical ``INCORRECT`` cases
and the one historical ``FAILED`` case were reviewed once with the permitted
local Qwen3.8 model against the current-policy replay. The diagnostic result
was ``11 CORRECT / 14 PARTIAL / 5 INCORRECT / 1 FAILED``; five responses could
not be parsed as reviewer JSON because the answer was too long. Most remaining
``PARTIAL`` labels are frozen-criteria coverage expectations broader than the
user's stated scope, not retrieval or citation-safety defects. The five
remaining incorrect cases are EN-017, EN-026, EN-047, ZH-022, and ZH-040; the
first four are narrative-generation/benchmark-scope cases, while ZH-040
exposed a concrete parser/planner issue.

The concrete ZH-040 defect was reproducible with a real Apple table row:
``current quarter | prior-year quarter | YoY``. The growth parser used the
last textual period (the prior-year column) as the growth owner, so the planner
could not derive the current-quarter Services growth. It now selects the
newest labelled quarter and allows deterministic YoY derivation only for a
named metric in a performance-shaped question; broad summaries remain
conservative and do not derive every available rate. Regression coverage now
protects ``苹果的服务类业务做得怎么样？`` and the bilingual segment case.

Post-fix artifacts:

```text
source audit: evaluation/results/current_source_retrieval_audit_20260924_v69_named_growth_derivation/
required facts retrieved/projected: 318/318 (100%)
English/Chinese source-fact parity: 50/50
replay: evaluation/results/current_policy_replay_20260924_v91_named_growth_derivation/
final unsupported numeric/qualitative claims: 0/0
ZH-040 deterministic result: Services revenue 30.976 billion USD;
  derived YoY growth 16.25%, both period-labelled and cited
local Qwen3.8 ZH-040 diagnostic: PARTIAL (no longer an incorrect/refusal)
DeepSeek/paid-provider calls: 0
```

The remaining EN-019 period ambiguity and narrative-generation cases are not
being repeatedly re-run or silently reclassified as fixed. They require a
separate benchmark policy decision or a provider-generation quality project;
changing expected answers or adding question-specific rules is explicitly out
of scope.

### 2026-09-24 driver-evidence convergence repair

The focused production probe exposed a second deterministic retrieval/policy
defect: explicit business-driver questions stopped after the first two driver
sentences. On Apple, that allowed the iPhone/Mac rows to crowd out the later
Services row; on multi-company comparisons it could omit Tesla or Apple after
the first two issuers. Business-factor wording also lacked issuer-scoped
retrieval probes. The generic refusal compaction path had a related edge case:
an explicitly supported driver excerpt could still leave a stale
``retrieved passages are insufficient`` line in the final response.

The implementation now:

- recognises business-factor causal wording without question-ID rules;
- fans out bounded driver probes per named company;
- keeps a larger bounded driver passage pool and continues after an unsafe
  PDF-split fragment so a later complete passage can represent that issuer;
- accepts operational outcomes such as deployments and positive offsets as
  driver evidence when a causal link is explicit;
- removes a generic refusal only when an explicit financial driver is actually
  supported; background-only commentary remains fail-closed;
- treats a source-only issuer constraint separately from the answer target, so
  ``use Apple's filing to answer NVIDIA`` cannot be satisfied by Apple prose.

Regression coverage includes Apple Services-after-product ordering,
multi-company issuer-scoped probes, all-issuer driver extraction,
source-only/target-company mismatch, and final answer refusal compaction.

Focused current-production artifact:
``evaluation/results/current_source_retrieval_audit_20260924_v72_driver_finalizer_focus/``

The five affected cases retained ``unsupported_claim_count = 0``. EN-017 now
includes Apple Services drivers; EN-026, EN-047 and ZH-026 retain evidence for
the named issuers; ZH-022 retains Apple, NVIDIA and Tesla evidence. The full
offline suite after the final safety-boundary fix is ``2608 passed, 23
skipped``; DeepSeek/paid-provider calls remain zero.

### 2026-09-24 convergence follow-up: consolidated revenue selection and ranking safety

The next focused replay found a reproducible fact-selection defect rather than
another Provider-quality loop. Flattened financial tables can assign the same
period metadata to a consolidated total, a geographic/segment subtotal, and an
annual-history row. The planner now prefers explicitly labelled total-net-sales
or total-revenue rows and a bounded repeated-value cluster. This is a generic
evidence rule; it does not name benchmark question IDs or treat filenames as
period truth.

Against the three checked-in sample filings, the selected facts are now:

```text
Apple Q2 FY2026 revenue:   $111.184B (not the $92.963B geographic subtotal)
Tesla Q4 2025 revenue:     $24.901B (not the $53.823B annual-history row)
NVIDIA Q1 FY2027 revenue:  $81.615B
```

For an unqualified multi-company growth question, the production finalizer now
computes a bounded deterministic comparison from reported YoY rates or a
validated current/prior pair. It emits NVIDIA as the highest rate in this
sample set, explicitly discloses that the source periods differ, and binds the
ranking/caveat to issuer-complete evidence. Strict sanitization no longer drops
this valid policy sentence, while arbitrary qualitative ranking prose remains
fail-closed.

Regression coverage includes the consolidated-vs-geographic Apple row,
growth-ranking retention under strict sanitization, and the existing wrong
company/period numeric gates. Validation after this repair:

```text
full offline pytest: 2611 passed, 23 skipped, 1 warning
frontend contract tests: 41 passed
frontend production build: PASS
Ruff: PASS
git diff --check: PASS (existing CRLF normalization warnings only)
Docker: six services running/healthy
GET /api/v1/health: 200
GET /api/v1/ready: 200
DeepSeek/provider calls: 0
secret log scan: NO LEAK
```

### 2026-09-24 finalizer stale-absence convergence

The v95 replay of the current production grounding path exposed and closed one
last deterministic boundary issue: historical growth-comparison drafts could
reintroduce phrases such as ``Apple's growth narrative is not assessable`` or
``the evidence contains no Apple revenue`` after a late merge, even when the
trusted ledger contained issuer-complete revenue/Yoy facts. The finalizer now
removes these stale variants only after deterministic issuer-complete ranking
proof, then appends the validated ranking/caveat. Ordinary missing-evidence
refusals remain unchanged.

```text
v95 source facts projected: 330/330
v95 final unsupported numeric claims: 0
v95 final unsupported qualitative claims: 0
EN-022/ZH-022 ranking present: YES
EN-022/ZH-022 stale revenue-absence claim: NO
historical labels unchanged: PARTIAL 37 / CORRECT 29 / INCORRECT 33 / FAILED 1
Provider/evaluator calls: 0/0
```

Regression coverage includes ``not assessable``, ``contains no ... revenue`` and
``revenue ... absent`` wording. Full offline pytest is now ``2612 passed, 23
skipped, 1 warning``; frontend contract tests (41), build, Ruff and diff check
pass. Backend and agent-worker were rebuilt without taking down the stack or
touching volumes; all six services remain healthy and health/ready return 200.

The subsequent current-source audit (``v74_growth_fact_probes``) closed the
remaining cross-company ranking retrieval gap:

```text
required facts retrieved: 330/330 (100%)
required facts projected: 330/330 (100%)
bilingual source-fact retrieval differences: 0
context-plan differences: 0
unsupported numeric/fact projection claims: 0
provider/evaluator calls: 0/0
```

EN-022 and ZH-022 now both retrieve and project Apple, Tesla, and NVIDIA
headline revenue plus issuer-local growth evidence before producing the
directional ranking. The new probes are company- and observed-period scoped;
they do not introduce question-specific answers.

### 2026-09-24 provider guard hardening

An isolated HTTP experiment revealed that the DeepSeek adapter previously
checked ``ALLOW_REAL_PROVIDER`` only when ``PYTEST_CURRENT_TEST`` was present.
That allowed a production process with a persisted DeepSeek route to construct a
real client while the Compose value was ``false``. The experiment was stopped
immediately when the response routing exposed this; the temporary container was
removed and no further requests were sent. Because the old guard was not active
in production, the run cannot be certified as zero-provider-call; at most two
requests may have reached the configured provider.

The adapter now fails closed in every runtime unless
``ALLOW_REAL_PROVIDER=true``. Only injected SDK doubles in pytest are exempt.
The production-style guard regression and retry tests pass, the full suite is
``2613 passed, 23 skipped, 1 warning``, and the rebuilt Docker backend rejects
client construction with ``ProviderError`` while the flag is false.

The guard is now shared by all external adapters (OpenAI, Gemini, Anthropic and
Doubao); only explicitly local Ollama-compatible endpoints are allowed without
the paid-provider opt-in. External/local endpoint tests pass and the full suite
is ``2622 passed, 23 skipped, 1 warning``. Both backend and worker containers
were rebuilt and verified to reject every external provider while allowing the
local endpoint classification, with health/ready still at 200.
