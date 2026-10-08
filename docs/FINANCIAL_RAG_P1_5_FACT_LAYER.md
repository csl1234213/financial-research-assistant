# Financial RAG P1.5 — Canonical Financial Fact Layer

## Status

**P1.5: PASS (offline structured-fact layer).** No Provider was called, no production database was written, and Chroma was not rebuilt or reindexed. This phase creates an in-memory/test repository and deterministic retrieval API only.

## Design review and reuse boundary

- Reused the existing `core.fact_ledger.FinancialFact` and `FactLedger`; added optional structured fields so narrative facts and existing constructors remain backward compatible.
- The legacy evidence-window extractor remains suitable for narrative/verified textual facts, but it cannot recover statement, scope, row mapping, fiscal semantics, or table provenance from text alone. It must not manufacture structured facts from that path.
- `FactLedger.from_evidence()` now handles typed `financial_table_rows_json` only through the P1.5 eligibility gate. `unverified_table` is still rejected before parsing. Already-created structured facts can enter via `FactLedger.from_financial_facts()`.
- Added `core.financial_facts` for the gate, factory, in-memory repository, retrieval policy, period/unit normalization, and non-mutating QA audits. It does not own a second persistent fact model.

## Schema and eligibility

`FinancialFact` retains its existing ledger fields and adds: company ID/name, accounting standard, original/normalized labels, statement type, consolidated/parent scope, raw source value/unit, mapping status/rule, row verification status, source kind, source creation type, table/row locator, source text, statement period, and a structured identity. `provenance` exports those fields together with page and source locator.

The gate requires a VERIFIED row, EXACT or SUPPORTED registry mapping, non-null canonical metric, compatible statement, classifiable explicit period, Decimal value, supported unit and currency, known scope, statement type, document/company identity, positive source page, source locator, and source text. Unknown, ambiguous, unmapped, incomplete, or inconsistent rows fail closed. A VERIFIED structural row is not thereby considered semantically mapped.

EXACT and SUPPORTED are both admitted but preserved separately. The current P1.4 metric naming convention uses `attributable_net_income` for the mapped “归属于母公司股东的净利润”; this phase does not rename it to `net_income_attributable_to_parent`.

## Identity, periods, scope, value and standard

- Deterministic identity includes document, company, accounting standard, canonical metric, statement, scope, period type and bounds, currency, and canonical unit. Value is excluded from identity so conflicting source amounts cannot evade detection.
- Identical identity + identical Decimal value is a duplicate; its alternate source records remain available from the in-memory repository. Identical identity + different values is a `FACT_CONFLICT`; every candidate is audited and excluded from normal retrieval. No silent winner is selected.
- `INSTANT` facts carry a period-end date (and beginning-balance dates where supported); `DURATION` facts carry start and end dates. Annual bounds are assigned only when fiscal-calendar metadata and its source are supplied. The regression context records the Moutai report’s accounting-policy and fiscal-calendar source pages; a year label alone is insufficient to invent duration bounds.
- `CONSOLIDATED` and `PARENT_COMPANY` are separate observations, not part of canonical metric identity. Both are stored. Retrieval defaults to an explicit `CONSOLIDATED` policy and reports the selection reason; callers can request parent scope.
- Monetary values use `Decimal` and are normalized to currency base units. Source raw value and source unit remain intact. Tested Chinese units include 元、千元、万元、百万元、亿元; CNY facts use `CNY_YUAN`.
- Accounting standard is `CAS`, `US_GAAP`, `IFRS`, or `UNKNOWN`. A non-UNKNOWN standard requires explicit source evidence; language is never used as a proxy. Standard is part of fact identity and can be specified during retrieval, preventing cross-GAAP collisions.

## FactLedger and retrieval API

`FinancialFactRepository` supports `upsert`, deterministic `find`, `find_latest`, and lookup by company, metric, fiscal year, scope, document, and accounting standard. `latest=True` is based on stored fiscal-year metadata, never the current date. `StructuredFinancialFactRetrieval.get_financial_fact(...)` applies the preferred-scope policy and returns facts with value, currency, unit, period, statement, page, original label, and citation provenance. If standards are unspecified and multiple standards are present, it returns the candidates rather than guessing.

`FactLedger.lookup()` puts `FINANCIAL_STATEMENT` facts before narrative facts. This is only a priority ordering; it does not weaken the existing unverified-table boundary. Exact structured numeric retrieval is repository-backed and does not use embeddings.

## Real P1.3/P1.4 Moutai regression

The checked-in P1.3 reconstruction fixture contains 595 rows, all `VERIFIED`. P1.4 normalization maps 98: 58 EXACT and 40 SUPPORTED. The other 497 verified rows are UNMAPPED; 0 are AMBIGUOUS. All 98 mapped rows satisfy the structured-fact gate and are retrievable with full source provenance.

| Statement | Verified rows | Mapped rows | Facts created |
|---|---:|---:|---:|
| Balance sheet | 175 | 36 | 36 |
| Income statement | 119 | 38 | 38 |
| Cash flow statement | 117 | 24 | 24 |
| Equity statement | 184 | 0 | 0 |
| Total in checked-in fixture | 595 | 98 | 98 |

The excerpt fixture has no PARTIAL rows, so `REJECTED_PARTIAL` is **not applicable / 0 present in this fixture**, not evidence that the separate 19 partial candidates noted in the full P1.3 run were ingested or audited here. A synthetic PARTIAL case verifies fail-closed rejection. `REJECTED_UNMAPPED=497`; ambiguous mapping count is 0.

### 20 real fact samples

All values below were read from P1.3 reconstructed rows; CNY values are exact Decimal yuan. Period labels preserve the source comparative column.

| Canonical metric | Original label | Value | Period / type | Scope | Statement | Page | Mapping |
|---|---|---:|---|---|---|---:|---|
| cash_and_bank_balances | 货币资金 | 51,690,610,946.50 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 56 | EXACT |
| cash_and_bank_balances | 货币资金 | 59,295,822,956.89 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 56 | EXACT |
| accounts_receivable | 应收账款 | 2,609,048.49 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| accounts_receivable | 应收账款 | 18,974,192.75 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| inventory | 存货 | 61,427,421,796.18 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| inventory | 存货 | 54,343,285,157.47 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| fixed_assets | 固定资产 | 22,488,122,304.35 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| fixed_assets | 固定资产 | 21,871,446,747.14 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| construction_in_progress | 在建工程 | 2,471,886,030.58 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| construction_in_progress | 在建工程 | 2,149,619,937.05 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| total_assets | 资产总计 | 303,834,844,021.44 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| total_assets | 资产总计 | 298,944,579,918.70 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 57 | EXACT |
| total_liabilities | 负债合计 | 49,875,590,112.37 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 58 | EXACT |
| total_liabilities | 负债合计 | 56,933,264,798.10 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 58 | EXACT |
| equity_attributable_to_parent | 归属于母公司所有者权益 | 244,637,811,032.18 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 58 | SUPPORTED |
| equity_attributable_to_parent | 归属于母公司所有者权益 | 233,105,984,399.47 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 58 | SUPPORTED |
| minority_interest | 少数股东权益 | 9,321,442,876.89 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 59 | EXACT |
| minority_interest | 少数股东权益 | 8,905,330,721.13 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 59 | EXACT |
| total_equity | 所有者权益（或股东权益）合计 | 253,959,253,909.07 | 2025-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 59 | SUPPORTED |
| total_equity | 所有者权益（或股东权益）合计 | 242,011,315,120.60 | 2024-12-31 / INSTANT | CONSOLIDATED | balance_sheet | 59 | SUPPORTED |

### Required metric checks, consolidated FY2025

| Canonical metric | Reported value | Page | Result |
|---|---:|---:|---|
| cash_and_bank_balances | 51,690,610,946.50 CNY | 56 | FACT |
| total_assets | 303,834,844,021.44 CNY | 57 | FACT |
| total_liabilities | 49,875,590,112.37 CNY | 58 | FACT |
| total_equity | 253,959,253,909.07 CNY | 59 | FACT |
| fixed_assets | 22,488,122,304.35 CNY | 57 | FACT |
| construction_in_progress | 2,471,886,030.58 CNY | 57 | FACT |
| revenue | 168,838,102,514.79 CNY | 61 | FACT |
| net_income | 85,310,324,833.67 CNY | 62 | FACT |
| attributable_net_income | 82,320,067,101.68 CNY | 62 | FACT; existing P1.4 canonical name |
| operating_cash_flow | 61,522,204,989.35 CNY | 65 | FACT |

`货币资金` remains `cash_and_bank_balances`, never `cash_and_cash_equivalents`; `负债合计` remains `total_liabilities`, never `total_debt`; `净利润` and parent-attributable net income remain separate; total equity and parent-attributable equity remain separate. Fixed assets and construction in progress are not CapEx. `cash_and_cash_equivalents_ending` remains a distinct reported cash-flow metric and is not conflated with balance-sheet cash.

## Conflicts and sanity audits

| Check | Result |
|---|---:|
| FACT_CONFLICTS | 0 |
| DUPLICATES | 0 |
| SILENT_CONFLICT_COUNT | 0 |
| SCOPE_LOSS_COUNT | 0 |
| PERIOD_LOSS_COUNT | 0 |
| UNIT_LOSS_COUNT | 0 |
| PROVENANCE_LOSS_COUNT | 0 |
| Accounting equation | 4/4 PASS (two years × two scopes; difference 0.00 CNY) |
| Cash-flow balance | 4/4 PASS (two years × two scopes; difference 0.00 CNY) |

The cash-flow check uses only the report’s beginning cash + reported net increase = ending cash values; it does not create or persist a derived fact. Neither audit edits a source amount.

## Verification

- Targeted financial-fact, P1.3 reconstruction, P1.4 registry, typed-row, and legacy FactLedger tests: **106 passed**.
- Full offline backend suite, `ALLOW_REAL_PROVIDER=false`: **2775 passed, 23 skipped, 0 failed**.
- Ruff, full repository: **PASS**.
- `git diff --check`: **PASS**. Git printed existing working-copy line-ending notices for unrelated dirty files.
- Provider calls / API cost: **0 / $0**.

## Files in this P1.5 change

- `core/financial_facts.py`
- `core/fact_ledger.py` (only the P1.5 FactLedger schema/ingestion/structured-first hunks are included in the commit; the rest is pre-existing working-tree work)
- `tests/test_financial_facts.py`
- `docs/FINANCIAL_RAG_P1_5_FACT_LAYER.md`

## Known limitations and next step

- The real regression fixture is the 595-row reconstructed financial-statement excerpt. The full-report 19 PARTIAL candidates are not part of that checked-in fixture; they remain ineligible and were not claimed as covered by the measured fixture count.
- The FactLedger typed-row bridge needs trusted document-level accounting-standard and fiscal-calendar metadata to emit duration facts. Without it, those facts are rejected rather than having dates inferred from language or the current date.
- Storage remains in-memory/test-only. No migrations, production DB writes, Chroma rebuild, answer-generator integration, or derived facts are included.
- P1.6 can define a separately reviewed persistence boundary and ingestion lifecycle after this offline layer is accepted.

## Commit

`feat: build canonical financial fact layer`
