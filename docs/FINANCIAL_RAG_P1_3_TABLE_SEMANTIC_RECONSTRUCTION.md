# P1.3 Financial Table Semantic Reconstruction

## Status

**P1_3_STATUS: PASS (standard statements, audited sample)**

This phase reconstructs standard financial statement rows from the PDF parser's
native text regions, table cells, and coordinates. It does not read Chroma
chunks as source structure, call an LLM/provider, rebuild Chroma, reindex a
production collection, or write production data.

Source used for the full-document audit:
`<external-qualified-report.pdf>`
(143 pages, 1,082,847 bytes). A 16-page regression fixture preserves original
page numbers 56–71 at `tests/fixtures/moutai-standard-statements-2025.pdf`.

## Architecture

`PDF → ParsedPage(text regions + native table candidates/cell bboxes) → statement/context detection → header/column binding → atomic FinancialTableRow → conservative verification`

The parser IR preserves page-level text region bboxes, native table rows,
per-cell bboxes, table bboxes, and original page/table/row/column coordinates.
The reconstructor uses that IR only; it has no Chroma or provider dependency.
Atomic rows carry one value per period, `Decimal` values, raw source values,
unit, currency, scope, statement type, note reference, column role, page,
cell/region bbox, and row/column locator. `canonical_metric` remains optional:
P1.3 verifies structure, not metric normalization.

## Detection and context results

| Statement | Scope | Pages | Detected rows | Verified |
|---|---|---:|---:|---:|
| Balance sheet | Consolidated | 56–59 | 100 | 100 |
| Balance sheet | Parent company | 59–61 | 75 | 75 |
| Income statement | Consolidated | 61–63 | 77 | 77 |
| Income statement | Parent company | 63 | 42 | 42 |
| Cash flow statement | Consolidated | 64–66 | 68 | 68 |
| Cash flow statement | Parent company | 66–67 | 49 | 49 |
| Equity statement | Consolidated | 68–69 | 115 | 115 |
| Equity statement | Parent company | 70–71 | 69 | 69 |

The full-document pass produced **10 contexts and 614 atomic candidate rows**:
595 VERIFIED rows across the eight standard statement contexts and 19 PARTIAL
rows in two appendix-like balance-sheet-shaped tables whose scope could not be
proven. The two unknown-scope contexts cover pages 87–92 and 124–133. No
candidate was promoted to VERIFIED solely because its label looked financial.
There were no UNVERIFIED rows emitted by this reconstructor; rows without a
proven numeric binding are omitted rather than represented as facts.

Parent-company statements contain 235 VERIFIED rows (75 balance sheet, 42
income statement, 49 cash flow, 69 equity). Consolidated statements contain
360 VERIFIED rows (100, 77, 68, 115 respectively).

## Binding and verification rules

- Statement title detection combines known statement-title patterns with page
  text regions; scope is only `consolidated`, `parent`, or `unknown` when the
  title explicitly supports it. `unknown` cannot be VERIFIED.
- Multi-row headers are flattened by cell geometry: leaf headers inherit only
  parent headers whose bboxes cover the data-column center. This supports the
  merged equity-statement headings without relying on table column ordinals.
- Explicit reporting dates map directly to date periods. FY headers map to
  `FYyyyy`. Closing/opening labels bind only when a report date is explicit;
  opening period maps to the preceding year. Unbound or ambiguous columns fail
  closed.
- Currency and unit are separate fields and must be explicitly sourced from
  nearby report text. No default CNY or yuan is applied. Verified rows from the
  Moutai statements use `currency=CNY`, `unit=元`.
- Note columns are detected separately and retained in `note_reference`; they
  are excluded from numeric value binding.
- Numeric parsing uses `Decimal`, handles thousands separators, leading minus,
  accounting parentheses, and dash/blank as no value. Percent rows do not get
  silently treated as currency amounts.
- Continuation requires an adjacent page and compatible table geometry; old
  period columns are mapped by x-position when a continuation grid shifts
  column indices. Repeated headers are discarded as headers. A new statement,
  appendix/policy/audit boundary, missing-table page, or incompatible grid
  prevents old columns from leaking into unrelated rows.
- VERIFIED requires source-backed dimensions, a parsed number, explicit period,
  recognized statement and scope, unit/currency, source page and text, and a
  proven row-to-column binding. Canonical metric registration is not required.

## 20-row source ground-truth audit

The following expected values were transcribed from the PDF's native table
cells before comparison with parser output. Each row matched exactly on label,
period, raw value, Decimal-normalized value, unit, currency, scope, and page;
each also retained a source cell/region bbox and a source locator.

| # | Statement | Scope | Row label | Period | Raw value = normalized Decimal | Unit | Currency | Page | Status |
|---:|---|---|---|---|---:|---|---|---:|---|
| 1 | Balance sheet | Consolidated | 货币资金 | 2025-12-31 | 51,690,610,946.50 | 元 | CNY | 56 | VERIFIED |
| 2 | Balance sheet | Consolidated | 货币资金 | 2024-12-31 | 59,295,822,956.89 | 元 | CNY | 56 | VERIFIED |
| 3 | Balance sheet | Consolidated | 应收账款 | 2025-12-31 | 2,609,048.49 | 元 | CNY | 57 | VERIFIED |
| 4 | Balance sheet | Consolidated | 存货 | 2025-12-31 | 61,427,421,796.18 | 元 | CNY | 57 | VERIFIED |
| 5 | Balance sheet | Consolidated | 固定资产 | 2025-12-31 | 22,488,122,304.35 | 元 | CNY | 57 | VERIFIED |
| 6 | Balance sheet | Consolidated | 在建工程 | 2025-12-31 | 2,471,886,030.58 | 元 | CNY | 57 | VERIFIED |
| 7 | Balance sheet | Consolidated | 资产总计 | 2025-12-31 | 303,834,844,021.44 | 元 | CNY | 57 | VERIFIED |
| 8 | Balance sheet | Consolidated | 负债合计 | 2025-12-31 | 49,875,590,112.37 | 元 | CNY | 58 | VERIFIED |
| 9 | Balance sheet | Parent | 货币资金 | 2025-12-31 | 85,687,080,245.45 | 元 | CNY | 59 | VERIFIED |
| 10 | Balance sheet | Parent | 资产总计 | 2025-12-31 | 195,350,142,529.19 | 元 | CNY | 60 | VERIFIED |
| 11 | Income statement | Consolidated | 其中：营业收入 | FY2025 | 168,838,102,514.79 | 元 | CNY | 61 | VERIFIED |
| 12 | Income statement | Consolidated | 其中：营业成本 | FY2025 | 14,892,277,570.91 | 元 | CNY | 61 | VERIFIED |
| 13 | Income statement | Consolidated | 三、营业利润 | FY2025 | 114,808,950,164.24 | 元 | CNY | 62 | VERIFIED |
| 14 | Income statement | Consolidated | 五、净利润 | FY2025 | 85,310,324,833.67 | 元 | CNY | 62 | VERIFIED |
| 15 | Income statement | Consolidated | 归属于母公司股东的净利润 | FY2025 | 82,320,067,101.68 | 元 | CNY | 62 | VERIFIED |
| 16 | Cash flow statement | Consolidated | 经营活动产生的现金流量净额 | FY2025 | 61,522,204,989.35 | 元 | CNY | 65 | VERIFIED |
| 17 | Cash flow statement | Consolidated | 投资活动产生的现金流量净额 | FY2025 | -31,641,898,948.89 | 元 | CNY | 65 | VERIFIED |
| 18 | Cash flow statement | Consolidated | 筹资活动产生的现金流量净额 | FY2025 | -73,427,081,208.87 | 元 | CNY | 66 | VERIFIED |
| 19 | Cash flow statement | Consolidated | 现金及现金等价物净增加额 | FY2025 | -43,544,479,810.11 | 元 | CNY | 66 | VERIFIED |
| 20 | Cash flow statement | Consolidated | 期末现金及现金等价物余额 | FY2025 | 126,425,609,447.72 | 元 | CNY | 66 | VERIFIED |

| Audited error class | Errors in the 20-row ground-truth sample |
|---|---:|
| Column binding | 0 |
| Period binding | 0 |
| Unit | 0 |
| Scope | 0 |
| Numeric/raw value | 0 |

The 20-row sample is an exact, manually transcribed regression audit, not a
claim that every one of the 595 rows was independently transcribed by a human.
The wider output was checked for structural invariants: all 595 VERIFIED rows
have unit, currency, page, source region, and source locator; appendix-shaped
rows with unknown scope remain PARTIAL.

## Regression and quality gates

- Targeted parser/schema/document-loader/task tests: **87 passed**.
- Full offline backend suite with `ALLOW_REAL_PROVIDER=false`: **2737 passed,
  23 skipped**, 1 existing Starlette/httpx deprecation warning.
- Full Ruff: **PASS**.
- `git diff --check`: **PASS** (Git printed line-ending normalization warnings
  for unrelated pre-existing dirty files; no whitespace errors).
- No DeepSeek, local model, or other provider calls were made.
- Production Chroma, indexes, and database were not touched.

## Known limitations

- Reconstruction is intentionally limited to standard statements and nearby
  parser-native table grids. It does not claim complete reconstruction of
  financial note schedules or appendix tables.
- The two appendix-like tables remain PARTIAL because scope is not explicit;
  their rows are not eligible as verified facts.
- Values in the 20-row ground-truth audit are manually cross-checked; the
  remaining VERIFIED candidates are structurally validated but not individually
  hand-transcribed in this phase.
- Parser outputs are not yet persisted to/reindexed in production Chroma by
  design. A future phase must explicitly authorize and gate any reindex.
- This proves structural extraction quality, not query accuracy or answer
  quality.

## Next step

P1.3 is ready for review/commit. Later phases may consume only VERIFIED rows
and separately handle metric normalization or production reindexing. Do not
infer that this change has altered existing production indexes.
