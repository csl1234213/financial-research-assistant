# Financial RAG P1.4 — Metric Registry & Canonical Normalization

**P1_4_STATUS: PASS**

**Provider calls: 0; production database/indexes: untouched.**

## Scope and architecture

P1.4 adds a deterministic, registry-backed semantic layer over P1.3's
structurally verified `FinancialTableRow` observations:

```text
VERIFIED FinancialTableRow
  -> FinancialMetricRegistry / contextual alias rules
  -> normalized label + canonical metric candidate + status + evidence
  -> statement-constraint validation
  -> auditable MetricNormalization projection
```

`core/financial_metric_registry.py` is isolated from the PDF parser, retriever,
answer prompts, and providers. `MetricNormalization` retains the original row
by reference and exposes `original_label`, `normalized_label`,
`canonical_metric`, `mapping_status`, `mapping_rule`, and `mapping_evidence`.
The source `FinancialTableRow` is never mutated; P1.3's
`verification_status=VERIFIED` remains only a structural judgment. A
non-VERIFIED source row cannot receive a canonical metric.

The registry definitions include canonical name, category, compatible
statement types, Chinese and English aliases, scope rules, period semantics,
value type, aggregation semantics, and notes. Scope and period remain
observation dimensions; neither is included in metric identity. No FactLedger,
production persistence, retrieval, prompt, or answer path was modified.

## Implemented canonical metrics

- Balance sheet: `cash_and_bank_balances`, `cash_and_cash_equivalents`,
  `total_assets`, `total_liabilities`, `total_equity`, `accounts_receivable`,
  `inventory`, `fixed_assets`, `construction_in_progress`,
  `short_term_borrowings`, `long_term_borrowings`,
  `equity_attributable_to_parent`, `minority_interest`.
- Income statement: `revenue`, `total_operating_revenue`, `cost_of_revenue`,
  `operating_income` (existing project convention), `total_profit`,
  `net_income`, `attributable_net_income` (existing project convention),
  `r_and_d_expense`, `selling_expense`, `administrative_expense`,
  `finance_expense`.
- Cash flow: `operating_cash_flow`, `investing_cash_flow`,
  `financing_cash_flow`, `cash_and_cash_equivalents_net_increase`,
  `cash_and_cash_equivalents_beginning`,
  `cash_and_cash_equivalents_ending`.

Canonical metrics are extensible data definitions rather than a large
`if/elif` chain. The current registry contains explicit, finite aliases; it
does not use fuzzy string similarity or LLM classification.

## Alias and ambiguity rules

- Exact primary aliases receive `EXACT`; explicitly registered synonyms and
  safe presentation variants receive `SUPPORTED`.
- Normalization applies Unicode NFKC, strips invisible Unicode spacing,
  collapses whitespace, and standardizes full-width parentheses/colon. It
  preserves `其中:` and all attribution/scope words in the normalized label.
- A leading standard row ordinal (for example `三、`) and a narrowly defined
  profit/loss sign-convention suffix can be ignored for lookup only; the
  original and normalized labels are still retained and the mapping is marked
  `SUPPORTED`.
- A generic `现金` / `cash` label is `AMBIGUOUS`; it is not guessed as either
  bank balances or cash equivalents.
- `营业总收入` maps to `total_operating_revenue`; `营业收入` maps to
  `revenue`. A displayed `其中：营业收入` maps only through its explicit
  statement-row alias. These labels are not blindly collapsed.
- `负债合计` is `total_liabilities`, never `total_debt`. `净利润` and
  parent-attributable profit, as well as total equity and parent-attributable
  equity, use distinct canonical identifiers.
- Statement mismatch yields `UNMAPPED` with the candidate metric recorded in
  evidence. Unknown labels remain `UNMAPPED`; a recognized but generic cash
  label remains `AMBIGUOUS`.
- `short term debt`, `trade receivables`, generic capex terms, and other
  unreviewed near-synonyms are intentionally not registered as aliases.

## Guizhou Moutai 2025 P1.3 fixture audit

Replayed the actual P1.3 reconstructed rows from
`tests/fixtures/moutai-standard-statements-2025.pdf`; this fixture preserves
the original report pages 56–71. No synthetic rows were used for the
integration result.

| Statement | Verified rows | EXACT | SUPPORTED | AMBIGUOUS | UNMAPPED | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Balance sheet | 175 | 30 | 6 | 0 | 139 | 20.57% |
| Income statement | 119 | 16 | 22 | 0 | 81 | 31.93% |
| Cash flow statement | 117 | 12 | 12 | 0 | 93 | 20.51% |
| Equity statement | 184 | 0 | 0 | 0 | 184 | 0.00% |
| **Total** | **595** | **58** | **40** | **0** | **497** | **16.47%** |

Coverage is `EXACT + SUPPORTED` divided by verified rows. The low coverage is
intentional: most detailed line items, equity movement components, and
unreviewed labels stay unmapped. This is not a recall target. In the equity
statement, many financial dimensions occur in column headings rather than the
row label; this row-label-only phase does not infer a metric from those headers.

### Actual mapping samples

These are distinct label/context samples from the P1.3 fixture. Original PDF
page numbers are shown; the same row observations can recur across periods.

| # | Original label | Normalized label | Canonical metric | Status | Statement / scope | Page |
|---:|---|---|---|---|---|---:|
| 1 | 货币资金 | 货币资金 | `cash_and_bank_balances` | EXACT | BS / consolidated | 56 |
| 2 | 应收账款 | 应收账款 | `accounts_receivable` | EXACT | BS / consolidated | 57 |
| 3 | 存货 | 存货 | `inventory` | EXACT | BS / consolidated | 57 |
| 4 | 固定资产 | 固定资产 | `fixed_assets` | EXACT | BS / consolidated | 57 |
| 5 | 在建工程 | 在建工程 | `construction_in_progress` | EXACT | BS / consolidated | 57 |
| 6 | 资产总计 | 资产总计 | `total_assets` | EXACT | BS / consolidated | 57 |
| 7 | 负债合计 | 负债合计 | `total_liabilities` | EXACT | BS / consolidated | 58 |
| 8 | 归属于母公司所有者权益 | 归属于母公司所有者权益 | `equity_attributable_to_parent` | SUPPORTED | BS / consolidated | 58 |
| 9 | 少数股东权益 | 少数股东权益 | `minority_interest` | EXACT | BS / consolidated | 59 |
| 10 | 所有者权益（或股东权 益）合计 | 所有者权益(或股东权益)合计 | `total_equity` | SUPPORTED | BS / consolidated | 59 |
| 11 | 货币资金 | 货币资金 | `cash_and_bank_balances` | EXACT | BS / parent | 59 |
| 12 | 应收账款 | 应收账款 | `accounts_receivable` | EXACT | BS / parent | 59 |
| 13 | 存货 | 存货 | `inventory` | EXACT | BS / parent | 59 |
| 14 | 固定资产 | 固定资产 | `fixed_assets` | EXACT | BS / parent | 59 |
| 15 | 在建工程 | 在建工程 | `construction_in_progress` | EXACT | BS / parent | 59 |
| 16 | 资产总计 | 资产总计 | `total_assets` | EXACT | BS / parent | 60 |
| 17 | 负债合计 | 负债合计 | `total_liabilities` | EXACT | BS / parent | 60 |
| 18 | 所有者权益（或股东权 益）合计 | 所有者权益(或股东权益)合计 | `total_equity` | SUPPORTED | BS / parent | 61 |
| 19 | 一、营业总收入 | 一、营业总收入 | `total_operating_revenue` | SUPPORTED | IS / consolidated | 61 |
| 20 | 其中：营业收入 | 其中:营业收入 | `revenue` | SUPPORTED | IS / consolidated | 61 |
| 21 | 其中：营业成本 | 其中:营业成本 | `cost_of_revenue` | SUPPORTED | IS / consolidated | 61 |
| 22 | 销售费用 | 销售费用 | `selling_expense` | EXACT | IS / consolidated | 61 |
| 23 | 管理费用 | 管理费用 | `administrative_expense` | EXACT | IS / consolidated | 61 |
| 24 | 研发费用 | 研发费用 | `r_and_d_expense` | EXACT | IS / consolidated | 61 |
| 25 | 财务费用 | 财务费用 | `finance_expense` | EXACT | IS / consolidated | 61 |
| 26 | 三、营业利润（亏损以“－”号填列） | 三、营业利润(亏损以“-”号填列) | `operating_income` | SUPPORTED | IS / consolidated | 62 |
| 27 | 四、利润总额（亏损总额以“－”号 填列） | 四、利润总额(亏损总额以“-”号填列) | `total_profit` | SUPPORTED | IS / consolidated | 62 |
| 28 | 五、净利润（净亏损以“－”号填列） | 五、净利润(净亏损以“-”号填列) | `net_income` | SUPPORTED | IS / consolidated | 62 |
| 29 | 1.归属于母公司股东的净利润 （净亏损以“-”号填列） | 1.归属于母公司股东的净利润(净亏损以“-”号填列) | `attributable_net_income` | SUPPORTED | IS / consolidated | 62 |
| 30 | 一、营业收入 | 一、营业收入 | `revenue` | SUPPORTED | IS / parent | 63 |
| 31 | 销售费用 | 销售费用 | `selling_expense` | EXACT | IS / parent | 63 |
| 32 | 管理费用 | 管理费用 | `administrative_expense` | EXACT | IS / parent | 63 |
| 33 | 研发费用 | 研发费用 | `r_and_d_expense` | EXACT | IS / parent | 63 |
| 34 | 财务费用 | 财务费用 | `finance_expense` | EXACT | IS / parent | 63 |
| 35 | 二、营业利润（亏损以“－”号填列） | 二、营业利润(亏损以“-”号填列) | `operating_income` | SUPPORTED | IS / parent | 63 |
| 36 | 三、利润总额（亏损总额以“－”号 填列） | 三、利润总额(亏损总额以“-”号填列) | `total_profit` | SUPPORTED | IS / parent | 63 |
| 37 | 四、净利润（净亏损以“－”号填列） | 四、净利润(净亏损以“-”号填列) | `net_income` | SUPPORTED | IS / parent | 63 |
| 38 | 经营活动产生的现金流 量净额 | 经营活动产生的现金流量净额 | `operating_cash_flow` | EXACT | CF / consolidated | 65 |
| 39 | 投资活动产生的现金流 量净额 | 投资活动产生的现金流量净额 | `investing_cash_flow` | EXACT | CF / consolidated | 65 |
| 40 | 筹资活动产生的现金流 量净额 | 筹资活动产生的现金流量净额 | `financing_cash_flow` | EXACT | CF / consolidated | 66 |

Additional audited cash-flow samples: `五、现金及现金等价物净增加额` →
`cash_and_cash_equivalents_net_increase` (SUPPORTED),
`加：期初现金及现金等价物余 额` →
`cash_and_cash_equivalents_beginning` (SUPPORTED), and
`六、期末现金及现金等价物余额` →
`cash_and_cash_equivalents_ending` (SUPPORTED). Parent-company counterparts
map to the same canonical metrics while retaining `scope=parent`.

### Required semantic boundary checks

| Source label | Result | Must not collapse into |
|---|---|---|
| 资产总计 | `total_assets` | — |
| 负债合计 | `total_liabilities` | `total_debt` |
| 货币资金 | `cash_and_bank_balances` | `cash_and_cash_equivalents` |
| 固定资产 | `fixed_assets` | `capital_expenditure` |
| 在建工程 | `construction_in_progress` | `capital_expenditure` |
| 净利润 | `net_income` | `attributable_net_income` |
| 归属于母公司股东的净利润 | `attributable_net_income` | `net_income` |
| 所有者权益合计 | `total_equity` | `equity_attributable_to_parent` |
| 归属于母公司所有者权益合计 | `equity_attributable_to_parent` | `total_equity` |
| 经营活动产生的现金流量净额 | `operating_cash_flow` | `free_cash_flow` |
| 营业总收入 | `total_operating_revenue` | `revenue` |
| 营业收入 | `revenue` | `cash_received_from_sales` |

The fixture produced four multi-label collision candidates: row numbering
variants for `operating_income`, `net_income`, and `total_profit`, plus the
explicit `营业收入` / `其中：营业收入` report-format variants. All are
expected same-metric forms under their declared aliases. No incompatible
statement/metric collision was observed. `FALSE_MAPPING_COUNT=0` across the 98
mapped observations (49 distinct label/statement/scope contexts); the
unmapped population was not counted as false mappings.

## Tests and gates

- Unit cases cover exact/supported aliases, English aliases, Unicode/full-width
  formatting, annotation and accounting-note variants, ambiguous cash,
  statement mismatch, unverified source rows, negative semantic boundaries,
  collision boundaries, and independent scope/period identity.
- Integration uses all 595 actual P1.3 `VERIFIED` rows and verifies source rows
  remain unchanged.
- Targeted tests (registry + P1.3 reconstruction/schema): **43 passed**.
- Full offline backend suite with `ALLOW_REAL_PROVIDER=false`:
  **2766 passed, 23 skipped**, 1 existing Starlette/httpx deprecation warning.
- Full repository Ruff: **PASS**.
- `git diff --check`: **PASS** (Git emitted only line-ending normalization
  warnings for unrelated dirty files).
- No provider was enabled or called; no production database, Chroma index,
  prompt, retrieval Top-K, or persisted fact was changed.

## Known limitations

- This is a deterministic first ontology slice, not a complete Chinese,
  US-GAAP, or IFRS taxonomy. Unknown lines remain unmapped.
- Current matching is row-label and statement aware. It does not infer a
  metric from equity-statement column headings or use semantic embeddings.
- Context-dependent accounting concepts beyond the explicit rules remain
  unmapped until source-specific reviewed aliases and tests are added.
- This phase does not attach mappings to production chunks or build final
  `FinancialFact` records; that is P1.5 scope.

## Next step

After the complete offline suite, Ruff, diff review, and isolated commit pass,
P1.5 can combine structurally VERIFIED observations with canonical metrics in
a separate FactLedger ingestion/retrieval design. No production rebuild is
implied by this report.
