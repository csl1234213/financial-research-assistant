# RC1 Phase 1C — Tree Retrieval Forensics

Date: 2026-10-02. Scope: forensic audit only; no retrieval implementation change.

RC1_PHASE_1C_STATUS = NOT_ACCEPTED
RC1_PHASE_1C_A_STATUS = PASS (latest implementation acceptance below)
TREE_RETRIEVAL_FORENSICS = COMPLETED_WITH_EVIDENCE_LIMITATIONS
PRODUCTION_PROMOTION = NO
COMMIT_1C_A = 7437c49ad16532a7b134d1a910a2a74696bbaeb5
ACTUAL_HISTORY_VALIDATION = 300 PASS, 0 FAIL, 0 SKIP

## Frozen failure and evidence limits

TREE_FAILURE_REPRODUCTION = HISTORICAL_REAL_FAILURE_CONFIRMED; NEW_LIVE_REPLAY_NOT_RUN

Original receipt: `<private-acceptance-artifacts>/p22-real-ready-tree-selection-compact.xml`, testcase `tests.test_ready_narrative_snapshot_replay::test_original_ready_snapshot_replay`.

- Query: `说明贵州茅台的主要业务`; locale zh-CN; tenant 1, user 2.
- Source SHA256: `474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288`.
- DeepSeek model: `deepseek-v4-flash`; one API attempt; finish reason stop.
- Wire input 11,326 bytes; 143 candidates; usage 4,119 prompt + 57 completion = 4,176 tokens.
- Selected page ranges: [1,1], [39,39]. Returned evidence pages: [1,1,1,1,1].
- Failure assertion: `Nonempty Tree retrieval does not prove main-business evidence coverage`.
- The receipt does not retain the complete raw model response, original node handles, or selection reason. Page-to-node identification below is deterministic reconstruction, not an original raw-response capture.
- A separate live low-coverage failure receipt has not been established. The correct-page truncation case below is a source-backed diagnostic counterfactual, not a second live-provider failure.

## Artifact evidence inspection

Read-only preserved artifact directory:
`<private-acceptance-artifacts>/p22-original-ready-hybrid/test_original_business_questio0/artifacts/1/474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288`.

All stored files in this directory matched their content-addressed SHA256 filenames. This retained same-source snapshot is not yet proven to be the exact artifact instance loaded by the failed provider run: the receipt lacks that artifact digest. Do not substitute it silently for the original frozen instance.

- Tree artifact: `c581f625d6d49252283fa4adedaee74f476098bfcb404b08aef4a7da4b57b036`.
- Quality artifact: `f6735ac9ab7b3944dea564a43683c9adde9391317b8006df02f53aee5f6ece02`.
- Internal document ID: `50b2dee6c4ce3ff54fa5f5914c6af520`.
- Tree: 144 nodes, max depth 1, quality LOW, page coverage 1.0, source-block coverage 1.0, heading coverage 0.0; no reported integrity errors or orphan pages.
- Expected page node: `50b2dee6c4ce3ff54fa5f5914c6af520:page:8`; parent `50b2dee6c4ce3ff54fa5f5914c6af520:root`; 22 source blocks.
- Expected source block: `46a648eb37d219014c5e73261d8f2888`, page 8, reading order 13, source-block position 13 (zero-based).
- Source text begins: `公司主要业务是茅台酒及系列酒的生产与销售。`
- Preceding source headings, reading orders 11 and 12: `第三节 管理层讨论与分析` and `一、报告期内公司从事的业务情况`.

TREE_ARTIFACT_EXPECTED_EVIDENCE_PRESENT = TRUE_IN_RETAINED_SAME_SOURCE_ARTIFACT
ORIGINAL_FAILURE_ARTIFACT_INSTANCE_MATCH = NOT_YET_PROVEN
TREE_BUILD_REGRESSION_DETECTED = NOT_ESTABLISHED

This is a fallback page tree, not a verified semantic chapter hierarchy. Presence and integrity do not prove navigation quality. No new tree was built or persisted during this audit.

## Current pipeline

CURRENT_TREE_RETRIEVAL_PIPELINE:

READY artifact read and integrity verification → all non-root node locator candidates → one model selection → final selected-node source blocks → source-order deduplication → first top_k blocks → UnifiedEvidence → EvidenceSnapshot projection.

Audited components:

- `retrieval/ready_tree_decision.py`: candidate IDs are opaque handles; current descriptors retain source headings; at most two selected IDs; 256-candidate and 16,000-byte admission limits; no ancestry descriptor; returned decision does not request deeper traversal. Original historical descriptor truncation and current descriptors must not be conflated.
- `retrieval/tree_shadow.py`: supports bounded child traversal, but replaces prior selection rather than retaining completed branches. Final source blocks are sliced by `selected[:top_k]`; no query-aspect-aware coverage evaluation. CoverageReport remains empty. Nonempty evidence is not sufficient coverage.
- `retrieval/ingestion_ready_tree.py`: validates source and ownership, returns snapshots, but does not expose full retrieval trace/coverage through this method. Query information-need fields are not populated here.
- Canonical source text, not node summaries, supplies evidence. No Hybrid fallback was observed in this path.

## Divergence and classification

FIRST_DIVERGENCE_POINT = MODEL_NODE_SELECTION_IN_HISTORICAL_RECEIPT

Selected pages 1 and 39 do not include the expected page-8 business source. The preserved page-1 node contains exactly five cover blocks; selection order plus top_k=5 consumes the entire evidence allowance before page 39.

TREE_FAILURE_CLASS = TREE_WRONG_BRANCH + SOURCE_ORDER_EVIDENCE_TRUNCATION; COVERAGE_EVALUATION_MISSING

Diagnostic counterfactual at unchanged top_k=5: even selecting page 8 alone produces its first five blocks (report header, nonrecurring-item disclosure, equity-incentive heading, applicability checkbox, fair-value heading). The expected business block at position 13 is excluded. This conclusion follows directly from persisted node block order and the audited slice, not from a new model call.

ROOT_CAUSE_HYPOTHESIS:

1. Historical navigation descriptors obscured later business headings; flat page navigation contributed to wrong selection. Supported by earlier receipts/documentation, but exact original prompt is not retained, so descriptor causality is not independently proven.
2. Confirmed deterministic materialization defect: source-order truncation ignores the requested information need, independently of selection correctness.
3. Confirmed contract gap: empty coverage fields cannot distinguish relevant evidence from cover-page evidence. The failing test caught this; the retriever did not compute coverage satisfaction.
4. Existing current heading improvements do not establish closure: recorded all-heading preflight exceeded the existing wire budget. No model-quality PASS may be inferred from fixture selection or nonempty evidence.

## Minimal fix plan — proposed, not implemented

1. Recover and bind the exact failed-run artifact digest, node IDs, original request payload and raw selection response where available. Explicitly retain missing-data flags if unrecoverable.
2. Freeze separate wrong-branch and correct-node/low-coverage regressions using real source blocks; fixture annotations must not become company/page rules.
3. Reuse RetrievalRequest information-need fields and CoverageReport. Define source-supported required aspects and reject unsupported satisfaction; do not treat retrieval count as coverage.
4. Use bounded node-ID/ancestry navigation over the existing artifact, retaining independently completed relevant branches. Preserve node/parent/source IDs in trace and provenance. Establish limits for rounds, visited nodes, branches and evidence before changing traversal.
5. Replace blind source-order truncation with source-grounded selection against information needs within the unchanged evidence budget. Preserve source text, page, bbox and IDs. No summary-as-evidence, Hybrid fallback or Top-K increase.
6. If success requires rebuilding a semantic hierarchy, changing selector prompt text, or altering sealed ingestion/build contracts, stop and report scope expansion rather than implementing it in this phase.
7. Audit historical untracked Tree dependencies before any candidate staging. Validate a self-contained candidate before a separate commit. No staging or implementation occurred in this audit.

## Acceptance state

EXPECTED_EVIDENCE_RECALL = NOT_ACCEPTED (historical failed result lacks expected block)
WRONG_BRANCH_COUNT = NONZERO_IN_HISTORICAL_FAILURE
FALSE_SATISFIED_COUNT = NOT_MEASURED
PROVENANCE_LOSS_COUNT = NOT_FULLY_AUDITED
TARGETED_TESTS = NOT_RUN_THIS_AUDIT
RUFF = NOT_RUN_THIS_AUDIT (no code changes)
PROVIDER_CALLS_THIS_AUDIT = 0
PRODUCTION_WRITES = 0
SEALED_COMMITS_MODIFIED = 0

Next: exact-instance evidence binding and scoped implementation authorization/review. Phase 1C is not PASS; do not enter subsequent phases or promote Tree to production.

## Subphase 1C-A — baseline freeze and implementation boundary

SUBPHASE_1C_A_STATUS = IN_PROGRESS_BASELINE_FROZEN

The 1C-A task explicitly accepts the retained same-source artifact for the correct-node diagnostic. Exact historical selector-instance recovery is not a prerequisite for this materialization-only subphase; it remains a prerequisite or evidence limitation for 1C-B.

SOURCE_ORDER_TRUNCATION_REGRESSION: `tests/test_tree_materialization_baseline.py`, executed against the content-addressed retained Tree and quality artifacts, without reconstruction or provider selection.

Receipt: `<private-acceptance-artifacts>/rc1-1ca-baseline.xml`.

- Correct-node baseline: expected block at position 13; EXPECTED_BLOCK_PRESENT=false; RETURNED_BLOCK_COUNT=5; coverage.complete=None; Provider calls=0.
- Cross-node baseline: injected nodes page 1 then page 8; returned pages [1,1,1,1,1]. First-node starvation independently confirmed.
- BASELINE_TEST_RESULTS: 2 PASSED, 0 FAILED, 0 SKIPPED. These are successful defect reproductions, NOT closure passes.

### TREE_INFORMATION_NEED_AUDIT

Current `RetrievalRequest` provides scoped.query, scoped.document_ids, scoped.tenant_id, scoped.top_k; intent; metric; fiscal_year; period; scope; query_precision; query_breadth; query_class; conversation_context and preferred_retrievers.

It has no explicit required_aspects, coverage requirements or multi-evidence need field. Entity scope is represented by scoped documents, not a separate company identity. Existing CoverageReport already exposes required_aspects, covered_aspects, missing_aspects, coverage_ratio and complete. Reuse it; do not create a parallel coverage/intent model.

Minimal proposed contract addition: an optional validated tuple of required_aspects on the existing request, default empty, rather than overloading intent with an undocumented delimiter. Explicit aspects can drive deterministic multi-aspect fixtures. Inferred main-business description must be generic across issuers; unrecognized/underspecified needs remain UNKNOWN, not falsely satisfied.

### Dependency and hunk ownership audit

`retrieval/tree_shadow.py` is tracked; its pre-existing delta is the NarrativeAdmission import and provenance merge. That delta belongs to historical work and is not authorized as part of 1C-A. The Tree models, integrity checker, build implementation, serialization, adaptive contracts and NarrativeAdmission are tracked dependencies.

READY adapters and `ready_tree_decision.py` are historical untracked files. They are not necessary for a source-artifact materialization test and must not enter this commit. `bm25_retriever.py` has historical mixed tokenizer changes: the working-tree tokenizer differs from HEAD, so importing its improved Chinese tokenizer would create a hidden dependency. A candidate must either use tracked baseline-safe utilities or provide a small self-contained lexical implementation confined to Tree evidence selection, without modifying Hybrid.

COMMIT_CANDIDATE_MANIFEST (proposed, not staged):

- Existing adaptive contract: explicit required_aspects only, if confirmed necessary.
- Tree materialization helper: bounded cross-node source-grounded ranking and conservative CoverageReport population.
- Tree retriever patch: materialization call, node/path/source provenance and candidate/selected/rejected trace; exclude historical NarrativeAdmission hunk.
- Deterministic real-artifact baseline and closure tests, multi-aspect/negative/provenance compatibility tests.
- This closure report.

### Evidence selection and coverage policy proposal

Evaluate canonical text across all already-selected nodes before spending the unchanged top_k budget. Use query/aspect lexical signals and canonical heading context for ranking. Prefer coverage-bearing body blocks over matching headers/checkboxes. Allocate to uncovered supported aspects before redundant high-score blocks; use stable source identity as tie-breaker, not caller node order. Source order may order presentation after selection, but cannot determine survival.

Coverage satisfaction requires affirmative source-body support for each understood aspect. Keyword occurrence in a heading, cover page, negated statement or question is not sufficient. Generic lexical ranking alone does not prove semantic completeness; UNKNOWN is required for unsupported needs. Do not claim arbitrary financial-query coverage from lexical overlap.

Preserve source text unchanged and add node IDs, ancestor path, reading order, document version and source IDs. Record bounded candidate count, returned count, scores/rejections and coverage state. No summary becomes final evidence.

IMPLEMENTATION = NOT_YET_APPLIED
ARCHIVED_BASELINE_COMMIT = NONE (before 1C-A implementation)
INDEPENDENT_CANDIDATE_VALIDATION = PENDING
CORRECT_NODE_CLOSURE_RESULT = PENDING
FALSE_SATISFIED_COUNT = NOT_MEASURED
PROVENANCE_LOSS_COUNT = NOT_MEASURED

Next execution: implement the proposed narrow materialization policy, add closure fixtures, independently validate the exact candidate without historical mixed/untracked dependencies, then consider the authorized separate commit. Do not modify the selector or enter 1C-B.

## Subphase 1C-A2 — implementation and independent acceptance

This section supersedes the earlier baseline-only/pending implementation snapshots.

SUBPHASE_1C_A_IMPLEMENTATION = COMPLETED
RC1_PHASE_1C_A_STATUS = PASS
RC1_PHASE_1C_STATUS = NOT_ACCEPTED

### INFORMATION_NEED_IMPLEMENTATION

Added backward-compatible `required_aspects: tuple[str, ...] = ()` to the existing RetrievalRequest, with unique/nonempty identity validation. No parallel intent, evidence or coverage type. Existing callers still populate query/tenant/document scope/top_k; optional information-need fields are not assumed populated. READY wiring is unchanged.

Explicit aspect identities currently understood: MAIN_BUSINESS_DESCRIPTION and RISK_DESCRIPTION. Without explicit aspects, conservative query mention recognition supports these narrative needs. Quantitative keywords or populated metric/period/fiscal_year/scope prevent inferred completeness. Unknown requirements remain UNKNOWN, even with evidence. This is not a universal query decomposer or financial semantic verifier.

### EVIDENCE_SELECTION_POLICY / GLOBAL_BUDGET_POLICY

New local `retrieval/tree_materialization.py` evaluates canonical blocks from all already-selected nodes; it performs no Provider/embedding/index calls. The existing BM25 working-tree Han-tokenizer enhancement is historical and mixed, so it was not imported or committed. A small standard-library word/Han-pair overlap matcher is confined to this helper, not a new retriever/index or change to Hybrid.

Global allocation prioritizes newly covered supported aspects, then affirmative support and lexical/context score. Canonical headings provide ranking context only; TITLE cannot establish coverage. Caller node ordering does not dominate the budget. Stable page/reading-order/block identity breaks score ties. Final evidence remains at most the existing top_k, including the frozen top_k=5.

If an understood need has affirmative body support, unproven filler is not added merely to fill unused slots. No fixed per-node quota. If there is no affirmative support, ranked diagnostic source evidence may still be returned, but coverage remains insufficient/unknown. No nearby-block expansion was necessary, and no grouping/build rule changed.

Candidate scoring is limited to selected-node source blocks. Existing whole-tree integrity validation is unchanged; it is not a new document-wide retrieval scan. Trace records candidate count/IDs, global scores, rejected and returned IDs, top_k, selection elapsed time and coverage details, without adding source text or provider prompts to trace.

### COVERAGE_POLICY

Existing CoverageReport stores required/covered/missing aspects, ratio and complete. `coverage_status` in trace expresses SATISFIED/PARTIAL/INSUFFICIENT/UNKNOWN. A supported aspect requires a canonical TEXT declarative sentence matching its conservative affirmative disclosure pattern. Headings, questions and recognized negated/unavailable statements do not establish coverage. Unknown aspects keep complete/ratio unset. This limited deterministic contract is not an entailment model or an Answer quality claim.

The legacy RetrievalResult status still describes result/budget availability; clients must not substitute FOUND/PARTIAL or evidence count for coverage.complete. No Answer release behavior was changed.

### REAL_ARTIFACT_BEFORE_AFTER / CROSS_NODE_BEFORE_AFTER

Same content-addressed artifact, query, selected nodes and top_k=5. Baseline executes the audited sealed `ac968d5b29f7b2c95ff343d2f90fe3dbca9e0264` Tree implementation; it does not merely simulate a slice after repair.

| Case | Before | After |
| --- | --- | --- |
| Correct page-8 node | Expected block absent; 5 returned; empty coverage | Expected block present; 1 returned; SATISFIED |
| Nodes page 1 then page 8 | Five cover-page blocks consume budget | Expected page-8 source retained; 1 returned; SATISFIED |
| Same nodes reversed | No ordering-quality claim in old receipt | Same required evidence retained; 1 returned; SATISFIED |
| Wrong page-1 node | Nonempty cover evidence; empty coverage | Nonempty diagnostic evidence; INSUFFICIENT |

Expected source block remains `46a648eb37d219014c5e73261d8f2888`; canonical source text is not regenerated. Correct-node required-evidence recall = 1.0. Narrow fixture irrelevant-evidence rate = 0.0 after removing quota filler (the intermediate 282-test candidate had 0.6 and was superseded).

### COVERAGE_CASES / PROVENANCE_AUDIT

- Single understood affirmative narrative aspect: SATISFIED.
- Two required aspects and both supported: SATISFIED.
- Only one of two supported, even with repeated evidence: PARTIAL.
- Empty or irrelevant evidence for understood requirements: INSUFFICIENT.
- Unrecognized/quantitative need: UNKNOWN, not optimistic satisfaction.
- Heading-only, question, negated/unavailable text: not SATISFIED.
- FALSE_SATISFIED_COUNT = 0 in the enumerated negative hard-gate fixtures; this is not a universal-language guarantee.
- PROVENANCE_LOSS_COUNT = 0 for real source fixtures: unchanged document/source identity, version, canonical text, page, bbox, source/recovery provenance; added node IDs, ancestry/path and reading order.
- Unified Evidence converts losslessly to AgentEvidence and Answer EvidenceSnapshot; no new parallel Evidence type.
- SUMMARY_USED_AS_FINAL_EVIDENCE = false; replacing node summaries does not change returned source evidence.

### Independent candidate results

TEMP_1C_A = <private-acceptance-artifacts>/rc1-1ca-candidate (clean detached sealed history plus explicit patch).
COMMIT_1C_A_SELF_CONTAINED = true
UNTRACKED_HIDDEN_DEPENDENCIES = 0

Imports were inspected and resolve inside the candidate checkout. The historical NarrativeAdmission import/provenance delta in the main Tree file was deliberately excluded. No READY adapter or selector was copied into the candidate.

Final receipts:

- `<private-acceptance-artifacts>/rc1-1ca-candidate-tight.xml`: 283 passed, 0 failed, 0 skipped.
- `<private-acceptance-artifacts>/rc1-1ca-provider-regression.xml`: 17 passed, 0 failed, 0 skipped.
- Unique candidate total: 300 passed, 0 failed, 0 skipped.
- Earlier run: 149 passed plus one setup error because isolated PostgreSQL was unconfigured; not counted as acceptance. It was rerun using the existing loopback `p23_upload_test` test database, random disposable schemas and the unchanged formal harness; production database was not used.
- Ruff on all changed Python files = PASS; candidate diff check = PASS.
- Existing Starlette/httpx deprecation and formal-marker registration warnings remain recorded, not treated as test passes/failures or fixed out of scope.

| Group | PASS | FAIL | SKIP |
| --- | ---: | ---: | ---: |
| TREE_MATERIALIZATION_TESTS (overlapping subset) | 5 | 0 | 0 |
| TREE_GLOBAL_BUDGET_TESTS (overlapping subset) | 5 | 0 | 0 |
| TREE_COVERAGE_TESTS (overlapping subset) | 22 | 0 | 0 |
| TREE_PROVENANCE_TESTS (real source subset) | 3 | 0 | 0 |
| REAL_ARTIFACT_REGRESSIONS | 7 | 0 | 0 |
| TREE_SELECTOR/TRAVERSAL_INTERFACE_REGRESSIONS | 9 | 0 | 0 |
| TREE_BUILD_REGRESSIONS | 7 | 0 | 0 |
| UNIFIED_EVIDENCE_REGRESSIONS | 16 | 0 | 0 |
| ANSWER_COMPATIBILITY (offline synthesis) | 114 | 0 | 0 |
| ANSWER_PROVIDER_CONTRACT | 23 | 0 | 0 |
| PROVIDER_REGRESSION (runtime/adapters/factory/retry) | 61 | 0 | 0 |
| FINANCIAL_FACT_REGRESSION | 9 | 0 | 0 |
| INDEX_CORE_REGRESSION | 22 | 0 | 0 |
| ANSWER_PROVIDER_INGESTION_ISOLATION | 1 | 0 | 0 |

Subset groups overlap; do not sum the table. Baseline defect tests remain distinct from acceptance fixes.

### Frozen boundaries and commit scope

Tree selector invocation/traversal AST prefix is identical to sealed history. The historical untracked READY selector was not imported or committed; its retained file fingerprint is SHA256 `16e56088e178eaa830fcb6cf1c6da518ed4151f60dfed99c5f3562f625763da3`. No new live selector-quality claim is made.

TREE_SELECTOR_BEHAVIOR_CHANGED = false
TREE_SELECTOR_PROMPT_CHANGED = false
TREE_BUILD_CHANGED = false
TOP_K_CHANGED = false
EVIDENCE_BUDGET_INCREASED = false
HYBRID_FALLBACK_ADDED = false
PROVIDER_CALLS = 0
EVIDENCE_SELECTION_PROVIDER_CALLS = 0
SOURCE_ORDER_EVIDENCE_TRUNCATION = CLOSED
CROSS_NODE_FIRST_NODE_STARVATION = CLOSED
COVERAGE_EVALUATION = ENABLED_FOR_SUPPORTED_NEEDS
TREE_BUILD_REGRESSION = 0
PROVIDER_REGRESSION = 0
ANSWER_EVIDENCE_REGRESSION = 0

Explicit commit scope is recorded in `phase-1ca-commit-manifest-20261002.json`. Candidate normalized index tree must equal the staged main index tree before commit; historical mixed/untracked changes remain outside the index. No Phase 1A/1B commit was rewritten.

COMMIT_1C_A = 7437c49ad16532a7b134d1a910a2a74696bbaeb5
ACTUAL_HISTORY_VALIDATION = 300 PASS, 0 FAIL, 0 SKIP in clean detached commit 7437c49ad16532a7b134d1a910a2a74696bbaeb5; receipt path `<private-acceptance-artifacts>/rc1-1ca-actual-history.xml`.

### Limitations and stop

Coverage currently understands only the two documented narrative aspect families. It does not prove numeric correctness, dates, scope, all ordinary language meanings or arbitrary aspect identities. Real artifact tests require retained artifacts and sealed baseline Git history; absent artifacts are explicitly skipped, never counted as PASS. Historical exact failed selector-instance recovery remains incomplete.

Do not enter 1C-B automatically. Wrong Branch remains open, overall Phase 1C remains NOT_ACCEPTED, and Tree production promotion is not authorized. No Docker deployment or GitHub push was performed.

## Subphase 1C-B — current admission reproduction and root-cause gate

This section follows explicit 1C-B authorization; it does not alter sealed 1C-A.

SUBPHASE_1C_B_REPRO_STATUS = DETERMINISTIC_PREFLIGHT_FAILURE_CONFIRMED; LIVE_REPLAY_GATE_NOT_MET
RC1_PHASE_1C_STATUS = NOT_ACCEPTED
CURRENT_WRONG_BRANCH_REPRODUCED = DETERMINISTIC_PRE_MODEL_FAILURE (task's preflight exception branch)
CURRENT_MODEL_WRONG_BRANCH_REPRODUCED = NOT_TESTED

### CURRENT_SELECTOR_REPRO_ENV / ownership qualification

- Clean sealed Git base: `7437c49ad16532a7b134d1a910a2a74696bbaeb5`.
- Isolated checkout: `<private-acceptance-artifacts>/rc1-1cb-repro`.
- Source / Tree / quality SHA bindings are the exact retained-artifact digests specified above; all hashes were checked before restoration. No Tree rebuild.
- Current READY selector is historical **untracked** code, absent from sealed history. Therefore a fully tracked "formal current selector" cannot be claimed. An explicit, byte-identical frozen overlay was used; no other dirty-worktree modules were imported.
- Selector file SHA256: `16e56088e178eaa830fcb6cf1c6da518ed4151f60dfed99c5f3562f625763da3` (matches sealed 1C-A report's fingerprint).
- Descriptor functions source SHA256: `798618914f1b3538599a731d6bb958bfa4a0b95425e2fc43f7be0e334a5e89cb`.
- Dependencies: sealed `core.answer_synthesis_narrative_strategy.parse_narrative_json`, `llm.providers.provider_models.ChatRequest`, `retrieval.tree_shadow.TreeDecision`, and standard-library json/re/time. The selector is the sole explicit historical code overlay.
- The temporary capture script and forensic tests are diagnostic artifacts, not production modules or committed runtime dependencies.
- Explicit overlay/diagnostic ownership manifest: `<private-acceptance-artifacts>/rc1-1cb-repro-manifest.json`. The frozen selector also retains legacy complete-usage and DeepSeek-attempt checks; these were not reached by this preflight and are not qualified as part of the sealed Provider acceptance. They were not changed or newly introduced.
- Query: `说明贵州茅台的主要业务`; tenant 1; internal document `50b2dee6c4ce3ff54fa5f5914c6af520`; top_k=5.
- Planned provider family: DeepSeek; historical model reference: `deepseek-v4-flash`. Actual Provider/model/endpoint are **not instantiated/resolved** because preflight blocks before any call. No claim of a historical-identical deployment.
- Unchanged selector settings: at most 2 selected handles, 256 candidate limit, 16,000-byte input limit, temperature 0, max_tokens 512, configured deadline 60 seconds. Actual model request was never sent.

### SELECTOR_INPUT_PREFLIGHT / DESCRIPTOR_VISIBILITY / WIRE_BUDGET_AUDIT

Complete sanitized receipt: `<private-acceptance-artifacts>/rc1-1cb-selector-preflight.json`.
Receipt SHA256: `95fdbcaeb210cf05f0bf1081c803e75dc077afc1b3015d6ba0103cf294f3d7d3`.

It contains the complete constructed selector instruction/payload, all 143 descriptor rows, descriptor byte sizes, opaque handle mappings, node/page identities, code/artifact/Git fingerprints, admission exception and safe request settings. It contains no API key, Authorization header or secret environment.

- Candidate count: 143 (not exceeding 256).
- Internal wire-budget measure: 22,919 UTF-8 bytes = 429 instruction + 22,490 payload bytes.
- Configured maximum: 16,000; excess: 6,919 bytes.
- Pooled section labels: 458; pooled-label JSON alone: 16,204 bytes, already exceeding the whole-input allowance.
- These are the current selector's exact concatenated instruction+payload budget measures, **not** serialized HTTP transport size.
- Expected node in constructed candidate pool: true; handle n8 resolves to the frozen page-8 node.
- Expected descriptor visible in constructed payload: true; both `第三节 管理层讨论与分析` and `一、报告期内公司从事的业务情况` are preserved.
- EXPECTED_NODE_ADMITTED = false: the complete request is rejected, not partially sent.
- EXPECTED_NODE_DESCRIPTOR_VISIBLE = true in the constructed pre-admission payload; visible to model = NOT_APPLICABLE_NO_REQUEST.
- EXPECTED_BUSINESS_HEADING_VISIBLE = true in constructed payload.
- WIRE_BUDGET_TRUNCATION_OCCURRED = false.
- CANDIDATE_LIMIT_TRUNCATION_OCCURRED = false.
- Admission exception: `TREE_MODEL_INPUT_BUDGET`.
- MODEL_INPUT_SENT = false.

No title-loss or truncation conclusion is justified here: the current implementation rejects the entire intact payload. The observed current failure differs from the historical selection of pages 1/39.

### HANDLE_MAPPING / REPRODUCTION / RAW_RESPONSE_CAPTURE

All 143 handles map bijectively to original artifact node IDs; descriptor/page relationships and lossless pooled-label packing were independently validated. Three repeated calls through the unchanged selector entrypoint produce the identical preflight rejection and zero Provider calls.

CURRENT_SELECTOR_RESULT_CAPTURED = PRE_MODEL_ADMISSION_EXCEPTION_AND_COMPLETE_CONSTRUCTED_INPUT
FULL_CURRENT_RAW_RESPONSE_CAPTURED = NOT_APPLICABLE_NO_MODEL_REQUEST
ARTIFACT_DIGEST_BOUND = true
GIT_SHA_BOUND = true
HANDLE_MAPPING_VALIDATED = true
EXPECTED_NODE_ADMISSION_KNOWN = true
DESCRIPTOR_VISIBILITY_KNOWN = true
WIRE_TRUNCATION_KNOWN = true

The task requires no Provider call after failed preflight, while the general live reproduction hard gate requires a captured raw response. These cannot both hold on this branch. This audit follows the explicit preflight-stop rule, does not fabricate a response, and does **not** declare the full live/model wrong-branch reproduction gate PASS.

LIVE_PROVIDER_CALLS = 0
N_REPLAYS = 0
DETERMINISTIC_PREFLIGHT_REPETITIONS = 3
ATTEMPTS = 0
TOTAL_USAGE = NOT_APPLICABLE_NO_REQUEST
EXPECTED_NODE_HIT_RATE = NOT_APPLICABLE_NO_SELECTION
WRONG_BRANCH_RATE = NOT_APPLICABLE_NO_SELECTION
INVALID_SELECTION_RATE = NOT_APPLICABLE_NO_SELECTION
TIMEOUT_RATE = NOT_APPLICABLE_NO_REQUEST
COVERAGE_SATISFIED_RATE = NOT_APPLICABLE_NO_SELECTOR_RESULT
REQUIRED_EVIDENCE_RECALL = NOT_APPLICABLE_NO_SELECTOR_RESULT
MODEL_LATENCIES = NOT_APPLICABLE_NO_REQUEST

Explicit correct-node fixture integration confirms sealed 1C-A still returns the required source block within top_k=5 and SATISFIED coverage. This fixture is not a selector replay or selector-quality PASS.

### HISTORICAL_RECOVERY_ATTEMPT

A bounded targeted scan of existing selection receipts/trace filenames located the previously inspected compact real-selection XML and source-heading preflight XML, but did not recover a complete historical request/raw response/digest-bound mapping. No broad unlimited history scan.

HISTORICAL_EXACT_INSTANCE_RECOVERY = UNAVAILABLE_IN_BOUNDED_SEARCH
ORIGINAL_FAILURE_ARTIFACT_INSTANCE_MATCH = NOT_YET_PROVEN
HISTORICAL_WRONG_BRANCH_ROOT_CAUSE = EVIDENCE_LIMITED

### FIRST_DIVERGENCE_POINT / FAILURE_CLASS / ROOT_CAUSE

FIRST_DIVERGENCE_POINT = build_prompt final wire-budget admission, before Provider.chat
FAILURE_CLASS = TREE_CANDIDATE_ADMISSION_FAILURE
FAILURE_SUBCLASS = WIRE_BUDGET_REJECTION
ROOT_CAUSE = current lossless all-heading descriptor payload does not fit the unchanged input budget; the pooled label dictionary alone is larger than that allowance.

This is a demonstrated current deterministic contract incompatibility. It is not proof of historical descriptor truncation, Provider failure, model selection nondeterminism, semantic flat-tree navigation inability or a need to rebuild hierarchy.

TREE_SELECTOR_CLOSURE_REQUIRES_TREE_BUILD_SCOPE_EXPANSION = NOT_ESTABLISHED

### TEST_RESULTS / CURRENT_SELECTOR_CORPUS

Receipt: `<private-acceptance-artifacts>/rc1-1cb-regressions.xml`: 45 PASS, 0 FAIL, 0 SKIP.

- Selector forensic tests: 7 PASS (fingerprint, candidate visibility, complete wire/mapping, repeated admission rejection, 1C-A materialization/Coverage integration, absent response truthfulness, isolated imports).
- Provider runtime regressions: 31 PASS.
- Tree build boundary regressions: 7 PASS, including isolated PostgreSQL test schema; production DB untouched.
- Current selector/prompt/descriptor/admission/traversal/Provider/Answer/Top-K production code changes: zero.
- Six-case quality corpus and 3–5 live selection replays: NOT_RUN; current input admission must be addressed first. Not counted as PASS.

### MINIMAL_FIX_PLAN / NEXT_ACTION / stop

Request separate authorization for an admission-compatible locator-input fix, not a speculative model prompt fix. First evaluate generic lossless packing/representation alternatives with the frozen candidate mapping and heading-visibility assertions; if those cannot fit, propose an explicit bounded descriptor/admission policy with evidence-retention tests before implementation. Do not merely raise 16,000 bytes, prune fixture-specific pages/headings, or modify Tree build without authorization.

Only after input admission passes should the fixed Provider/model/settings be qualified and 3–5 live selector replays capture complete raw responses, then integrate sealed 1C-A and assess actual wrong-branch behavior. No current model-quality conclusion is available yet.

COMMIT_THIS_SUBPHASE = NONE
REPORT_ARCHIVE_METADATA_CORRECTED = true
No retrieval-behavior commit, runtime change, deployment, push, Phase 1D or production promotion. Report changes remain uncommitted; diagnostic artifacts are retained on D:.

## RC1 Phase 1C-B1 — Admission-compatible selector input closure

Scope: reversible input representation only. The section above records the prior
audit snapshot, not the current B1 result. No live Provider inference, deployment,
push, model-quality acceptance or next subphase is included.

### WIRE_BUDGET_DECOMPOSITION / CANDIDATE_BYTE_AUDIT

Frozen before-wire bytes: 22,919 = instruction 429 + payload 22,490.
Additive audit: static instruction 429, query text 33, ID JSON strings 464,
title JSON strings 1,036, page-range JSON values 1,071, unique heading text
14,829, heading reference arrays 2,168, remaining JSON keys/punctuation 2,889.
These categories sum to 22,919. Body, summary, provenance and debug fields: zero.

Before expanded candidate descriptor P50/P95/MAX: 175 / 466 / 588 bytes;
sum expanded descriptor bytes: 28,189. This duplicates shared headings and is
not additive with the pooled request's wire size.

After-wire bytes: **15,717 = instruction 621 + payload 15,096**.
Payload value sizes: query JSON 35, phrase dictionary 1,356, encoded heading
pool 11,122, page origin 1, candidate references 2,556; object framing/keys 26.
Compact candidate reference P50/P95/MAX: 17 / 29 / 49 bytes. These reference
sizes exclude shared navigation pools and therefore are not a standalone
descriptor completeness comparison.

BEFORE_BYTES = 22919
AFTER_BYTES = 15717
BYTE_LIMIT = 16000
BYTE_HEADROOM = 283
FULL_CANDIDATE_COUNT = 143
UNIQUE_HEADING_COUNT = 458
PHRASE_COUNT = 89

The byte contract remains UTF-8(instruction + payload), not serialized HTTP
request bytes or tokenizer counts. No limit, candidate ceiling or selected-node
ceiling has changed.

### DESCRIPTOR_FIELD_AUDIT / COMPACTION_POLICY

| Field | Role | Representation |
| --- | --- | --- |
| Query | Required selection input | Exact original text, key q |
| Handle | Required request-local identity | Original n1…n143, no change |
| Original node ID | Stable source identity | Complete host-side bijection, never used as model evidence |
| Title | Navigation | Exact title retained; only exact Page N inferred from page |
| Page range | Navigation/source locator | Consecutive singleton pages use common origin; all other ranges explicit |
| Heading labels | Navigation | All original labels/order retained via shared pool and reversible phrase dictionary |
| Heading references | Navigation links | Ordered index lists; consecutive runs use inclusive ranges |
| Body/summary/provenance/debug | Not selector wire fields | Still absent; no new evidence projection |

Generic codec: q=query, d=phrase dictionary, h=heading pool, p=page origin or
explicit page values, n=[handle, heading references], optional t=title overrides.
Labels use $c for dictionary references; $$ preserves literal dollar signs.
Dictionary phrases are verbatim and non-recursive. Index run encoding preserves
order and duplicates. Phrase ranking is deterministic, uses UTF-8 savings and
non-overlapping occurrence counts; preprocessing has finite phrase/length bounds.
The bounded immutable-content cache carries no query, owner or node identities.

No company, page, oracle, business-question branch or manually chosen heading
is hardcoded in production. No candidate scoring, pruning, traversal or evidence
materialization is added. Titles/headings are never dropped based on relevance.

### HEADING_RETENTION / HANDLE_MAPPING / N3_PREFLIGHT

All 143 descriptors roundtrip exactly: handle, title, page range, every heading
and heading order. All 458 labels remain recoverable. Three independent pure
build_prompt calls yield identical wire bytes and mappings, with zero Provider
attempts. Both main-business headings on the frozen n8 descriptor survive;
risk and audit headings also survive. Distinct navigation under identical titles
is tested. Owner, source projection, 256-candidate and two-selected-node limits
remain enforced; exact 16,000-byte acceptance and 16,001-byte rejection are tested.

EXPECTED_NODE_IN_CANDIDATE_POOL = true
EXPECTED_NODE_ADMITTED = true
EXPECTED_BUSINESS_HEADING_RETAINED = true
EXPECTED_BUSINESS_HEADING_VISIBLE = REVERSIBLY_ENCODED_IN_MODEL_INPUT
HANDLE_MAPPING_VALID = true
CANDIDATE_SET_CHANGED = false
CANDIDATE_ORDER_CHANGED = false
DESCRIPTOR_INFORMATION_LOSS = false
ADMISSION_REQUIRES_STAGED_SELECTION = false for this frozen artifact/query
REAL_PROVIDER_ATTEMPTS = 0

Visibility here means recoverable from supplied schema/dictionary/references,
not that each complete heading appears as a single literal wire substring.
The instructions only explain this field decoding. Selection-policy text,
temperature, output schema, rationale policy and transport remain unchanged.
Model comprehension of the encoding is **not** validated by roundtrip tests.

### DEPENDENCY / OWNERSHIP / COMMIT_BOUNDARY

The pre-B1 selector was untracked historical implementation, not part of sealed
1C-A. Its exact archived SHA256 is
`16e56088e178eaa830fcb6cf1c6da518ed4151f60dfed99c5f3562f625763da3`.
It is preserved byte-identically in Git's LF blob as a non-imported test fixture
(the fingerprint test normalizes Windows checkout CRLF). This commit
explicitly formalizes only that required minimal selector port plus admission
delta; it does not silently include the historical Answer or Tree runtime tree.

| Explicit manifest path | Ownership / reason |
| --- | --- |
| retrieval/ready_tree_decision.py | Historical minimal port; B1 changes only pack_tree_locators, new codec import and field decoding explanation |
| retrieval/tree_locator_codec.py | B1 reversible wire encoding and audit decoder |
| tests/test_tree_selector_admission.py | B1 deterministic admission, identity, policy and negative tests |
| tests/fixtures/rc1/tree_selector_pre_b1.py.txt | Exact pre-B1 selector source snapshot; baseline fingerprint/policy comparison only |
| docs/rc1/phase-1c-tree-retrieval-closure-20261002.md | Prior authorized forensic archive correction and current B1 acceptance report |

Required runtime symbols already tracked in sealed history:
parse_narrative_json (strict Answer parser), ChatRequest (Provider contract),
TreeDecision (Tree contract). All remaining dependencies are standard library.
No additional untracked runtime modules are required. Frozen source-heading
extraction, selector initialization and entire __call__ AST are equal to the
archived historical implementation. Its legacy complete-usage/DeepSeek-attempt
checks are retained unchanged and are not endorsed as new Provider semantics.

Tree build/artifact hierarchy, 1C-A materialization, Provider runtime, Answer,
Hybrid, RRF, Top-K and main worktree's mixed tree_shadow.py changes are excluded.
The candidate is based only on sealed HEAD 7437c49 plus the five explicit paths.

### VALIDATION / LIMITATIONS / NEXT_ACTION

Independent candidate receipts:
`<private-acceptance-artifacts>/rc1-b1-final-regressions.xml` — 163 PASS, 0 FAIL,
0 SKIP; and `rc1-b1-candidate-regressions.xml` — 144 PASS, 0 FAIL, 0 SKIP
(earlier run includes the seven unchanged Tree-build cases, not additional
disjoint tests). The combined unique matrix is 170 tests:

| Group | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| B1 admission/codec/policy | 19 | 0 | 0 |
| Sealed 1C-A baseline + closure | 27 | 0 | 0 |
| Tree shadow | 20 | 0 | 0 |
| Adaptive/Unified Evidence + observability | 18 | 0 | 0 |
| Provider runtime + adapter/factory regressions | 55 | 0 | 0 |
| Answer Provider + ingestion isolation | 24 | 0 | 0 |
| Frozen Tree-build + isolated PostgreSQL boundary | 7 | 0 | 0 |

The Unified Evidence cases validate source text/provenance and conversion into
Agent Evidence and Answer EvidenceSnapshot. PostgreSQL uses only an explicitly
guarded local test database/disposable schema. No production writes.
Scoped Ruff = PASS; diff check = PASS. These are targeted regressions, not a
claim that the entire offline repository suite was run. Existing test warnings
are recorded in the XML and are not counted as test failures or skips.

STAGED_B1_EQUALS_VALIDATED_CANDIDATE = true
Validated/staged/committed tree = 8600ad61ea35463284721c2cfe4f79f60b6a51be.
COMMIT_1C_B1 = 5253dd97e8fd9bbd3b805a465f0a0b7e2459fa34
ACTUAL_HISTORY_VALIDATION = 170 PASS, 0 FAIL, 0 SKIP
Receipt: `<private-acceptance-artifacts>/rc1-b1-actual-history.xml`.
Clean detached checkout of that exact commit, no selector overlay or uncommitted
fixture; scoped Ruff and diff check PASS. These completed results were re-audited
on 2026-10-03; the implementation was not re-committed or rewritten.
COMMIT_1C_B1_SELF_CONTAINED = true
UNTRACKED_HIDDEN_DEPENDENCIES = 0
TREE_CANDIDATE_ADMISSION_FAILURE = CLOSED

RC1_PHASE_1C_B_ADMISSION_STATUS = PASS
RC1_PHASE_1C_STATUS = NOT_ACCEPTED
WRONG_BRANCH_QUALITY_CLOSURE = OPEN

Limitations: 283-byte headroom for this query/artifact; larger inputs still fail
closed. Compression CPU preprocessing and model decoding complexity are real
costs. This is not universal document admission, token-budget qualification,
live semantic selection acceptance, or proof that historical pages 1/39 are fixed.
Exact historical raw-response/artifact-instance recovery remains unavailable.

Next: stop after independent commit/history verification. A separately authorized
live replay must use the fixed artifact/input and record actual raw responses
before any Tree selection-quality conclusion. No live replay in this subphase.

## 2026-10-03 — 1C-B1 final closure and 1C-B2 frozen live selector replay

The new task described B1 as still pending, but the implementation commit and
clean-history acceptance already existed. They were verified, not duplicated:
COMMIT_1C_B1 = 5253dd97e8fd9bbd3b805a465f0a0b7e2459fa34.
Its parent is sealed 1C-A, its scope is exactly the five audited paths, and its
tree matches the validated/staged candidate tree. The main index was empty;
unrelated tracked/untracked work remained outside the commit. Existing actual
history receipt: 170 PASS / 0 FAIL / 0 SKIP. B1 is formally PASS; admission code
was not modified, amended or re-committed during B2.

SUBPHASE_1C_B2_STATUS = MEASUREMENT_COMPLETE_CURRENT_WRONG_BRANCH_REPRODUCED
RC1_PHASE_1C_B_ADMISSION_STATUS = PASS
RC1_PHASE_1C_STATUS = NOT_ACCEPTED
CURRENT_WRONG_BRANCH_REPRODUCED = true
CURRENT_SELECTOR_QUALITY = FAIL_ON_FROZEN_CASE
TREE_SELECTOR_FIX_REQUIRED = true (requires separate 1C-B3 authorization)
PRODUCTION_PROMOTION = NO

### LIVE_REPLAY_ENV / INPUT_DIGEST

Runtime modules were imported only from clean detached commit 5253dd97, not the
dirty main worktree or an untracked selector overlay. A standalone diagnostic
script uses the sealed artifact fixture loader, ProviderFactory/Registry and
ProviderConfig; it constructs no concrete adapter directly and changes no
runtime behavior. Capture is a delegating observer around the real Factory
provider. Source artifacts are content-addressed and hash-checked by the loader.
No Tree rebuild, production DB/index writes, Docker deployment or push.

- Query: `说明贵州茅台的主要业务`.
- Source SHA: `474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288`.
- Tree SHA: `c581f625d6d49252283fa4adedaee74f476098bfcb404b08aef4a7da4b57b036`.
- Quality SHA: `f6735ac9ab7b3944dea564a43683c9adde9391317b8006df02f53aee5f6ece02`.
- Expected node: `50b2dee6c4ce3ff54fa5f5914c6af520:page:8`.
- Expected source block: `46a648eb37d219014c5e73261d8f2888`.
- Complete candidate count: 143; limit 256; selected-node maximum 2; top_k=5.
- Wire bytes: 15,717; unchanged limit 16,000; headroom 283.
- Wire digest: `4e5464e124ec86159f2ff69f8b7b3963e65ce546521d0ff0602b65746a33426f`.
- Candidate-order digest: `a3124795e32dae15c379db5b910ad7cca97b776fd6f7219bbd0238ae1b7859b5`.
- Provider: DeepSeek; model: `deepseek-v4-flash`; endpoint: `https://api.deepseek.com`.
- Temperature 0; max_tokens 512; thinking disabled; selector deadline 60 seconds.
- Deployment Provider timeout 60, connect timeout 10, read timeout 45, total deadline 120 seconds.
- Factory/runtime retry policy unchanged: SDK retries 0; bounded application maximum 3.
- Actual attempts: one per replay, five total. No timeout or application retry.

Model/endpoint/timeout configuration was read from the current deployment.
Only the deployment's DeepSeek credential was used, in process environment,
never printed or persisted in a receipt. Live permission was process-local and
removed after execution; production provider policy/settings were not changed.
The model tag matches the historical reference, but exact historical deployment,
model backend/version, artifact-instance and raw response identity are not proven.

The diagnostic preflight checked the byte count, all handles, expected heading
and invariant input digest before inference. Each run's payload/order digest
was identical. The later offline admission repeat passed 19 tests, zero failures
or skips; this is not substituted for live quality evidence.

### LIVE_REPLAY_RESULTS / RAW_RESPONSES

Full sanitized receipts are retained under
`<private-acceptance-artifacts>/rc1-b2-live-20261003/`:
`input.json`, `run-1.json` through `run-5.json`, and `summary.json`.
Input receipt includes complete instruction/payload, decoded descriptors and
handle mapping. Each run receipt includes the full untruncated structured model
response, finish reason, token usage, resolved nodes/pages, elapsed time,
classification and sealed 1C-A evidence/Coverage. No API key, Authorization
header or secret environment is included.

Diagnostic source: `<private-acceptance-artifacts>/rc1-b2-live-capture.py`.
SHA256: `f9c21258eee7cfec6118c4b2e1470862c0a7ea0a2b909a90a38d35d02a1666aa`.
This is an explicitly disclosed measurement script, not a runtime dependency.

| Run | Handles | Pages | Coverage | Expected block | Latency seconds | Prompt / completion / total | Result |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| frozen-1 | n10, n11 | 10, 11 | INSUFFICIENT | absent | 6.218 | 5995 / 62 / 6057 | WRONG_BRANCH |
| frozen-2 | n10, n11 | 10, 11 | INSUFFICIENT | absent | 0.782 | 5995 / 63 / 6058 | WRONG_BRANCH |
| frozen-3 | n10, n11 | 10, 11 | INSUFFICIENT | absent | 0.719 | 5995 / 63 / 6058 | WRONG_BRANCH |
| frozen-4 | n10, n11 | 10, 11 | INSUFFICIENT | absent | 1.062 | 5995 / 57 / 6052 | WRONG_BRANCH |
| frozen-5 | n10, n11 | 10, 11 | INSUFFICIENT | absent | 0.688 | 5995 / 58 / 6053 | WRONG_BRANCH |

All five finish_reason values are `stop`; API attempts=1; generation=SUCCESS;
usage=KNOWN. Request ID is null because this adapter's normalized response did
not expose one; none was invented. Complete raw structured content was captured
in all five responses. One exact raw example (run-1):

```json
{"selected_node_ids":["n10","n11"],"reason":"n10 covers 第三节 管理层讨论与分析 including 公司从事的业务情况 and 主营业务分析; n11 covers 主营业务分产品/分地区/分销售模式情况, directly relevant to describing 贵州茅台的主要业务."}
```

Resolved selected nodes, identical across runs:
`50b2dee6c4ce3ff54fa5f5914c6af520:page:10` and
`50b2dee6c4ce3ff54fa5f5914c6af520:page:11`.
The five returned 1C-A evidence IDs were also identical across runs:
`24491982f908fe2d3d59b56e7b99cdae`,
`49f35f80066ab2496b9f6b447d21dd3a`,
`4c216a5cf224dd8e3c717e88fed243b1`,
`60eca205952843c9557deadaced51074`,
`4808b653bc106d0702348aa84b445719`.

LIVE_REPLAYS = 5
VALID_SELECTION_RUNS = 5
PROVIDER_FAILURE_RUNS = 0
SELECTOR_PROTOCOL_FAILURE_RUNS = 0
FULL_RAW_SELECTOR_RESPONSE_CAPTURED = true
EXPECTED_NODE_HIT_RATE = 0.0
WRONG_BRANCH_RATE = 1.0
INVALID_SELECTION_RATE = 0.0
COVERAGE_SATISFIED_RATE = 0.0
REQUIRED_EVIDENCE_RECALL = 0.0
LATENCY_MIN = 0.688 seconds
LATENCY_MEDIAN = 0.782 seconds
LATENCY_MAX = 6.218 seconds
TOTAL_USAGE = 30278 tokens (29975 prompt + 303 completion)

Wrong-branch rate is computed over valid selections, excluding Provider failures.
All current selections are legal handles but wrong for the fixed disclosure
requirement. No failed Provider run is mislabeled as a Tree quality failure.
Actual monetary cost was not available; token counts are not converted into
invented billing amounts. These statistics describe five trials of one case,
not the quality of the model or Tree retrieval across all queries.

### FIRST_DIVERGENCE_POINT / FAILURE_CLASS / ROOT_CAUSE

FIRST_DIVERGENCE_POINT = Provider's raw selected_node_ids/rationale, before
host-side handle resolution and before 1C-A materialization.
FAILURE_CLASS = TREE_MODEL_NODE_SELECTION_FAILURE
OBSERVED_SUBCLASS = LOCATOR_HEADING_TO_HANDLE_MISASSOCIATION
TREE_SELECTION_NONDETERMINISM = NOT_OBSERVED_IN_SELECTED_HANDLES

The decoded n8 locator has the exact headings `第三节 管理层讨论与分析` and
`一、报告期内公司从事的业务情况`. n10 instead has product/region/sales-mode
revenue table headings; n11 has cost-composition headings. The raw rationale
incorrectly assigns n8's business/management headings to n10 (and in run-4
assigns the industry heading to n11). Host-side mapping is correct: n10 resolves
to page 10, not page 8. The error is already present in the model output, not
introduced by resolution, transport retry, missing usage or index truncation.

The expected source body explicitly says the company's principal business is
production and sale of Moutai and series wines. The selected pages have related
financial breakdowns, not that expected identity disclosure. Their returned
evidence does not satisfy sealed Coverage. A separate zero-Provider correct-node
control selected n8: expected block present=true and Coverage=SATISFIED. This
isolates the demonstrated failure from sealed 1C-A materialization. It is not a
successful selector replay and is not included in the five-run quality metrics.

ROOT_CAUSE_CONFIRMED = model selection/rationale does not respect the supplied
heading-to-handle association on this compact input, consistently selecting
financial-breakdown nodes instead of the business-identity disclosure node.
ROOT_CAUSE_NOT_ISOLATED = whether reversible dictionary/index decoding burden,
semantic confusion between business description and business breakdown, or
another model navigation limitation is the primary causal mechanism. No
counterfactual prompt/representation experiment was run; the codec cannot be
declared the sole cause, and a Tree rebuild is not justified by these receipts.
The current pages 10/11 failure is not an exact reproduction of historical
pages 1/39; historical root cause remains evidence-limited.

### CURRENT_SELECTOR_QUALITY_CORPUS / NEXT_ACTION / STOP

CURRENT_SELECTOR_QUALITY_CORPUS = NOT_RUN_BY_CONDITIONAL_STOP_RULE
The six-case corpus is required only after the frozen wrong-branch case does
not reproduce. Here it reproduces in 5/5 valid trials, so the task's RESULT 1
stop condition applies. No additional Provider spending or selective corpus
success is used to mask the frozen-case failure.

MINIMAL_FIX_PLAN (proposal only): authorize 1C-B3; preserve this complete failing
receipt as regression; isolate heading/handle decoding versus semantic business
overview/breakdown selection with generic, source-grounded cases; design the
smallest clearer locator association/input-consumption fix within the unchanged
byte/candidate/node/Top-K limits. Revalidate exact mappings and all candidates
before repeating the same fixed live case. No company/page hardcoding, budget
increase, Tree rebuild, Provider runtime or Answer changes are authorized now.

Runtime behavior changes in B2: zero. Frozen selector/codec/Provider/Tree/1C-A
are unchanged; the clean detached replay checkout remains clean. Only this
report is updated in the main repository. No production promotion, deployment,
push or automatic 1C-B3 implementation.

FINAL_RESULT = B1 PASS; B2 CURRENT WRONG BRANCH REPRODUCED;
STOP FOR FIX AUTHORIZATION.

## 2026-10-03 — 1C-B3 representation attribution: no qualified production fix

SUBPHASE_1C_B3_STATUS = ATTRIBUTION_AUDITED; REPRESENTATION_CANDIDATE_NOT_QUALIFIED
RC1_PHASE_1C_STATUS = NOT_ACCEPTED
CURRENT_CODEC_MODEL_COMPREHENSION = FAIL_ON_FROZEN_PROBE
REPRESENTATION_COMPREHENSION_VALIDATED = false (no passing candidate)
PRODUCTION_REPRESENTATION_CHANGED = false
SELECTOR_SEMANTIC_PROMPT_CHANGED = false
PRODUCTION_PROMOTION = NO

### B2_RAW_RESPONSE_ATTRIBUTION_AUDIT

The ten selected-handle claims across five B2 raw responses were checked against
lossless decoded descriptors, not inferred from selected page numbers alone.
Complete entries, including each original claim and all actual headings, are in
`<private-acceptance-artifacts>/rc1-b3-probe-20261003/b2-attribution-audit.json`.

| B2 run | n10 / page 10 claim | n11 / page 11 claim | Attribution audit |
| --- | --- | --- | --- |
| 1 | management discussion/company business | product/region/sales-mode business breakdown | both contradict actual handle headings |
| 2 | management discussion/company business | product/region/sales-mode business breakdown | both contradict actual handle headings |
| 3 | management discussion/company business | product/region/sales-mode business breakdown | both contradict actual handle headings |
| 4 | management discussion/company business | company industry situation | both refer to headings belonging to n8 |
| 5 | management discussion/company business | product/industry business analysis | n10 definite error; n11 broad wording is indeterminate |

Actual n10 headings are financial revenue/margin breakdown labels; actual n11
headings concern cost composition. The business/management/industry headings
are attached to n8. The vague fifth-run n11 claim is not forced into a definite
error category merely because the overall selection failed.

HANDLE_ATTRIBUTION_ERRORS = 9 definite / 10 selected-handle claims
HANDLE_ATTRIBUTION_ERROR_RATE = 90% of all claims; 100% of 9 assessable claims
ATTRIBUTION_UNDETERMINED = 1 / 10
SEMANTIC_SELECTION_ERRORS = NOT_INDEPENDENTLY_IDENTIFIABLE
EXPECTED_HANDLE_IDENTIFIED_RATE_FROM_B2 = UNKNOWN
EXPECTED_HANDLE_SELECTED_RATE_FROM_B2 = 0%

Not selecting n8 does not prove the model knew or did not know its identity.
These raw responses prove misattribution, not semantic selection error with
correct attribution. A separate comprehension experiment was therefore needed.

### CODEC_COMPREHENSION_PROBE / ORACLE / PREDECLARED_GATE

Frozen runtime baseline remains 5253dd97e8fd9bbd3b805a465f0a0b7e2459fa34,
using the same hash-checked source/Tree/quality artifacts, original business
query in q, full 143-candidate set/order, DeepSeek/deepseek-v4-flash,
temperature 0, max_tokens 512, unchanged runtime/deadlines and 16,000 bytes.
Diagnostic instructions request exact heading lookup only, not relevance or
financial selection; their results cannot certify production selection quality.

Sixteen deterministic source-derived cases cover early/middle/late candidates,
short/long descriptors, shared/unique/similar headings and one frozen failure
anchor. Targets contain headings only; expected handles/pages never enter
model instructions. Oracles come from the sealed lossless decoder. Shared
headings have exactly two matching handles and require both; returned unknown,
duplicate or extra handles cannot qualify. Every call contains the complete
unchanged candidate set, not only the sampled candidates.

Gate declared before calls: all 16 cases in both repetitions must have handle,
heading and page accuracy=1.0, complete coverage and zero protocol/runtime
failures. Two successes on the business anchor do not override failures elsewhere.

### REPRESENTATION_ABLATION / HOST_ROUNDTRIP

A = unchanged B1 codec: shared encoded heading pool, reference indexes/ranges,
and page-origin inference.
B = diagnostic-only inline map: each handle directly owns [page, heading,...];
the same phrase dictionary and encoded heading strings are retained. This
removes the global heading-index join and puts explicit page values beside the
handle. It is an experimental data-layout candidate, not production code.

B payload = 15,317 bytes. The controlled A/B diagnostic calls used identical
instructions, target cases, batches, model and settings. A wire range was
15,637–15,738; B wire range 15,858–15,959; no budget increase.
All 143 identities, exact titles/pages/headings, duplicates and heading order
roundtrip exactly; candidate ordering and dictionary are unchanged. Test-only
roundtrip coverage includes dollar markers, quotes, newlines, Unicode, custom
titles, nonconsecutive pages and multipage ranges.

### A_B_RESULTS — controlled comprehension protocol, not selector replay

| Metric | A current | B inline |
| --- | ---: | ---: |
| Unique cases / repetitions | 16 / 2 | 16 / 2 |
| Valid evaluated case observations | 32 | 32 |
| Handle lookup accuracy | 4/32 = 12.5% | 15/32 = 46.875% |
| Heading attribution accuracy | 4/32 = 12.5% | 12/32 = 37.5% |
| Page attribution accuracy | 2/32 = 6.25% | 10/32 = 31.25% |
| Invalid-handle rate | 0% | 0% |
| Missing/duplicate/cardinality ambiguity | 4/32 = 12.5% | 15/32 = 46.875% |
| Provider / protocol failures | 0 / 0 | 0 / 0 |
| Predeclared hard gate | NOT_PASS | NOT_PASS |

Valid handle syntax is not correct attribution. B improved lookup by 34.375
percentage points in this finite paired set, but remained far below the gate;
no claim of universal comprehension or statistical significance is made.

| Case | Exact source heading | Decoder oracle handles | A correct | B correct |
| --- | --- | --- | --- | --- |
| 0 | 重要提示 | n2 | 0/2 | 1/2 |
| 1 | 三、公司基本情况 | n72 | 0/2 | 0/2 |
| 2 | 十九、 补充资料 | n142 | 0/2 | 2/2 |
| 3 | 六、税项 | n83 | 2/2 | 2/2 |
| 4 | b. 利息支出 | n132 | 0/2 | 2/2 |
| 5 | (一) 员工情况 | n31 | 0/2 | 0/2 |
| 6 | 留存收益 | n106 | 0/2 | 2/2 |
| 7 | 2024 年度 | n69,n71 | 0/2 | 0/2 |
| 8 | 2025 年度 | n68,n70 | 0/2 | 0/2 |
| 9 | 贵州茅台酒股 份有限公司 | n129 | 0/2 | 0/2 |
| 10 | 贵州茅台酒股份有限公司 | n1 | 1/2 | 1/2 |
| 11 | 一年内到期的债权投资 | n91 | 0/2 | 1/2 |
| 12 | 一年内到期的其他债权投资 | n93 | 0/2 | 1/2 |
| 13 | 2025 年年度报告 | n1 | 1/2 | 0/2 |
| 14 | 六、前瞻性陈述的风险声明 | n2 | 0/2 | 1/2 |
| 15 | 一、报告期内公司从事的业务情况 | n8 | 0/2 | 2/2 |

Expected-handle identification on the anchor: A=0/2, B=2/2. This demonstrates
why a business-only fixture would misleadingly favor B: shared, middle and
similar-heading cases still fail. B is rejected, not promoted.

### PROBE_DESIGN_LIMITATIONS / COMPLETE_RECORDS

An initial standalone current-codec pilot also failed: handle/heading 3/32,
page 2/32, zero Provider/protocol failures. Its diagnostic wording differs from
the controlled A/B protocol, so it is not averaged into those paired results.

The numeric [1,1] schema example could anchor page output. A final diagnostic
protocol removed concrete example defaults; it produced eight fenced-JSON
parse failures among twelve A calls, with only eight case observations admitted
and zero correct handle lookups among them. These are structured-output
failures, not Provider outages. The corresponding B arm was blocked before any
call: identical batches would exceed 16,000 bytes. No regrouping, budget increase
or tolerant fenced-JSON parsing was used to manufacture a passing comparison.
This incomplete final protocol is not claimed as a balanced A/B experiment.
The possible example-value confound particularly limits causal interpretation
of page scores; the numerous wrong-handle observations remain independently
visible in the valid controlled response set.

All raw responses and reconstructed requests are retained:
- `<private-acceptance-artifacts>/rc1-b3-probe-20261003/pilot-A/` — initial pilot.
- `<private-acceptance-artifacts>/rc1-b3-probe-20261003/` — controlled A/B, protocol,
  source-derived oracles, complete raw responses and summaries.
- `<private-acceptance-artifacts>/rc1-b3-probe-final-20261003/` — revised diagnostic
  protocol and its failures/blocked B arm.

Each directory has `verified-request-manifest.json`: the complete instructions,
targets, oracle, payload binding and every request's digest/byte length were
reconstructed and matched offline, including the initial pilot. All 48 requests
verify <=16,000 bytes. Captures contain no credential, Authorization header or
secret environment. Diagnostic sources reside on D: and are explicitly
measurement-only; no production module imports them.

### ROOT_CAUSE / IMPLEMENTATION_DECISION

Confirmed partial root-cause class:
TREE_SELECTOR_REPRESENTATION_COMPREHENSION_FAILURE /
TREE_HANDLE_ATTRIBUTION_FAILURE on the current model/frozen locator corpus.
Host losslessness does not imply model interpretability. Broad exact-lookup
failures exist without financial relevance judgment, so B2 is not attributable
solely to choosing a semantically less relevant but correctly understood node.

Not established: codec is the sole cause of B2; which dictionary/index/range
mechanism dominates; all flat-page navigation is inherently impossible; or
architecture expansion is necessary. No such stronger conclusion is reported.
TREE_WRONG_BRANCH_CLOSURE_REQUIRES_ARCHITECTURE_EXPANSION = NOT_ESTABLISHED

REPRESENTATION_FIX = NONE (B does not meet admission/comprehension qualification)
SEMANTIC_SELECTOR_DIAGNOSIS = DEFERRED (attribution prerequisite not passed)
SELECTOR_PROMPT_CANDIDATES = 0
NEW_PRODUCTION_SELECTOR_LIVE_REPLAYS = 0
QUALITY_CORPUS = NOT_RUN (comprehension hard gate not met)

The narrow phase gate blocks downstream live-selection and six-class quality
corpus acceptance. No single-case success, parser relaxation, source pruning,
model switch, fallback or semantic prompt patch bypasses it.

### PROVIDER_USAGE / REGRESSIONS / COMMIT_BOUNDARY

| Purpose / protocol | Calls | Tokens | Latency min / median / max seconds |
| --- | ---: | ---: | --- |
| Current-codec pilot | 12 | 73,165 | 0.391 / 0.711 / 1.906 |
| Controlled A comprehension | 12 | 73,266 | 0.610 / 0.711 / 1.860 |
| Controlled B comprehension | 12 | 75,226 | 0.500 / 0.735 / 1.813 |
| Final protocol A diagnostics | 12 | 73,079 | 0.391 / 0.649 / 1.719 |
| Final protocol B | 0 (admission blocked) | not applicable | not applicable |

B3 total: 48 Provider calls, 294,736 reported tokens. These are comprehension
costs only, not production-selector replay usage. Provider transport failures=0;
eight structured-output failures are kept separate. Actual billing is unknown.
All calls used the same DeepSeek model/endpoint and formal Factory/runtime;
SDK retries stayed disabled, each actual response reported one API attempt.

Independent diagnostic candidate: 176 PASS plus 29 additional PASS = 205 unique
targeted tests, zero failures/skips. Two formal READY-promotion cases were
explicitly deselected, not counted as PASS; PostgreSQL acceptance was not rerun
in B3. The suite includes eight new diagnostic tests, 19 B1 admission tests,
27 1C-A tests, Tree shadow/Unified Evidence, Provider runtime/adapters/factory,
Answer Provider/isolation, nine FinancialFact and 22 Core Index evidence tests,
and five query-free Tree-build boundary tests. It is not the full repository
offline suite. Scoped Ruff and diff check PASS.

No production behavior changed. Budget/count/order/Top-K, Tree build,
materialization, Provider runtime, Answer, Hybrid, FinancialFact and Index stay
frozen. In the tested 1C-A fixtures, false satisfied/provenance loss remain zero.
Untested gates are not promoted to PASS merely because files were unchanged.

Explicit diagnostic-only commit manifest:
`tests/test_tree_selector_attribution_contract.py` (test-only unqualified layout
roundtrip and invalid-handle rejection) and this report. No runtime fix commit;
REPRESENTATION_FIX_COMMIT = NONE; SEMANTIC_SELECTOR_FIX_COMMIT = NONE.
Clean committed-history targeted receipt is recorded separately at
`<private-acceptance-artifacts>/rc1-b3-actual-history.xml`; immutable diagnostic commit
SHA and actual result are supplied in the final handoff after verification.

NEXT_ACTION: stop with no qualified production replacement. Further representation
research must first meet the same predeclared gate within the unchanged budget;
do not enter production replay, semantic prompt repair or Tree-build expansion
on the strength of the business anchor alone.
