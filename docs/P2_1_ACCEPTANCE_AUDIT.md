# P2.1 acceptance audit

Status: IN_PROGRESS. This is a completion checklist, not a PASS declaration.

## Requirements and current evidence

| Requirement | Evidence | Current disposition |
|---|---|---|
| Phase 0 real architecture | P2_1_PHASE_0_RETRIEVAL_ARCHITECTURE_AUDIT.md | Complete |
| Existing Fact/BM25/vector/RRF preserved | No P2.1 edits in production composition/scoring modules | Verify final diff |
| Unified request/result/evidence/protocol | retrieval/adaptive_contract.py | Implemented, targeted tested |
| Fact adapter and dimension preservation | test_adaptive_fact_integration.py, five real SQLite metrics | Passed |
| Hybrid adapter full metadata | adaptive_adapters.py, real local embedding benchmark | Passed wiring; document-local corpus |
| Tree projection source safety | tree_shadow.py, READY compatibility report required | Tested |
| Tree quality | ranges/parent-child/cycles/source coverage/cache corruption tests | Tested |
| Tree version/cache/local artifacts | JSON artifact, tenant/hash/source digest/parser/tree policy key | Tested |
| Structured traversal | TreeDecision, bounded rounds, branch escape rejection, aggregate usage | 25 tree/benchmark tests passed |
| Source-backed final evidence | Actual block text only; summary exclusion test | Tested |
| Shadow primary invariant | Identity-preserving run_shadow; EXACT_FACT skip; isolated failure | Tested |
| Query classes/hypotheses/planner boundary | Ten classes; metadata-only hypotheses | Implemented |
| Coverage interface | CoverageReport, no recursive research promotion | Implemented |
| PageIndex assessment | Official license/local mode audit; architecture reference, no install | Complete, dependency compatibility unverified because unused |
| Retrieval-only A/B | Real embedding + HybridRetriever + local cosine store; narrative 10Q | Executed, report export available |
| Reviewed gold and provenance | Bounded narrative excerpt, reviewed native anchors and source blocks | Executed; complete annual report still quarantined |
| Tree not forced to win | Hybrid 5 / Tree 1 / tie 4, three both miss | Recorded |
| Fact numeric priority | Real adapter integration + unchanged P1.7 primary composition | Need final route regression suite evidence |
| Exhaustive coverage case | Narrative risks + prevention asks two gold blocks | Both missed; valid outcome, no tuning |
| Similarity vs relevance | Producer capacity question, semantic class | Hybrid hit, Tree miss |
| Exact phrase BM25 advantage | Real phrase case Hybrid win; no scoring edits | Recorded |
| Multi-document/three-year boundaries | Classified incomplete corpus, not given fake correctness | Recorded |
| Unified trace/failure taxonomy | adaptive_observability.py, unknown usage preserved null | Targeted tested |
| Benchmark cost/latency | JSON per-query fields; provider zero; compute cost unknown | Recorded |
| Full offline suite | Existing running handle 10531 | Pending terminal result |
| Ruff/diff | Whole repo Ruff PASS, diff check PASS with preexisting CRLF warning | Recheck final snapshot |
| Independent commit | P2.1 imports untracked upstream P1.6.2 package | Boundary unresolved; do not mix upstream silently |
| Final report | Checkpoint and this acceptance audit | Final comprehensive report pending |

## Required final dispositions

Do not declare P2.1 PASS until full suite/targeted final snapshot and route regression evidence are available. Tree benchmark recall need not be perfect; benchmark failure is allowed if honestly measured. Tree remains SHADOW/offline, no Provider required, no production DB/index writes or deployments.

Commit must retain a reproducible upstream dependency boundary. P1.6.2 files currently untracked cannot silently be included in P2.1 commit.

## Latest verification

Final P1.7/P2.1 targeted snapshot: 68 passed, 1 warning (108.44s). Additional Fact benchmark preference test set: 6 passed. Whole repository Ruff PASS; git diff --check PASS (preexisting hybrid file CRLF conversion warning only).

Fact adapter refuses metric/year/period/scope mismatch. Five real reconstructed/persisted metrics still FOUND through existing SQL lookup. Production composition files have no references to new adaptive_contract/tree_shadow modules; no new production route introduced.

Remaining: full offline process terminal result, comprehensive final report, independent commit lineage. Full test session 10531 remains running above 95%; do not restart or report success until terminal evidence.
