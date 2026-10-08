# P2.1 implementation and verification report

P2_1_STATUS = IMPLEMENTATION_AND_COMMIT_DEPENDENCY_VERIFIED

Date: 2026-09-30. User authorized separate prerequisite and P2.1 commits. P1.6.2 prerequisite is committed as 35eccf8. Isolated git-archive snapshot of the P2.1 commit passed 130 tests, with 1 skip and 1 deprecation warning (114.89 seconds); isolated Ruff passed. The full working-tree offline suite previously passed 2935 tests / 3 skipped / 21 deselected; this full suite was not rerun in the isolated snapshot. No production deployment or push is performed. These checks verify the committed dependency boundary, not production answer superiority.

## Architecture and contracts

CURRENT_RETRIEVAL_ARCHITECTURE: AgentRuntime intent/plan → P1.7 SQL FinancialFact or existing tenant-scoped Hybrid(BM25/vector/RRF) → agent Evidence → context/citation/grounding → answer. See the Phase 0 audit for exact composition points.

NEW_RETRIEVAL_ARCHITECTURE: isolated FACT/HYBRID/TREE adapters return unified evidence/results. run_shadow returns original primary by identity; shadow output is diagnostics only. No production composition entry imports the new modules.

RETRIEVER_PROTOCOL: retrieve(RetrievalRequest) → RetrievalResult.

RETRIEVAL_REQUEST_SCHEMA: reuses trusted tenant-scoped tool request; adds conversation, metric, fiscal year, period, financial scope, intent, precision, breadth, query class and preferred modes. Existing Hybrid internals remain intact.

RETRIEVAL_RESULT_SCHEMA: FOUND/NOT_FOUND/AMBIGUOUS/CONFLICT/PARTIAL/UNSUPPORTED/ERROR, route, evidence, coverage interface, deterministic flag, latency, cost, fallback reason and trace.

UNIFIED_EVIDENCE_SCHEMA: identity, type, document/company, source kind/name, page/bbox/locator/source-block ids, text, structured value, metric, period, scope, statement, retriever, confidence, full provenance and citation.

FINANCIAL_FACT_ADAPTER: wraps existing SQL lookup result without changing fact identity; validates request/evidence metric/year/period/scope and tenant/document boundaries. Five real persisted metrics tested: assets, cash/bank balances, net income, attributable net income, operating cash flow.

HYBRID_ADAPTER: wraps existing retrieve method, preserving raw source metadata. BM25, embedding, RRF scoring and production Top-K are unchanged. Local real-embedding benchmark uses isolated cosine store, not production Chroma.

## Tree and shadow

TREE_INDEX_MODEL / TREE_NODE_SCHEMA: immutable document projection with parent/child identity, title, level, pages, summary hint, canonical source-block ids, source kind/version/provenance. Tree stores document hash, schema/builder/policy/model versions.

TREE_BUILD_STRATEGY: canonical section grouping, or explicitly LOW fallback page tree. Current section projection depth is 1; it is not a complete nested semantic heading reconstruction.

TREE_QUALITY_RULES: whole-tree identity, cycles, parent/child/range validation, page/source coverage, orphan pages, summary coverage; legal ancestor nesting is accepted, shared sibling source ownership is rejected. Empty placeholder pages count toward inventory coverage only.

TREE_REASONING_RETRIEVER: injectable structured TreeDecision; optional bounded child traversal rejects hallucinated or escaped-branch nodes. Actual source blocks become evidence; summaries never become authoritative evidence. Usage sums across decision rounds.

TREE_SOURCE_PROVENANCE: source ids, bbox/locator, parser version, recovery provenance and tree/document versions retained. JSON artifact cache is isolated by tenant/document/hash/parser/tree policy/source digest; corrupt artifacts fail closed.

SHADOW_MODE_DESIGN: primary is returned unchanged on success/failure; EXACT_FACT skips tree. No production switch, database migration or reindex.

## PageIndex and benchmark

PAGEINDEX_INTEGRATION_ASSESSMENT = ARCHITECTURE_REFERENCE. Official MIT license and local-mode documentation reviewed. PAGEINDEX_DEPENDENCY_DECISION = NOT_INSTALLED. No Cloud upload, external model call or requirements change. Package conflicts/Python compatibility not assessed because dependency is not introduced.

BENCHMARK_CORPUS: existing verified statement fixture and independently READY narrative excerpt from official CNINFO annual report. Complete original report is QUARANTINED for merged-cell ambiguity; it is not admitted whole. Excerpt source pages 8/9/21/22/23 retain original physical page numbers, 79 source blocks. Source SHA and reproduction script are recorded in manifest.

QUERY_CLASSES: exact fact, exact phrase, local semantic, section, exhaustive, causal, cross section, trend, ambiguous, multi document. All classes exist in framework; reviewed narrative corpus covers phrase/semantic/section/exhaustive/causal; real SQLite integration covers five exact facts. Multi-year/multi-company gold remain unavailable rather than fabricated.

RETRIEVAL_FAILURE_TAXONOMY / OBSERVABILITY: all requested 14 failures plus shared RetrievalTrace; unknown candidate counts/costs stay null. Answer accuracy is NOT_EVALUATED in retrieval-only runs. Fact comparison is optional; a source-validated exact fact remains preferred.

## Results

P1_7_ROUTE_REGRESSION = 0 in final targeted tests; FINANCIAL_FACT_REGRESSION = 0 for the five real metrics. HYBRID_REGRESSION = 0 in offline suite relative to current dirty baseline; no P2.1 scoring edits.

Narrative tree: TREE_NODES=53, TREE_DEPTH=1, TREE_PAGE_COVERAGE=100% of excerpt inventory, TREE_BLOCK_COVERAGE=100%, TREE_QUALITY=MEDIUM. Only five pages contain actual content; no full-report coverage claim.

13 reviewed narrative cases: HYBRID_WIN_COUNT=8, TREE_WIN_COUNT=1, TIE_COUNT=4. Three ties represent both retrievers missing gold. FACT_WIN_COUNT is not aggregated into this narrative-only A/B run; five independent SQL Fact integration cases pass.

All returned narrative evidence source/page checks pass, CITATION_MISMATCH_COUNT=0. COVERAGE_INCOMPLETE_COUNT is nonzero. No tree superiority or production promotion conclusion.

TREE_HALLUCINATED_NODE_ACCEPTED=0, TREE_SOURCELESS_FINAL_EVIDENCE=0, TREE_REBUILD_ON_REPEAT_QUERY=0, TENANT_LEAK=0 and SHADOW_TREE_CHANGES_PRIMARY_ANSWER=0 in targeted safety tests. TREE_WRONG_BRANCH_COUNT requires reviewed node-selection gold; branch escape rejection is tested, but no fabricated global wrong-branch count is reported.

PRIMARY_ANSWER_CHANGED_BY_SHADOW_COUNT=0 in wrapper tests; production path unchanged. No live production shadow run is claimed.

Per-query recall/precision/citation/coverage/latency/calls/token/cost fields and winner reasons are in `<private-acceptance-artifacts>/p2_1-corpus/narrative-ab-report.json`. Typical observed Hybrid latency 16.8–34.2 ms, Tree 113.0–147.9 ms for this local warm run. This is not a general performance benchmark.

TREE_PROVIDER_CALLS=0; TREE_BENCHMARK_COST=0 generation-provider cost; embedding compute cost unknown. No answer generation evaluation.

## Verification

FULL_OFFLINE_TEST_RESULTS: 2935 passed, 3 skipped, 21 deselected, 1 warning, 1272.65s. This run began before the final incremental additions; final changed modules additionally verified by 68 passed targeted P1.7/P2.1 run and 6 passed benchmark tests. Later narrative query additions executed in real local model benchmark.

RUFF_STATUS=PASS whole repository. DIFF_CHECK_STATUS=PASS (preexisting CRLF conversion warning). No staged changes.

FILES_CHANGED: new retrieval/adaptive_contract.py, adaptive_adapters.py, adaptive_observability.py, tree_shadow.py; evaluation/adaptive_retrieval_benchmark.py, p2_1_real_hybrid.py; scripts/p2_1_narrative_excerpt.py; five adaptive/tree test modules; P2.1 audit/checkpoint/report docs and source manifest. Historical dirty production paths are not part of P2.1.

COMMIT=NOT_CREATED. DEPLOYMENT_BLOCKERS: P2.1 is shadow-only by design; no production promotion authorized by this phase. Submission blocker: P1.6.2 document_compatibility modules remain untracked. An independent P2.1 commit without those upstream modules would be incomplete; silently staging them violates the requested scope.

KNOWN_LIMITATIONS: shallow section projection; deterministic local title-embedding orientation benchmark, not real LLM reasoning benchmark; excerpt corpus; conservative full-document quarantine; no final adaptive production policy, no iterative research, no live answer accuracy; no complete multi-year/multi-company gold.

NEXT_STEP: resolve upstream commit boundary explicitly, finish reproducible isolated commit review, then P2.2 broader benchmark. Do not start P2.3 production routing or auto-promote Tree.
