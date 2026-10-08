# Proposed independent commits

User explicitly authorized two independent local commits on 2026-09-30. P1.6.2 prerequisite committed separately as 35eccf8. No push or deployment is authorized by this commit task.

## Commit A — P1.6.2 prerequisite

Proposed title: `feat: add offline financial document compatibility audits`

Include only:

- document_compatibility/__init__.py
- document_compatibility/adapters.py
- document_compatibility/engine.py
- document_compatibility/models.py
- document_compatibility/policy.py
- document_compatibility/promotion.py
- document_compatibility/structural_audit.py
- scripts/document_compatibility_audit.py
- tests/test_document_compatibility.py
- tests/test_document_compatibility_structure.py
- tests/fixtures/compatibility/manifest.json
- docs/P1_6_2_IMPLEMENTATION_CHECKPOINT.md
- docs/P1_6_2_PHASE_0_DOCUMENT_COMPATIBILITY_AUDIT.md

Source dependencies on document_loader and financial_metric_registry are already tracked at HEAD. Read-only source checks confirmed required parser helpers exist at HEAD. No production worker wiring or Docker override included.

## Commit B — P2.1

Proposed title: `feat: add adaptive retrieval shadow architecture`

Include new retrieval/adaptive_contract.py, adaptive_adapters.py, adaptive_observability.py, tree_shadow.py; evaluation/adaptive_retrieval_benchmark.py, p2_1_real_hybrid.py; evaluation/datasets/p2_1_moutai_source_manifest.json; scripts/p2_1_narrative_excerpt.py; the five test_adaptive*/test_tree_shadow test modules; only P2_1 documentation.

Do not include existing changes in core/answer_policy.py, core/fact_ledger.py, core/financial_grounding.py, core/required_fact_plan.py, retrieval/hybrid_retriever.py, tasks/knowledge_tasks.py, their historical tests, or deploy/docker-compose.moutai-v20.override.yml. No generated evaluation results, downloaded PDF, local database, cache, credentials or model artifacts.

Before each commit: verify exact staged file list and diff; run cached diff check. After both commits: test reproducible tracked tree with upstream present, verify dirty baseline preserved and report hashes. Do not push or deploy.

## Verification evidence

Full offline working-tree run: 2935 passed / 3 skipped / 21 deselected. Final targeted P1.7/P2.1 snapshot: 68 passed, additional 6 benchmark tests passed. Whole repository Ruff passes. After separate commits, isolated git-archive source snapshot passed 130 tests / 1 skipped and Ruff. Historical dirty files were not copied into the snapshot, staged, or committed. The isolated full offline suite was not rerun. No push or deployment performed.
