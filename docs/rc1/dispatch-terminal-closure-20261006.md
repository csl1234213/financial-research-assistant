# Dispatch terminal closure contract (D3-P0R-P1)

Pre-fix baseline: bf0bf684fbf090cb565f53b1b87882c1b2d7fb13.
This fixes terminal dispatch eligibility, not a proven historical duplicate execution.

TaskStatus defines pending/running/success/failed. Formal document authority also
includes ready/failed/quarantined; exhausted stages are persisted as failed.
There is no cancelled/quarantined/exhausted TaskStatus to add in this repair.
Dispatcher task-state allowlisting excludes unknown future states safely.

Existing dispatch `none` means no outstanding dispatch is required. Terminal task
transitions withdraw active pending/leased obligations to none, clear lease/retry
reservations and set TASK_TERMINAL as the withdrawal reason. Attempts are preserved.
Existing delivered/failed transport outcomes remain unchanged. Completion is never
misrepresented as transport delivery; no schema or migration change is needed.

Authority: TaskRepository owns generic task terminal transitions, the formal ledger
owns permanent failure/quarantine/exhaustion, and ReadyPromotionService owns formal
READY/success. Closure is in the same transaction as each terminal transition, with
Task-first row-lock ordering. Retryable formal stage failures do not close dispatch.
Worker transient FAILED -> PENDING restores only an active obligation that was
withdrawn by TASK_TERMINAL, without creating historical obligations or resetting
attempts; terminal formal document authority prevents restoring dispatch eligibility.
Committed success is not overwritten by a late handler failure/retry.

Dispatcher claim additionally requires pending/running execution and nonterminal
formal document authority through the finalized UploadSession binding. This protects
historical stale rows without rewriting them. Publish rechecks state, lease token and
expiry under the Task lock, held through publisher invocation and result persistence.
Thus terminal commit either precedes publication (publication rejected), or waits
until an already-started publication finishes. No exactly-once transport claim is made.
Broker transport already has 2-second socket/connect timeouts; this lock adds bounded
I/O contention in that production publisher. Injected publishers must be bounded and
must not synchronously wait for a terminal transaction that needs the same lock.

Worker terminal/ACK guard and stage idempotency remain defense in depth, not the
primary dispatch closure mechanism. No production cleanup, deployment, Provider
call or original-canary mutation is authorized by this implementation.

## Validation

The final targeted run has 155 passed, 0 failed and 1 skipped:

- Terminal dispatch contract: 53 passed, 1 skipped.
- Formal persistence/checkpoints: 18 passed.
- READY promotion: 38 passed.
- Existing worker dispatch/reliability: 17 passed.
- Actual formal worker recovery: 29 passed.

The skip is the SQLite parameter of the PostgreSQL-only concurrent publication
row-lock test; its PostgreSQL parameter passed. Tests use real Alembic migrations
in disposable PostgreSQL schemas and unit-only SQLite schemas. Crash rollback,
new dispatcher instances after commit, late finish, stale ORM state, duplicate
worker invocation, stage resume and transport retry are covered.

The autoflush=False retry regression was independently reproduced (10 failures)
then fixed and verified (10 passes) before the full final run. Runtime SessionLocal
uses autoflush=False; a predicate queried before flushing tentative PENDING would
otherwise leave the restored worker task non-executable. Flush and closure remain
inside the same locked transaction.

Original Q2 document65/task66 was evaluated with the actual new SQL predicate in
a read-only transaction: INELIGIBLE, with original pending obligation unchanged.
Historical stale count is one successful task in that isolated clone. Production
is pre-dispatch schema 20260928_09, so its count is not applicable, not zero.

Evidence receipts are outside source at the scoped D3-P0R-P1 acceptance directory;
test fixtures and operational credentials are not included in this product commit.

The one new isolated canary completed five stages exactly once and reached
READY/task success with dispatch none, zero dispatch attempts and zero task retries.
Formal worker restart plus three dispatcher instances observed no new claim,
dispatch or stage replay across a bounded 6.02-second window. Original Q2 was not
replayed or modified. Runtime source hashes match the five-file candidate overlay.

Acceptance boundaries: FACT/PDF/ownership and official BM25+vector+RRF retrieval
source/page binding passed. The additional Narrative resolver check rejected empty
report_company metadata (NARRATIVE_QUERY_COMPANY_NOT_BOUND). That failure is retained,
not overridden by retrieval-only evidence, and remains a later delivery blocker.
No Narrative quality acceptance or inherited full D2-RC acceptance is claimed.
Production resume remains false and live Provider calls remain zero.
