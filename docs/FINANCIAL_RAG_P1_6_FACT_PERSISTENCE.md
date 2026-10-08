# Financial RAG P1.6 — Financial Fact Persistence

**Status: implementation and offline verification PASS; isolated commit is blocked by a pre-existing migration dependency.**

## Baseline and safety

- HEAD at start: `4b350cf feat: build canonical financial fact layer`.
- The worktree was already broadly modified before P1.6. `core/fact_ledger.py` alone had 559 additions and 35 deletions relative to HEAD. These edits were left untouched; P1.6 does not change that file.
- `migrations/versions/20260729_08_local_ollama_provider.py` was an untracked pre-existing file and is the parent of the P1.6 migration. It was not staged or altered. Committing P1.6 without that parent would produce a revision that cannot be resolved from the current HEAD, so no commit was created.
- No production database migration or ingestion was run. The Moutai shadow ingestion used temporary SQLite databases created for the tests. Chroma, retrieval, router, prompt, and answer generation were not changed. No Provider was called.

## Existing database architecture

The project uses the existing SQLAlchemy declarative `storage.database.Base`, `SessionLocal`, and Alembic migrations. `Document` is tenant-scoped and already stores `content_sha256`; uploads deduplicate on `(tenant_id, content_sha256)`. The fact repository receives the existing SQLAlchemy `Session` and an explicit `tenant_id`; it does not create another connection or ORM.

The document's SHA-256 is stored as `document_version`. A revised PDF has a distinct content hash and document row; facts are scoped to both the tenant and relational document ID. The repository checks that the caller's document belongs to its tenant and refuses documents without a valid SHA-256. It never chooses an active/latest document version implicitly.

## Schema and repository

Added three Alembic-managed tables:

- `financial_facts`: canonical values, original and normalized labels, period/scope/company dimensions, exact P1.5 identity, source text/locator/page/table/row provenance, content hash version, tenant/document IDs, and ingestion run ID.
- `financial_fact_ingestion_runs`: row/fact counters, lifecycle status, timestamps, and error summary.
- `financial_fact_conflicts`: the stable identity, old/new values, and provenance snapshots for rejected conflicting values.

`SQLFinancialFactRepository` implements the same `FinancialFactRepositoryProtocol` as the in-memory adapter. It offers batch persistence, exact filters, document/metric lookup, latest lookup with ambiguity rejection, unique lookup with `FOUND / NOT_FOUND / AMBIGUOUS / CONFLICT`, conflict inspection, and document counts. Results are deterministically ordered; multi-match queries return all matches rather than selecting the first.

### Decimal storage

PostgreSQL and other production SQL dialects use `NUMERIC(38,12)`. SQLite's `NUMERIC` affinity was experimentally shown to convert `303834844021.44` into `303834844021.440002441406`; therefore the local/test SQLite dialect stores canonical decimal text in `VARCHAR(80)` and reconstructs `Decimal` exactly. The adapter rejects values outside the selected precision/scale instead of silently rounding them. The SQLite migration path and PostgreSQL dialect type mapping were tested; no live PostgreSQL instance was available for this run.

### Idempotency, versions, transactions, and conflicts

- The repository persists the existing P1.5 `fact_id` and exact `structured_identity`; it does not invent a second identity. It also checks that the persisted dimensions agree with the identity tuple.
- `(document_id, fact_id)` is unique. Same identity + same normalized Decimal is unchanged; same identity + different value fails the document-level fact transaction and writes a conflict audit. Existing facts are never updated to the incoming value.
- A `RUNNING` run record is committed first for observability. The facts and successful run counters then commit in one transaction. On insertion failure, all facts roll back and the run is marked `FAILED`; no partial document fact set remains.
- Document content hash and relational document ID isolate revisions. Facts from separate uploaded versions coexist; repository-level “latest” does not select between competing document versions.

## Guizhou Moutai shadow ingestion

Source: checked-in P1.3 fixture `tests/fixtures/moutai-standard-statements-2025.pdf`; 595 verified rows yielded 98 eligible P1.5 facts (58 EXACT, 40 SUPPORTED; the remaining 497 verified rows are unmapped/rejected for fact persistence).

| Measure | Result |
|---|---:|
| Facts generated / eligible | 98 |
| First-run persisted / inserted | 98 / 98 |
| Second-run persisted | 98 |
| Second-run inserted / unchanged | 0 / 98 |
| Final row count for version | 98 |
| Decimal / value loss | 0 |
| Scope / period / unit / provenance loss | 0 / 0 / 0 / 0 |
| Silent overwrite / missed conflict | 0 / 0 |
| Failure after insert 47 | PASS; zero facts remained, run recorded FAILED |
| Accounting equation audit after DB read-back | 4/4 PASS |
| Cash-flow audit after DB read-back | 4/4 PASS |

The following 20 observations were read back from the migrated temporary database after persistence. Amounts are exact `CNY_YUAN`; the source locators are retained unchanged.

| # | Original label | Canonical metric | Value | Period | Scope | Page / source row |
|---:|---|---|---:|---|---|---|
| 1 | 应收账款 | `accounts_receivable` | 2,609,048.49 | 2025-12-31 | Consolidated | p.57 / row 3 |
| 2 | 应收账款 | `accounts_receivable` | 11,895,319,134.75 | 2025-12-31 | Parent | p.59 / row 7 |
| 3 | 应收账款 | `accounts_receivable` | 11,800,123,743.35 | 2024-12-31 | Parent | p.59 / row 7 |
| 4 | 应收账款 | `accounts_receivable` | 18,974,192.75 | 2024-12-31 | Consolidated | p.57 / row 3 |
| 5 | 管理费用 | `administrative_expense` | 8,320,061,659.66 | FY2025 | Consolidated | p.61 / row 18 |
| 6 | 管理费用 | `administrative_expense` | 7,677,483,750.64 | FY2025 | Parent | p.63 / row 6 |
| 7 | 管理费用 | `administrative_expense` | 9,315,650,060.38 | FY2024 | Consolidated | p.61 / row 18 |
| 8 | 管理费用 | `administrative_expense` | 8,427,791,578.73 | FY2024 | Parent | p.63 / row 6 |
| 9 | 归属于母公司股东的净利润 | `attributable_net_income` | 82,320,067,101.68 | FY2025 | Consolidated | p.62 / row 14 |
| 10 | 归属于母公司股东的净利润 | `attributable_net_income` | 86,228,146,421.62 | FY2024 | Consolidated | p.62 / row 14 |
| 11 | 货币资金 | `cash_and_bank_balances` | 77,252,079,198.82 | 2024-12-31 | Parent | p.59 / row 3 |
| 12 | 货币资金 | `cash_and_bank_balances` | 59,295,822,956.89 | 2024-12-31 | Consolidated | p.56 / row 3 |
| 13 | 货币资金 | `cash_and_bank_balances` | 85,687,080,245.45 | 2025-12-31 | Parent | p.59 / row 3 |
| 14 | 货币资金 | `cash_and_bank_balances` | 51,690,610,946.50 | 2025-12-31 | Consolidated | p.56 / row 3 |
| 15 | 期初现金及现金等价物余额 | `cash_and_cash_equivalents_beginning` | 150,360,188,952.47 | FY2024 | Consolidated | p.66 / row 14 |
| 16 | 期初现金及现金等价物余额 | `cash_and_cash_equivalents_beginning` | 71,147,917,165.03 | FY2024 | Parent | p.67 / row 24 |
| 17 | 期初现金及现金等价物余额 | `cash_and_cash_equivalents_beginning` | 169,970,089,257.83 | FY2025 | Consolidated | p.66 / row 14 |
| 18 | 期初现金及现金等价物余额 | `cash_and_cash_equivalents_beginning` | 76,517,140,680.50 | FY2025 | Parent | p.67 / row 24 |
| 19 | 期末现金及现金等价物余额 | `cash_and_cash_equivalents_ending` | 169,970,089,257.83 | FY2024 | Consolidated | p.66 / row 15 |
| 20 | 期末现金及现金等价物余额 | `cash_and_cash_equivalents_ending` | 126,425,609,447.72 | FY2025 | Consolidated | p.66 / row 15 |

## Verification

- P1.6 persistence tests after adding exact lookup statuses, ingestion counters, identity checks, and migration-backed shadow setup: 7 passed.
- P1.5 financial-fact and migration regressions: 17 passed in the focused run.
- Final full offline suite after all code changes: 2782 passed, 23 skipped, 0 failed (409.53 seconds); `ALLOW_REAL_PROVIDER=false` for the run.
- Ruff full-tree check: PASS.
- `git diff --check`: PASS (Git emitted only existing line-ending normalization warnings for unrelated modified files).

## Known limitations and next step

- Persistence is deliberately not connected to upload workers, production query routing, or any production database; P1.7 / deployment work remains separate.
- An actual PostgreSQL server was not configured, so the database integration run used migrated SQLite and verified the PostgreSQL type dialect mapping rather than live PostgreSQL I/O.
- The existing working tree contains many unrelated tracked modifications and untracked files. In particular, the P1.6 migration depends on the untracked pre-existing revision `20260729_08`. A standalone P1.6 commit is unsafe until that parent migration is explicitly resolved. Do not stage it implicitly.
- Next: run the final complete offline suite, then decide whether to commit the prerequisite migration separately or authorize including that dependency in the P1.6 commit.
