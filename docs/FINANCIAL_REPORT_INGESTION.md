# Financial report ingestion: format and evidence integrity

## Why format-aware ingestion matters

Flattening a spreadsheet or a PDF table into an unlabelled string can detach a
financial value from its row label, period, unit, or currency. That makes a
retriever appear to find the right number while the citation no longer proves
what the number means. Ingestion therefore preserves source structure and
location, and marks uncertain metadata as unknown instead of guessing.

## Upstream design references

- [Docling](https://github.com/docling-project/docling) models multiple input
  formats through a structured document representation with layout, reading
  order, tables, and exportable provenance. The representation distinguishes
  table items from prose and retains source/layout provenance
  ([document model](https://github.com/docling-project/docling/blob/main/docs/concepts/docling_document.md));
  Docling also lists XBRL financial-report support. Its
  [table export example](https://github.com/docling-project/docling/blob/main/docs/examples/export_tables.py)
  illustrates keeping table data structured instead of treating it as prose.
- [PaddleOCR PP-StructureV3](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.en.md)
  combines layout detection, OCR and table recognition, and can expose detected
  cell boxes, HTML table structure, OCR text and recognition scores. It is a
  candidate fallback for scanned or complex PDFs, not a correctness oracle.
- [MinerU's structured-content schema](https://github.com/opendatalab/MinerU/blob/master/docs/next/middle-json/structured-content-schema.md)
  makes source locators, page information, and document identity explicit.
- [Marker](https://github.com/datalab-to/marker) supports several office and
  document formats; its optional LLM-assisted processing is deliberately not
  enabled here because this import path must be provider-free and deterministic.
- [RAG-Anything's parser failure checklist](https://github.com/HKUDS/RAG-Anything/blob/main/docs/multimodal_rag_failure_modes.md)
  recommends inspecting the parser's intermediate output when OCR/layout mixes
  columns, rather than trusting the final answer alone.
- [RAGFlow's chunker](https://github.com/infiniflow/ragflow/blob/683a86add702e01a4163c283e9ae56d84f156703/internal/ingestion/component/chunker/general.go)
  selects a strategy from the parser's canonical file type, which is a useful
  pattern for format-specific ingestion. Its [spreadsheet row-loss issue](https://github.com/infiniflow/ragflow/issues/19185)
  and [silent cell-loss issue](https://github.com/infiniflow/ragflow/issues/18459)
  also show why parse completion alone is not an integrity check; this project
  keeps regressions for sparse used ranges and preserves ambiguous rows as
  non-evidence instead of silently promoting them.
- RAGFlow's [CSV parser](https://github.com/infiniflow/ragflow/blob/45637635df95140b0a0dc0d3693dc4b07b10595e/internal/parser/parser/csv_parser.go)
  emits ordered spreadsheet rows as structured JSON and leaves final chunking
  to a later stage. Its [office table renderer](https://github.com/infiniflow/ragflow/blob/45637635df95140b0a0dc0d3693dc4b07b10595e/internal/parser/parser/office_table_render.go)
  distinguishes table-header chunks. These are useful boundaries: parsers
  should preserve typed rows and source coordinates; chunkers should preserve
  row integrity and repeat the necessary headers.
- Docling's [chunking options](https://github.com/docling-project/docling/blob/1ceca3073e499dcc9da2dc802ac1f18bce672978/docs/concepts/chunking.md)
  explicitly support repeating table headers as table rows are chunked. The
  upstream [DOCX table-cell fix](https://github.com/infiniflow/ragflow/pull/17497)
  and CSV quoted-field fix ([#16881](https://github.com/infiniflow/ragflow/pull/16881))
  demonstrate that format adapters need parser-specific regression fixtures;
  one successful PDF test cannot certify XLSX, DOCX, or CSV ingestion.
- [Unstructured's title chunker](https://github.com/Unstructured-IO/unstructured/blob/main/unstructured/chunking/title.py)
  defaults to isolating `Table`/`TableChunk` elements from neighboring prose,
  and its [table-isolation tests](https://github.com/Unstructured-IO/unstructured/blob/main/test_unstructured/chunking/test_table_isolation.py)
  lock that boundary down. This is a useful guard against a table row inheriting
  unrelated narrative text (or prose receiving a table's values) when chunks
  are later merged. [LlamaIndex's MarkdownElementNodeParser](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/node_parser/relational/markdown_element.py)
  provides a related pattern for Markdown exports: represent embedded tables as
  their own nodes and retain the source-document relationship instead of
  treating every table as undifferentiated prose.
- Docling's [incorrect-table-columns issue](https://github.com/docling-project/docling/issues/1678)
  reports misplaced rows/columns despite OCR and accurate table mode. This is
  why adding a parser or enabling OCR cannot replace output validation.
- Docling's [multi-page-table issue](https://github.com/docling-project/docling/issues/2976)
  reports continued tables split into separate tables in both standard and VLM
  pipelines. RAG-Anything's [failure checklist](https://github.com/HKUDS/RAG-Anything/blob/main/docs/multimodal_rag_failure_modes.md)
  likewise recommends inspecting intermediate table blocks and testing
  table-only retrieval questions. These are useful diagnostics, not guarantees
  that a parser switch fixes financial fact integrity.

These projects informed the provenance-first design; this implementation does
not claim their parsing accuracy or completeness.

## Current ingestion contract

Supported upload formats are PDF, XLSX, DOCX, and CSV. The browser and API
validate the same extension set, and the server also checks the content
signature/structure before accepting a file.

- **PDF:** PyMuPDF retains page/block provenance. Native bordered-table
  extraction is additive only and requires explicit distinct period columns,
  exact row width, and one value per mapped cell. A second deterministic path
  handles selectable-text, borderless financial statements whose date, year,
  and value cells are separate text blocks: it groups words by page coordinates,
  binds values to the nearest period-column centers, and joins only same-baseline
  cells. Headers may be SEC-style date/year cells or explicit comparative labels
  such as `Q4-2024`, `Q1-2025`; explicit quarter labels remain authoritative and
  are not reconstructed from filenames. For SEC date headers, fiscal-quarter
  keys are derived only when the opening report text establishes a reporting
  period and comparative dates align to quarter intervals; otherwise the exact
  period end date is retained without guessing a quarter. Units are carried
  from the nearby statement header; the primary financial-unit declaration
  (for example, "in millions") takes precedence over exception units (for
  example, share counts in thousands). EPS is represented as a per-share unit
  and is kept distinct from net-income numerators used to calculate EPS.
  Ragged rows, ambiguous headers, prose dates, and distant later rows are not
  promoted. The spatial path is bounded to the immediate continuous row run
  and at most one continuation page. Comparative text that cannot be mapped
  remains `unverified_table`; the production evidence gate and fact ledger
  exclude it, including from fallback evidence.
- **XLSX:** worksheets, row/column coordinates, nearby title/header rows, and
  number formats are retained. When one row contains distinct explicit period
  headers, data is bound by exact column coordinate; comparative numeric rows
  that cannot be mapped safely are tagged `unverified_table`. Sparse worksheets
  are streamed through their declared row range, so data after large blank gaps
  is not silently treated as end-of-data. OOXML merged-cell row spans are
  inspected separately because read-only spreadsheet parsing omits that layout
  metadata; merged period headers and merged financial value rows are
  quarantined until their exact cell-to-period mapping can be proven. Formula
  cells use only a cached workbook result. Formulas without cached values are
  explicitly marked as non-evidence; no formulas or macros are executed.
- **DOCX:** body paragraphs, headings, and tables are retained with paragraph
  or table/row locators. Nearby explicit unit declarations are attached to each
  table row so unit scaling survives chunk boundaries. A period-bearing header
  row is selected from the first five table rows and values must line up
  exactly; ragged rows and financial rows whose header/value grid uses merged
  cells are quarantined until exact span-aware mapping is implemented. This
  parser does not OCR embedded images.
- **CSV:** a period-bearing header row may occur within the first five rows;
  rows are rendered as header/value pairs only when the source columns map
  exactly. Comparative numeric rows with repeated, split, or otherwise
  ambiguous period labels are quarantined. Arbitrary merged/multi-row header
  schemas are not guessed.

Each indexed chunk carries parser/chunker version, source format, content type,
and a page, sheet/row, table/row, or CSV row locator where available. Citation
metadata carries those locations back to the UI.

Chunk sequence is source sequence (page, block, sheet, table, and row order),
not vector similarity order. Embeddings are used to rank retrieval candidates;
they must never be used to reconstruct or sort the source document. `chunk_index`
is assigned only after deterministic parsing/chunk assembly, and each citation
continues to point to its original locator. Tables are isolated from adjacent
prose before token-size chunking; if a table must span chunks, its period/unit
headers are repeated or carried as table context.

Cross-format acceptance is based on normalized facts, not similar-looking text:
fixtures for PDF, XLSX, DOCX, and CSV must agree on company, canonical metric,
period, unit/currency, normalized value, and a resolvable source locator. The
tests also verify segment facts independently (for example, Data Center versus
Edge Computing); a consolidated total or a repeated nearby number cannot stand
in for a missing segment row. Parsing, retrieval, and final-context inclusion
are measured as separate stages so a lost claim is attributed to the actual
failure boundary rather than “PDF versus Excel” by guesswork.

Company and period metadata must be supported by opening document content.
Filename values are retained only as diagnostic hints. If multiple known
issuers appear in the opening content, or the filename hint conflicts with the
content, company scope becomes `Unknown`. Multiple comparative periods also
remain `Unknown` at whole-document level; chunk-level period extraction keeps
the periods side by side rather than assigning the whole report to one period.
Common fiscal labels including `Q1 FY27`, `Q1 FY2027`, `Q1 Fiscal 2027`, and
Chinese fiscal-quarter forms normalize to the same period key. This matters for
split table rows such as diluted EPS: adjacent fiscal-year headers must remain
bound to the correct EPS value, not merely inherit a filename or document-level
quarter.

Retrieval also preserves intent-specific evidence coverage. A request for
business segments reserves candidates from distinct numeric-bearing section
headings (for example, Data Center and Edge Computing) instead of allowing a
consolidated income-statement chunk to consume the full context. If a PDF page
parser retained the heading in chunk text but exposed only a generic page label
as metadata, the retrieval path can derive that nearby heading conservatively.
Growth-driver questions reserve reported management commentary while excluding
safe-harbor boilerplate from that required evidence slot. This is a retrieval
coverage safeguard, not a claim that section labels alone prove a financial
number. Fact extraction remains bound to the row label, period, value, and
source provenance. Regression tests exercise the known NVIDIA Q1 FY2027 segment
and growth-driver omissions, plus equivalent Data Center and Edge Computing
fact extraction from PDF, XLSX, DOCX, and CSV fixtures.

The API citation list is a presentation set, not a dump of retrieval results.
Only chunks that the final grounding pass binds to an answer clause may be
shown as citations; a valid but unused retrieval chunk is not evidence for the
user-visible answer and must be omitted. After unused chunks are removed,
answer-side `[Evidence n]` markers are compacted to the same rank sequence as
the returned citation cards. This prevents a valid source from becoming a
misleading citation solely because presentation filtering changed its index.

## Reprocessing existing documents

Parser and chunker versions are stored with vector metadata. Existing indexed
documents do not change merely because parser code was updated. After deploying
an ingestion change, operators must reprocess/reindex documents through the
existing document lifecycle before expecting updated chunks or citations.
Reindexing must remain tenant-scoped and must not bypass upload authorization.

## Known limits and acceptance criteria

Structure preservation reduces format-induced ambiguity; it does not establish
that a report is genuine, that every table was extracted, or that a generated
claim is true. Unsupported/ambiguous content must remain ungrounded rather than
being upgraded based on a filename or a nearby number.

The current adapters normalize explicit comparative rows to a common
metric/period/value representation, but do not attempt arbitrary merged-cell
schemas or OCR-only layouts. XLSX merged cells are conservatively quarantined
at row granularity rather than reconstructed across spans. PDF period headers
must be actual table columns with coordinate-aligned values; inline narrative
dates are not promoted. The three public demo reports exercise different paths:
Apple/NVIDIA include spatial date-column binding, while Tesla includes explicit
quarter-label columns as well as native table extraction. Parser row counts are
not an accuracy score; exact values, periods, units, and rejected rows must be
asserted by regression tests before widening accepted layout patterns.

Before enabling another parser backend such as Docling or PP-StructureV3,
evaluate it offline on the same representative PDF/XLSX/DOCX/CSV filings and
compare canonical fact records, not only exported Markdown or retrieval scores:

1. Equivalent reports encoded as PDF, XLSX, DOCX, and CSV produce the same
   normalized row-label/value/period/unit/currency facts where the source
   formats contain the same data, including unit footnotes and title/preamble
   rows, and DOCX unit notes remain attached even when the table is chunked away
   from the explanatory paragraph.
2. Split-coordinate date headers, repeated inline prose dates, missing cells,
   continuation pages, and deliberately misaligned numeric values either
   preserve exact cell bindings or fail closed for numeric evidence; they must
   not guess a neighboring period.
3. Every accepted fact points to an exact page/table/row/cell or sheet/cell
   locator and records parser version and source hash.
4. Chunk recall and final-context evidence coverage remain measured separately
   from table-extraction correctness.
5. Wrong-company and wrong-period citation rates do not regress, and CPU/RAM,
   image size, and parse latency remain acceptable.

The parser output is not a correctness oracle. Docling provides a unified
representation with tables, document hierarchy, layout, and provenance;
PP-StructureV3 offers layout/OCR/table-structure extraction. Both are candidate
backends for evaluation, not automatic replacements. A parser issue can still
shift columns, so every backend must pass the exact-cell binding and fail-closed
fixtures before its extracted rows can support numeric answers.

No LLM provider is called during parsing or its regression tests. Historical
index contents may require a controlled reindex before the fix is visible in
the running application.

## GitHub implementation cross-check (2026-09-18)

Public implementations were reviewed for concrete patterns, not treated as
accuracy guarantees:

- [FinDocStructRAG](https://github.com/AD2000X/FinDocStructRAG) describes a
  financial-document pipeline that keeps table topology, spanning-cell
  mapping, OCR-to-cell assignment, canonical structured output, and table
  retrieval as separate stages. This supports preserving row/column bindings
  and testing extraction separately from retrieval. It is a research prototype
  with its own stated evaluation scope, not a production parser to adopt
  without corpus-specific testing.
- [Docling](https://github.com/docling-project/docling) uses a structured
  document representation across formats and exposes layout, reading order,
  table structure, OCR and lossless exports. The useful design lesson is to
  retain structure and provenance through conversion; converting every source
  directly to plain Markdown would lose information needed to validate exact
  financial cells.
- [RAGFlow](https://github.com/infiniflow/ragflow) separates format/parser
  handling from chunking, offers table-aware chunking and source-linked
  citations, and documents support for heterogeneous inputs. Its open parser
  and chunking issue history also demonstrates that broad format support does
  not guarantee no row/cell loss. This project therefore retains per-format
  fixtures instead of using “file accepted” as an integrity signal.
- [LettuceDetect](https://github.com/KRLabsOrg/LettuceDetect) provides a local,
  span-level grounding-verification approach for flagging unsupported answer
  spans. Such a verifier could supplement claim-to-evidence review, but it
  cannot repair a value already misbound to a row/period during parsing, and
  any model-based verifier needs independent calibration against this
  project's financial gold set.

The current implementation already follows the applicable low-risk patterns:
canonical row/value/period/unit extraction, source locators, parser-versioned
chunks, separate retrieval/context gates, and fail-closed treatment of
ambiguous tables. Offline verification on this checkout:

```text
Equivalent PDF/XLSX/DOCX/CSV facts: PASS
Equivalent segment facts across supported formats: PASS
Public retrieval, multi-company risk evidence and disclaimer exclusion: PASS
Apple/Tesla comparison retrieval regression: PASS
NVIDIA headline/driver retrieval regression: PASS
Focused bilingual planning regressions: PASS
Combined: 33 passed, 1 existing Starlette/httpx deprecation warning
Real Provider/evaluator calls: 0
```

This closes only the tested ingestion/retrieval regression boundary. It does
not certify arbitrary reports, scanned-only layouts, merged financial grids,
all 100 historical semantic grades, or all 341 citation entailment judgments.
New parser backends and newly accepted layout patterns must pass the same
canonical-fact, provenance, fail-closed, bilingual-retrieval and citation
regressions before being enabled. Frozen benchmark expected answers remain
unchanged.
