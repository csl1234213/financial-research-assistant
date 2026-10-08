# P1.4.6 Offline Final-Answer Repair

## Scope and safety

This repair uses historical answers and saved evidence only. New provider calls: **0**.
Evaluator calls: **0**. New API cost: **$0**. No real 5Q/100Q run, commit,
push, database mutation, volume deletion, or historical artifact deletion was performed.
Existing unrelated working-tree changes are preserved.

## Findings and production changes

1. `core.answer_policy.finalize_grounded_answer` is the production boundary after
   generation. It scopes the response, grounds claims, completes missing required
   facts from the evidence ledger, then validates those additions again.
2. Removed the late unscaled fact appender and unchecked reasoner appendix from
   the final report path. Table values retain their units and printed column periods.
3. Evidence numbers are scoped to the matching metric row. Incidental references
   to net income in a cash-flow reconciliation are not net-income facts.
4. Explicit citations are bindings. Another company's matching number or a
   different cited chunk cannot rescue a claim. Clauses are checked separately.
5. Citations remain attached to their clauses before punctuation. Both original
   post-sentence citations and repeated sanitization are regression-tested.
6. Completed facts use readable periods (`Q2 2025`, not internal `Q2_2025` keys),
   explicit currency, source references, and cumulative-period labels when supplied
   by the ledger. Correct table facts survive even with unknown document metadata.
7. Metric comparisons no longer require unrelated strategy, infrastructure,
   investment, risk, and outlook sections. Retrieval weights and Top-K were not tuned.
8. Smoke collection fails closed when production audit capture is disabled, stale,
   missing full evidence, or inconsistent with the actual response. HTTP outcomes
   are saved before post-processing. Original raw output is recorded separately
   from prepared and final answers.

## Correcting the interpretation of the third 5Q run

The third run recorded `raw_llm_answer=null`, empty retrieved/context evidence,
and empty grounding results. Its harness read a different default audit location.
Consequently, the historical **80 unsupported numbers** is an unverified report-level
measurement, not proof of 80 incorrect financial claims. Historical files remain unchanged.

The newest replay is under
`evaluation/results/p1_4_6_offline_repair/verified_02/`.
It calls the same production final-answer policy, but its input is the historical
**final answer**, not the missing original raw generation. Evidence uses exact chunk
IDs with a saved current snapshot captured on 2026-09-15. This is not proof of the
original request's exact context, new model accuracy, or a successful live smoke.

| Latest final-answer replay | Required-fact coverage | Unsupported numeric claims |
| --- | --- | --- |
| ZH-013 | 100% | 0 |
| EN-016 | 100% | 0 |
| EN-019 | 100% | 0 |
| ZH-019 | 100% | 0 |
| ZH-008 | 100% | 0 |

An independent older raw-answer replay is included separately. Two comparison
cases lack exact original Tesla chunk content and are explicitly marked partial;
the missing data is not fabricated. Other older contexts do not necessarily
contain all required facts. Their safe insufficiency is not counted as success.

## Validation

- Focused grounding/ledger/audit/prompt tests: 135 passed; an additional readable
  period regression subsequently passed in the 10-test final-policy module.
- Frontend: 31 tests passed; production build passed.
- Repository Ruff: passed.
- `git diff --check`: passed.
- Full offline backend suite: **2,217 passed, 2 skipped, 21 deselected**, zero
  failures, 256.66 seconds. One pre-existing FastAPI/Starlette deprecation warning.
- Docker: initially unavailable, then recovered during validation. Canonical
  project `financial-rag-prod` passed Compose configuration validation. Rebuilt
  the shared backend image and recreated only backend and agent-worker with
  `up -d --no-deps`; no volumes or databases were deleted.
- All six services healthy after update. `/api/v1/health` and `/api/v1/ready`
  returned HTTP 200. Backend `ALLOW_REAL_PROVIDER=false` was confirmed.
- SHA-256 of all six updated production Python files matched local source in
  the running backend: answer policy, grounding, core engine, fact ledger,
  required-fact plan, and prompt builder. The worker shares that runtime image.
- Compose reported existing uploads/logs/Redis volumes with older project labels.
  These existing volumes were preserved; no volume-label cleanup was attempted.

Commands use `ALLOW_REAL_PROVIDER=false`; no live marker opt-in:

```powershell
$env:ALLOW_REAL_PROVIDER='false'
$env:EVALUATION_BYPASS_PLAN_LIMITS='false'
$env:EVALUATION_BYPASS_TENANT_IDS=''
python -m pytest tests -m 'not live' -q --tb=short
python -m ruff check .
git diff --check
python -m evaluation.replay_p1_4_6 --snapshot evaluation/results/p1_4_6_offline_repair/evidence_snapshot.json --output evaluation/results/p1_4_6_offline_repair/<new-run-directory>
# In frontend:
npm test
npm run build
```

The replay refuses to overwrite an existing output directory. No audit-induced
environment secret changes or credential outputs are required.

The first full pass recorded 2,206 passed and nine failures. Seven were quota
tests inheriting local evaluation-bypass settings; disabling those settings only
inside the test process restored quota enforcement. One was the prompt-version
manifest (updated to 2.3.0 without changing questions or expected criteria), and
one was a citation-placement assertion loaded before the corrected test was saved.
The 53-test focused rerun covering these areas passed. Local `.env` and production
quota settings were not changed.

## Repair files

- `core/answer_policy.py`, `core/answer_grounding.py`, `core/core_engine.py`
- `core/fact_ledger.py`, `core/required_fact_plan.py`
- `prompt_builder.py`, `evaluation/benchmarks/financial_model_benchmark_v1.json`
- `evaluation/p1_4_1_real_provider_fact_ledger_recheck.py`, `evaluation/replay_p1_4_6.py`
- `tests/evaluation/test_final_answer_policy.py`, `tests/evaluation/test_answer_grounding_contract.py`
- `tests/evaluation/test_fact_ledger_row_grounding.py`, `tests/evaluation/test_smoke_audit_integrity.py`
- `tests/test_prompt_builder.py`, this report, new offline replay artifacts

These are repair-related paths, not a claim that every existing Git modification
belongs to this repair. Many pre-existing dirty paths remain untouched.

## Gate

Offline repair and regression gate: **PASS**.
Docker application and health gate: **PASS**.
`READY_FOR_REAL_5Q: YES`, subject to explicit authorization for the next paid run.
No new paid run is authorized by this report. Historical raw-output gaps remain;
this repair is not a retrospective PASS of the third real 5Q run.
