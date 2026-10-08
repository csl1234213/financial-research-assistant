# Financial RAG — Format-Agnostic Period Retrieval Repair

Date: 2026-09-18

## Scope and safety

This repair uses only local deterministic tests, existing public demo reports,
and synthetic evidence with a fake embedding/store. It does not call DeepSeek,
any other model provider, or an evaluator API; provider calls and cost are zero.
It does not modify benchmark expected answers or historical result artifacts.

## Root cause reproduced

The retrieval contract had two period-evidence gaps:

1. ``matches_filter(..., "period", ...)`` examined row metadata, chunk text,
and document-quarter metadata, but not the parser's local ``table_context``.
For a valid table row whose heading and numeric row were stored separately,
the row could therefore fail to match its stated quarter.
2. If the chunk text explicitly said Q2, a stale parent/document ``quarter``
field saying Q1 could still pass the Q1 filter because the fallback only
checked whether the text mentioned more than one period. One explicit,
conflicting period was incorrectly allowed to inherit the document quarter.

With a higher-scoring Q2 outlook candidate and a lower-scoring Q1 actual row,
the public ``HybridRetriever.retrieve`` path reproduced the wrong-period
selection at ``top_k=1``. This occurred with the hybrid store and with the
vector-only fallback.

### Follow-up candidate-coverage finding

The public NVIDIA sample PDF parses a Q1 FY2027 gross-margin narrative as one
chunk containing both the period and ``74.9%``. A separate comparative-table
chunk contains several gross-margin percentages but is classified as
``unverified_table`` and has no row-to-column period binding. The latter must
not be treated as authoritative Q1 evidence just because it is near a table
heading or belongs to a Q1 filing.

A deterministic public-retriever regression then reproduced a second failure:
with ``top_k=2``, higher-ranked same-period cash-flow and revenue rows filled
the company/period slots, truncating a lower-ranked but exact gross-margin
row. The selector now reserves an exact company-period-metric table row before
generic company/period/metric slots when that binding is actually present.
This narrower ordering applies to FACT and metric-specific COMPARE queries;
broad SUMMARY queries retain their existing multi-metric coverage policy. If
table row period binding is missing, the exact slot is unavailable and the
row is not upgraded by filename or document-quarter hints.

## Changes

- Explicit period text in a chunk now takes precedence over cached document
  period metadata. A chunk that says Q2 cannot satisfy a Q1 request merely
  because its parent metadata or filename hint says Q1.
- A fiscal-marker spelling variant (``Q2 FY2026`` vs ``Q2 2026``) is accepted
  only when the independently extracted document quarter exactly confirms the
  unmarked request and quarter/year are otherwise identical. It cannot
  override a different quarter in the explicit chunk text.
- A trusted single-period table header in ``table_context`` can supply the
  period for its split metric row. A multi-period/unbound table header cannot
  guess which column a value belongs to; explicit row/column period evidence
  remains required.
- For explicit metric FACT questions (and metric-specific comparisons),
  period-matched evidence is reserved before broad company/metric slots, so a
  high-similarity adjacent-quarter chunk cannot consume a small top-k slot.
- When lexical retrieval is disabled/unavailable, explicit-period requests
  still pass through this period-aware selector. Unconstrained vector-only
  queries preserve their prior vector ordering.
- Broad financial summaries and multi-metric comparisons keep their existing
  coverage ordering; the period-first policy is deliberately not applied to
  those query scopes.
- Historical replay also exposed an answer-completion alias mismatch:
  ``services and other revenue`` was recognized by the fact ledger but not by
  the required-fact checker, so the production grounding boundary appended a
  duplicate ``Services revenue`` claim. Required-fact checks now use the
  central ledger alias registry, including Chinese ``净销售额`` / total-revenue
  aliases. A segment-revenue line cannot satisfy consolidated revenue merely
  because its number happens to equal the consolidated amount.

## Format-variation boundary

The repository already has format-specific extraction for spatial PDF tables
and structured CSV/XLSX/DOCX rows, carrying fields such as ``table_context``,
``content_type``, source locator, and metric/value binding. The regression
exercises the common retrieval contract at the public entry point using
synthetic representations of split table headers/rows, while existing parser
tests continue to validate format-specific extraction. Ambiguous, merged,
ragged, or unbound comparative tables remain unverified; this fix does not
make such rows safe numeric evidence and does not promise that arbitrary OCR
or layouts will parse perfectly.

## GitHub implementation patterns reviewed

- The NVIDIA/KX financial RAG blueprint uses temporal columns, hybrid query
  support, and period-aware query interpretation. This supports keeping
  issuer/period as explicit evidence metadata rather than relying on dense
  similarity alone: [KX financial RAG strategy](https://github.com/KxSystems/nvidia-kx-samples/blob/3a01bf3e6d1d445e8c284dd601d7f57e026d8139/KX-nvidia-rag-blueprint/docs/kdbai-financial-rag-strategy.md).
- A financial multimodal RAG example combines table/chart extraction with
  dense plus BM25 retrieval and RRF. The transferable pattern is structured
  extraction plus hybrid retrieval—not a different embedding model alone:
  [Multimodal Financial RAG example](https://github.com/Mattral/RAG-Multimodal-Financial-Doc-Analysis-and-Recall/blob/2ee24ad1b5e766e44f6c02b68c7f6668602462f0/spaces/rag-financial/app.py).
- RAGFlow exposes parent-child chunking and documents parser bugs involving
  dropped table cells. This is a useful reminder that parser choice is not a
  substitute for format-specific ingestion fixtures and evidence validation:
  [RAGFlow parent-child API option](https://github.com/infiniflow/ragflow/blob/15b6668dd8f7a8921cecec9fae4e4d46f7947bdd/docs/references/http_api_reference.md),
  [RAGFlow parser fixes](https://github.com/infiniflow/ragflow/blob/15b6668dd8f7a8921cecec9fae4e4d46f7947bdd/docs/release_notes.md).

The follow-up GitHub review found three directly relevant patterns:

- [Docling's PDF/RAG pipeline](https://github.com/docling-project/docling) converts
  layout-aware documents into typed structure, retains headings/page metadata,
  and offers `HybridChunker` / line-based chunking. Its table chunking can repeat
  headers across chunks and keeps lines intact. This is a strong candidate for a
  complex-PDF parser adapter, not evidence that every table extraction is exact.
- [RAGFlow's PDF parser](https://github.com/infiniflow/ragflow/blob/main/deepdoc/parser/pdf_parser.py)
  combines OCR, layout recognition, and table-structure recognition. It shows
  that robust handling of scans, columns, and tables is a dedicated parsing
  subsystem; adopting it would also add model/runtime weight and needs a local
  resource and quality benchmark.
- [SEC Insights](https://github.com/run-llama/sec-insights) is a 10-K/10-Q RAG
  reference with citations and PDF citation highlighting. For SEC filings where
  the issuer and accession can be authoritatively matched, [edgartools' XBRL
  interface](https://github.com/dgunning/edgartools/blob/main/edgar/xbrl/docs/XBRL.md)
  offers structured statements, facts, units, dimensions, and period filters.
  XBRL can validate or complement a user-uploaded filing; it cannot replace a
  general parser for arbitrary PDFs, and it must not silently substitute a
  different accession, issuer, or period.

Recommended next design is a parser cascade behind the existing normalized
`ParsedDocument` contract: keep the current PyMuPDF/OCR fast path for clean
born-digital prose and simple tables; route scanned, multi-column, or structurally
ambiguous pages to a layout/table-aware backend; keep CSV/XLSX/DOCX on their
native structured readers. Preserve row label + column header + period + unit +
page/section provenance as one evidence unit, and reject or mark ambiguous rows
unverified rather than indexing a guessed numeric binding as trusted evidence.
Before enabling a new backend, compare both parsers on a versioned corpus that
includes split headers, repeated/merged headers, landscape tables, footnote unit
declarations, multi-column prose, scanned pages, and irregular table layouts.
Gate rollout on exact row/value/period/unit binding and citation-location checks,
then re-index only with a bumped parser/chunker version. This is a proposed
architecture; no parser dependency or migration was introduced in this repair.

These are architectural references, not production guarantees. No new parser
dependency or parser migration was introduced; adoption should first be
benchmarked against the local Apple, NVIDIA, and Tesla filings and the existing
format fixtures.

## Verification

The focused offline regressions cover:

- split, single-quarter table header and value row;
- rejection of a multi-period header with no row/column binding;
- rejection of explicit Q2 content under stale Q1 document/filename metadata;
- acceptance of matching fiscal-marker spelling variants only when the
  document-level period independently confirms the same quarter/year;
- public hybrid and vector-only retrieval selecting Q1 actual over Q2 outlook;
- public retrieval retaining an exact period-metric row when higher-ranked
  same-period statement rows would otherwise fill a small ``top_k``;
- two-company risk retrieval retaining each issuer's concrete risk evidence
  without using generic forward-looking disclaimers as context slots.

The focused retrieval/parser regression command passed:

```text
pytest -q tests/test_hybrid_retrieval.py tests/retrieval/test_period_aware_retrieval.py tests/test_document_loader.py tests/test_document_formats.py
124 passed, 1 warning
```

After the bilingual fiscal-marker case was added, the combined offline
evaluation, retrieval, and format-parser regression command also passed:

```text
pytest -q tests/evaluation tests/test_hybrid_retrieval.py tests/retrieval/test_period_aware_retrieval.py tests/test_document_loader.py tests/test_document_formats.py
421 passed, 1 warning
```

The replay-only alias regression is covered by two additional assertions:
the original ``Services and other revenue`` answer is retained without a
duplicate appended fact, and a services-segment revenue line cannot satisfy a
consolidated-revenue requirement. The approved fake-store public retrieval
test also confirms that a two-company risk query reserves concrete evidence
for both companies without allowing either safe-harbor disclaimer to consume
the result slots.

The frozen 100-answer set was replayed through the deterministic production
grounding/finalization boundary into a new, non-overwriting artifact directory:
``evaluation/results/offline_grounding_replay_20260918_v6``. It made zero
provider/evaluator calls and cost $0. It reports zero final unsupported
numeric claims and four pairs with required-fact coverage differences, but
the stored historical semantic grades remain unchanged (29 CORRECT, 37
PARTIAL, 33 INCORRECT, 1 FAILED). This is **not** a semantic re-grade and does
not resolve the historical 33/1 answer-quality findings or prove bilingual
meaning equivalence.

The warning is an existing Starlette/httpx deprecation notice. Ruff and
``git diff --check`` also passed for the edited Python files/worktree. No
DeepSeek call, 5Q/100Q run, Docker rebuild, commit, or push was performed. The
frozen answer/citation/bilingual quality gates remain open and have not been
re-graded by this change.

## Frozen citation-label integrity recheck

Review of the frozen ``formal_20260916`` annotations found that the previous
citation validator treated a rank marker anywhere in an answer as support for
the separately annotated claim. That allowed a claim to borrow a different
sentence's citation. The validator now requires the exact claim and citation
marker to occur in the same sentence/clause; otherwise the annotation is
``REVIEW_INDETERMINATE``. A deterministic offline revalidation command and
fixture tests were added. It refuses to run if ``ALLOW_REAL_PROVIDER`` is
enabled and refuses to overwrite an existing output directory.

Running it over the 341 frozen annotations produced:

| Status | Count |
| --- | ---: |
| ``VALID_SUPPORTED`` | 94 |
| ``VALID_BUT_NOT_SUPPORTED`` | 46 |
| ``UNUSED_RETRIEVED_CONTEXT`` | 127 |
| ``REVIEW_INDETERMINATE`` | 74 |

Of the original 223 ``VALID_BUT_NOT_SUPPORTED`` labels, 122 were candidates
never referenced by an answer marker, 55 had an invalid/unattached claim or
quote annotation and require re-review, and 46 retained the unsupported label
after source/quote/claim/rank integrity checks. The remaining 46 are still
same-provider semantic judgments, **not independent human adjudications**;
this audit therefore corrects annotation integrity but does not claim that all
citation-entailment problems are resolved. Full machine-readable results are
in ``evaluation/results/offline_citation_revalidation_20260918_v1``.

The frozen 50 English/Chinese pairs also have 19 answer-grade disagreements
in the historical same-provider reviews. Separately, production-policy replay
finds four pairs with deterministic required-fact coverage differences. These
are distinct signals; neither is a human bilingual-equivalence audit. The
four deterministic cases are EN/ZH-010 (Q1 margin facts), EN/ZH-021 (Tesla
comparison facts), EN/ZH-037 (Apple Q2 revenue), and EN/ZH-046 (Tesla margins).
They remain targeted offline regressions to resolve; the frozen 19 grade
labels have not been changed.

The follow-up retrieval regression initially failed with only the same-period
cash-flow and revenue rows returned. After adding the exact metric coverage
slot, the focused period/risk/margin tests passed. A full provider-disabled
offline suite then completed with ``2417 passed, 23 skipped``. An intermediate
run surfaced an Apple broad-summary regression; the exact period-metric slot
was restricted to fact and metric-comparison scope, and both the Apple summary
case and the full suite passed on rerun. No evaluator or provider was called.

The revalidation and fixture-contract suite passed 22 tests before its latest
offline artifact run. A later combined suite passed 425 tests before the
Tesla follow-up regressions below were added.

## Tesla bilingual margin follow-up regression

The public `HybridRetriever.retrieve` path now has an offline bilingual
follow-up regression using the actual local Tesla PDF plus a fake vector/lexical
store. The follow-up inherits Tesla and Q2 2025 from conversation history and
must return both gross-margin and operating-margin evidence without Apple or
NVIDIA contamination. A synthetic split-row regression also covers
`Total GAAP gross margin` in an explicit comparative table.

The regression exposed a production selector bug: the financial-row coverage
regex recognized `Total gross margin`, but not `Total GAAP gross margin`.
The gross-margin row therefore lacked the `table_metric_value:gross_margin`
coverage dimension. Under a multi-metric follow-up, other Tesla rows could
consume the available context slots even though the requested GAAP margin was
present in the parsed filing. The row recognizer now accepts the explicit
`GAAP` qualifier while continuing to keep segment rows (such as automotive
gross margin) distinct from consolidated gross margin.

The frozen 100-answer production-policy replay was rerun into the new
non-overwriting artifact `evaluation/results/offline_grounding_replay_20260918_v8`.
It still reports four deterministic required-fact parity differences (010,
021, 037, 046), because the replay deliberately preserves historical raw
answers and frozen citations; it is not a fresh retrieval replay and cannot
rewrite those historical outputs. Thus the EN/ZH-046 historical mismatch is
not erased by fixing the current retrieval path. The frozen semantic grade
counts likewise remain unchanged: 29 CORRECT, 37 PARTIAL, 33 INCORRECT, and
1 FAILED. The historical 19 English/Chinese grade disagreements and the
remaining citation entailment adjudications are still open.

Latest combined offline verification:

```text
pytest -q tests/evaluation tests/test_hybrid_retrieval.py tests/retrieval/test_period_aware_retrieval.py tests/test_document_loader.py tests/test_document_formats.py
428 passed, 1 warning
```

The warning is an existing Starlette/httpx deprecation notice. This establishes
the selected offline evaluation, retrieval, and parser regression set only; it
does not satisfy the full semantic release gate. No Provider calls, real 5Q or
100Q evaluation, Docker rebuild, commit, or push were performed.

## 2026-09-18 offline continuation

Further examination of the four deterministic EN/ZH replay differences found
two additional current-path defects:

- An unqualified request about NVIDIA's Q1 margins was converted into two
  required facts (gross margin and operating margin), although the report's
  explicit margin disclosure is GAAP/non-GAAP gross margin. Generic margin
  planning now requires margin types actually present in evidence; a question
  explicitly asking for gross **and** operating margin still requires both.
- Broad company comparisons filled metric slots company-by-company. Under the
  fixed top-K budget this let Apple rows consume slots before Tesla's margin
  rows. Broad comparison slots now prioritize revenue, net income, gross
  margin, and operating margin across issuers before optional cash-flow/EPS
  rows. Company/period binding is unchanged.

Current public-retriever regressions now exercise local Apple, NVIDIA, and
Tesla PDFs for the four historical mismatch families: Q1 NVIDIA margin
disclosure, Apple/Tesla comparative metrics, the English and Chinese "iPhone
maker" Apple alias, and the bilingual Tesla Q2 margin follow-up. The Tesla
comparison regression requires Q2 2025 revenue, net income, gross margin, and
operating margin to be present in both language paths. These establish
retrieval/context coverage only; they do not re-grade or rewrite frozen
historical answers.

The latest combined offline suite passed **429 tests**. A new frozen replay
artifact, `evaluation/results/offline_grounding_replay_20260918_v9`, again
records zero provider calls, zero evaluator calls, and $0 cost. It still shows
four differences because it intentionally reuses the original retrieval
citations and answers. Historical grades remain 29 CORRECT, 37 PARTIAL, 33
INCORRECT, and 1 FAILED; all 19 same-provider EN/ZH grade disagreements are
unchanged. The 46 remaining citation entailment labels still need independent
semantic adjudication. No claim is made that the full quality objective is
complete.

The complete backend suite initially exposed seven quota-test failures. The
local `.env` enables an evaluation bypass for an allowlisted runtime tenant;
tests had inherited that local setting, so normal quota enforcement tests
were accidentally exercising the bypass. `tests/conftest.py` now starts tests
with evaluation bypass disabled, an empty test allowlist, and ordinary chat
limits enabled. Tests specifically covering evaluation bypass still opt in
explicitly. The seven affected quota/429 regressions then passed, followed by
the complete offline backend suite:

```text
ALLOW_REAL_PROVIDER=false pytest -q
2395 passed, 23 skipped, 1 warning
```

The 23 skipped cases require a live Provider or external runtime setup. The
run made no DeepSeek or evaluator API calls. Ruff and `git diff --check` are
recorded separately after the final edits.

## Two-column PDF reading-order regression

A generated two-column PDF reproduced a separate parser defect: PyMuPDF's
geometric `sort=True` order yielded `left-1, right-1, left-2, right-2`, weaving
paragraphs from adjacent columns. The parser now switches to column-major
ordering only when it sees at least two prose blocks on each side, a stable
central gutter, and non-overlapping column bounds. Full-width blocks remain
section separators; numeric/table-like text is not used to infer the columns.
Ambiguous pages keep the prior order instead of being force-classified. The PDF
parser version was bumped so re-ingestion can distinguish the new ordering.

Regression coverage includes a generated multi-column PDF plus a direct
full-width-section-break ordering contract; existing PDF table, OCR, XLSX,
DOCX, and CSV parser tests remain part of the focused suite. The test reproduced
the old interleaving before the fix and passes with the new order. The official
[PyMuPDF Layout extension](https://github.com/ArtifexSoftware/pymupdf_layout)
and [Docling](https://github.com/docling-project/docling) remain candidates for
more complex layouts, but neither was added as a dependency in this change.
PyMuPDF Layout's licensing terms and runtime compatibility must be reviewed
before production adoption. This deterministic two-column fix is not a claim
that arbitrary scans, tables, or all multi-column designs are now supported.

Post-change verification:

```text
pytest -q: 2397 passed, 23 skipped, 1 warning
ruff check .: PASS
git diff --check: PASS
```

Docker Desktop was launched, but its Linux engine remained unavailable and
`com.docker.service` could not be started from this session. No image rebuild,
container recreation, data-volume change, Provider call, or evaluation run was
performed after the parser change.

## Public hybrid retrieval risk-coverage check

Using the approved offline boundary, the public `HybridRetriever.retrieve`
entry point was exercised with a local fake vector store and synthetic Apple
and NVIDIA evidence. The question compared both issuers' risk factors with
`top_k=2`. Each issuer had a high-scoring generic forward-looking disclaimer
and a lower-scoring concrete risk disclosure. Retrieval returned the Apple
and NVIDIA risk chunks, and neither disclaimer occupied a final slot. The
test made no Provider calls.

Verification after this check:

```text
Focused multi-company risk + parser regressions: 6 passed
pytest -q tests/test_document_loader.py tests/test_document_formats.py: 79 passed
ALLOW_REAL_PROVIDER=false pytest -q: 2397 passed, 23 skipped, 1 warning
ruff check .: PASS
git diff --check: PASS (Git emitted only existing line-ending warnings)
```

The 23 skips are live-provider or external-runtime cases. Docker's Linux
engine remained unavailable, so Docker runtime health/rebuild was not
verified. Historical semantic grades, bilingual disagreements, and remaining
citation-entailment adjudications remain unresolved; this offline retrieval
check does not close those quality gates.

## Canonical parser spot-check on the shipped public PDFs

The same `load_pdf_chunks` ingestion path was run against the repository's
Tesla, Apple, and NVIDIA demo PDFs with OCR disabled. It produced 208, 330,
and 92 chunks respectively. For each file, both probed headline numeric facts
and the normalized filing period were found (Tesla `Q2_2025`, Apple `Q2_2026`,
NVIDIA `Q1_FY2027`). NVIDIA's source says “First Quarter Fiscal 2027”; a
literal search for `Q1 FY2027` had reported a false miss, while the canonical
period extractor correctly normalized the source wording. Thus this spot-check
did not reproduce a period-binding defect in these three files.

MuPDF emitted `No common ancestor in structure tree` diagnostics on some
tagged pages and its advisory to consider `pymupdf_layout`; extraction still
completed and the probed facts/periods were present. These diagnostics are
recorded as parser robustness signals, not treated as proof that arbitrary
PDF layouts are handled correctly. Production adoption of a layout engine
still needs licensing, runtime, and corpus-level evaluation before replacing
the current parser.

## Layout-engine comparison spike (local only)

The candidate-engine check was run in an isolated temporary virtual environment
outside the repository using Docling `2.128.0`, with OCR disabled, table
structure enabled, and remote services disabled. The only inputs were the
repository's public/demo Tesla, Apple, and NVIDIA PDFs. Model artifacts were
downloaded to a temporary local cache; no report content was uploaded and no
LLM/Provider was invoked.

Docling extracted the probed facts from the full sample set:

| PDF | Pages | Probed facts found | Conversion time |
|---|---:|---:|---:|
| Tesla | 35 | 2/2 | 78.8s |
| Apple | 32 | 2/2 | 66.9s |
| NVIDIA | 9 | 2/2 | 23.6s |

The combined conversion time was about 169 seconds for 76 pages, compared with
about 8.6 seconds for the current canonical parser on this machine (roughly
19.6x slower in this small, non-production spike). NVIDIA's first-page-range
run also emitted a table-structure warning that 7 of 59 PDF cells were dropped
from one 12x3 table. The full run emitted further orphan/dropped-cell warnings;
their per-table mapping was not captured, so no stronger claim about table
fidelity is made. The successful headline probes are not a guarantee that all
table cells, layouts, or reports are faithfully reconstructed.

Docling is MIT-licensed and offers a credible local layout/table extraction
fallback to benchmark further. Its documented settings allow remote services
to remain disabled, but its model artifacts still need to be installed or
downloaded locally. These results do not justify replacing the current fast
parser as the default. A future opt-in fallback should be selected only for
pages flagged as layout-ambiguous, and only after a per-table cell/value
fidelity gate and resource budget are defined. By comparison, PyMuPDF Layout is
AGPL-3.0 while this repository is MIT-licensed; adding that package would need
an explicit license review rather than being treated as a drop-in dependency.

Sources: [Docling license](https://github.com/docling-project/docling/blob/main/LICENSE),
[Docling advanced PDF options](https://github.com/docling-project/docling/blob/main/docs/usage/advanced_options.md),
[Docling chunking concepts](https://github.com/docling-project/docling/blob/main/docs/concepts/chunking.md),
[PyMuPDF Layout license](https://github.com/ArtifexSoftware/pymupdf_layout/blob/main/LICENSE).

This is a candidate-engine comparison, not proof of format-agnostic ingestion.
The repository's own PDF, DOCX, XLSX, and CSV test suite remains the active
baseline; DOCX/XLSX/CSV are handled by separate structured parsers, so no claim
is made that PDF layout findings generalize to those formats.

## GitHub pattern review and current-code fit

Two relevant upstream implementation patterns were inspected on GitHub:

* [Docling native chunking](https://github.com/docling-project/docling/blob/main/docs/concepts/chunking.md)
  chunks from document structure, carries heading/caption metadata into chunk
  context, and can repeat table headers when a long table spans chunks. This is
  directly relevant to metric-period-value binding; it is a candidate parser
  path, not a reason to replace every existing parser without a fidelity gate.
* [PyMuPDF4LLM layout-aware chunking](https://github.com/pymupdf/pymupdf4llm/blob/main/CHUNKING.md)
  documents layout-boundary chunks, semantic heading/table-caption merges,
  table-preserving modes, section-start boundaries, and ingestion diagnostics.
  Its [repository license](https://github.com/pymupdf/pymupdf4llm/blob/main/LICENSE)
  is AGPL-3.0, so it is not a dependency recommendation for this MIT project
  without an explicit license decision.

The project already has the compatible architectural seam: format-specific
PDF/Office/CSV parsers emit provenance-bearing `DocumentChunk`s, while shared
fact grounding and retrieval consume normalized row evidence. For example,
`tests/test_document_formats.py::test_segment_metrics_normalize_consistently_across_report_formats`
builds equivalent PDF, XLSX, DOCX, and CSV segment disclosures and verifies
that the same metric/period/value facts survive. Existing parser and hybrid
retrieval suites also cover table binding, ambiguous-period quarantine,
multi-column reading order, and multi-company evidence coverage. The next
safe step for a new format/layout is to add a source-backed fixture and verify
row values, period, issuer, locator, and retrieval before enabling it for
uploads; a prompt rewrite alone cannot restore data that parsing or retrieval
discarded.

## Actual sample-corpus retrieval probe

An additional offline probe ran the public `HybridRetriever.retrieve` entry
point over all 630 chunks emitted from the three demo PDFs, using the
deterministic seeded-hash embedding and in-memory vector store used by the
retrieval gate. This substitutes a deterministic test embedder for the
production embedding model, so it tests parser-to-retriever wiring and
coverage behavior, not production vector relevance.

For English and Chinese Apple-vs-NVIDIA risk-comparison queries, the final
top-4 contained both requested issuers and no third-company evidence. In the
Chinese query, one NVIDIA result was the source's Q2 outlook paragraph; this
may be relevant to the China-related export caveat in that release, but the
probe did not perform semantic risk-entailment grading. Therefore company
coverage passed, while substantive risk completeness remains unscored. The
NVIDIA demo release contains limited forward-looking risk discussion rather
than the full 10-K risk-factor section, so no retriever can return absent
disclosures from that file.

The first attempt through the legacy `load_documents()` wrapper stopped
because it enabled OCR on this host, where Tesseract is not installed. No
production setting was changed. The successful repeat called the canonical
`load_pdf_chunks(..., ocr_enabled=False)` path, appropriate for these digital
PDFs. This is an environment dependency note, not a parse/retrieval failure.

## Grounding contradiction and bilingual-difference triage

The frozen EN-010 raw answer denied that NVIDIA's Q1 FY2027 margin was present,
then added a Q2 outlook-vs-actual correction. With the actual NVIDIA sample PDF
parsed and retrieved through the current public hybrid path, the production
finalizer could prove the Q1 gross-margin fact (74.9%) but previously left the
stale generic denial in place. This was a grounding/final-answer defect, not a
missing-source or period-retrieval defect.

The finalizer now treats an unqualified “no margin figures” absence statement
as superseded when the requested gross/operating margin is supported, and drops
the now-redundant number-free Q2 outlook correction in a single-period FACT
answer. It does not let a generic “margin” mention satisfy both metric types,
and numeric comparison/correction sentences remain subject to normal grounding.
The answer heading is also localized to the question language. A production
contract regression uses the same stale English raw answer against English and
Chinese Q1 questions and verifies both retain the supported 74.9% fact, remove
the contradiction, and report zero unsupported numeric claims.

The remaining frozen required-fact coverage differences were triaged without
rewriting historical answers or expected criteria:

| Pair | Finding | Current interpretation |
|---|---|---|
| EN/ZH-010 | EN raw answer incorrectly denied an available Q1 margin; current retrieval supplies it. | Production grounding contradiction; fixed and covered by a bilingual regression. |
| EN/ZH-021 | Frozen English and Chinese rows contain different Tesla facts in their cited evidence sets. | Historical evidence-coverage mismatch; not safe to synthesize missing evidence during replay. Current broad-comparison retrieval coverage has separate offline regressions. |
| EN/ZH-037 | Chinese frozen row has zero citations, while the English row has Apple Q2 revenue evidence. | Historical no-evidence refusal is appropriate for that replay input. Current English/Chinese “iPhone maker” alias and Apple Q2 retrieval are covered against the sample PDF. |
| EN/ZH-046 | Historical Tesla margin coverage differs; current retrieval/follow-up regressions cover Q2 2025 gross and operating margins in both languages. | Replay uses frozen citations and cannot establish fresh-path equivalence or alter historical grades. |

Reverification with real local PDF parsing plus seeded embeddings confirmed that
the supported Q1 NVIDIA gross-margin fact reaches the production finalizer; no
provider was called. Current focused offline verification:

```text
ALLOW_REAL_PROVIDER=false pytest -q tests/evaluation/test_final_answer_policy.py tests/test_hybrid_retrieval.py tests/retrieval/test_period_aware_retrieval.py tests/test_document_loader.py tests/test_document_formats.py
159 passed, 1 warning
```

The warning is the existing Starlette/httpx deprecation. Historical 100Q grades
(33 INCORRECT, 1 FAILED), 19 same-provider grade disagreements, the 46
unresolved citation-entailment labels, and full semantic equivalence remain
open. This update is an offline production-path regression fix and triage only;
it is not a semantic re-evaluation. No DeepSeek, evaluator API, live Smoke,
benchmark, Docker rebuild, commit, or push was run.

## Natural-language fiscal-quarter scope regression

Inspection of frozen EN-036 reproduced a critical period-parser gap. The query
asked about NVIDIA's data-center business in its “first fiscal quarter of
2027”, but the parser recognized only “first quarter of fiscal 2027”. It
therefore created no Q1 filter, and the historical Q2 FY2027 guidance value
($91B) survived the response boundary. This was a deterministic scope bug,
not a valid answer about the requested quarter.

Period parsing now accepts both ordinal-first forms, including “first fiscal
quarter of 2027” and “first quarter of fiscal year 2027”. A production
grounding regression asserts that Q2 FY2027 guidance cannot support that Q1
question. The bilingual-language guard was also tightened for English queries:
a material CJK share now triggers the localized evidence-only fallback, so a
Chinese raw answer is not returned just because company/period tokens and a
refusal sentence are Latin-script. Its regression covers the original mixed
language/wrong-period pattern.

The frozen 100-answer replay was run to a new, non-overwriting directory,
`evaluation/results/offline_grounding_replay_20260918_v11`. EN-036 now removes
the Q2 $91B claim and returns an English insufficient-evidence response. All
100 historical grade labels remain unchanged (29 CORRECT, 37 PARTIAL,
33 INCORRECT, 1 FAILED); there are still four required-fact parity differences
and zero final unsupported numeric claims. This replay verifies the current
deterministic response boundary against frozen inputs only; it is not a fresh
retrieval/model-answer evaluation and does not close the semantic gate.

Full provider-disabled backend verification after this change:

```text
ALLOW_REAL_PROVIDER=false pytest -q
2401 passed, 23 skipped, 1 warning
```

No DeepSeek/evaluator call, real 5Q/100Q run, Docker rebuild, commit, or push
was performed. Remaining incorrect/failed historical grades and citation
entailment/bilingual quality discrepancies still need offline diagnosis and
production-path regressions before real Provider use is allowed.

## Chinese single-period retrieval and narrow business-scope follow-up (v13)

An offline public-path regression using the NVIDIA demo PDF reproduced a
second EN-036 defect. The Chinese question named Q1 FY2027 and the data-center
business, but did not carry a resolved company entity. Period parsing was
correct, yet the final coverage-aware selector treated period only as a small
ranking boost for this analysis query. The Q2 FY2027 outlook paragraph could
therefore survive alongside Q1 evidence. English happened to avoid the leak
because its resolved company/context took a different path. This was not a PDF
segmentation failure: the Q2 paragraph was correctly extracted and labeled;
the final selector failed to honor the explicit conflicting period.

The production selector now excludes a candidate when a single-period query
conflicts with an explicit period in the chunk or trusted row-period metadata.
Unknown period remains eligible, and chunks that explicitly contain the
requested period remain eligible for claim-level grounding. No company alias
or benchmark question ID was added. Both English and Chinese public
`HybridRetriever.retrieve` tests now verify that Q1 Data Center revenue
($75.2B) is retrieved from the real local PDF, the Q2 $91B guidance chunk is
absent, and the finalizer keeps the supported Q1 fact without the wrong-period
claim.

The frozen EN-038 replay also exposed scope over-completion: “data centre
performance” was not recognized as the named business metric, so a broad
summary plan appended consolidated revenue and gross margin too. The exact
British-English alias is now recognized. Its offline regression supplies all
three facts and verifies only Data Center revenue is required and emitted for
the narrow question in both English and Chinese.

Latest non-overwriting replay:
`evaluation/results/offline_grounding_replay_20260918_v13`.
It processed all 100 frozen answers with zero provider/evaluator calls and
$0 cost. The historical grade labels remain 29 CORRECT, 37 PARTIAL,
33 INCORRECT, and 1 FAILED; final unsupported numeric claims remain 0.
Deterministic required-fact parity differences are 5/50 (pairs 010, 021, 036,
037, 046). This count is not a human bilingual-equivalence score and does not
cover the separate 19 historical grade disagreements. EN-036 now drops the
Q2 $91B claim and keeps the evidence-backed Q1 Data Center fact in the frozen
replay; the paired Chinese frozen item still has no citations and cannot be
repaired by inventing evidence. EN-038 no longer adds consolidated revenue or
gross margin. These results are production-policy replay, not a semantic
re-grade of the old model outputs.

Verification after these changes:

```text
ALLOW_REAL_PROVIDER=false pytest -q
2402 passed, 23 skipped, 1 warning
ruff check .
All checks passed
git diff --check
PASS (Git reported existing mixed-LF/CRLF working-copy warnings only)
```

The warning is the existing Starlette/httpx deprecation. The 33 INCORRECT,
1 FAILED, 223 citation-entailment concerns, and 19 English/Chinese grade
disagreements remain open pending offline semantic review and targeted
production-path fixes. No DeepSeek/provider/evaluator calls, benchmark
generation, Docker actions, Git staging, commit, or push were performed.

## 2026-09-18 follow-up: actual-vs-guidance grounding and format strategy

An offline regression from a frozen Tesla answer exposed a FactLedger parsing
error: a sentence saying total revenue was down 3% YoY to `$24.9B` was cut off
at the growth phrase, while a nearby regulatory-credit FX impact of `$0.3B`
could be misread as total revenue. Revenue evidence windows now retain the
explicit YoY/QoQ context, and generic revenue parsing rejects driver-only
phrases such as regulatory-credit revenue and “revenue was impacted by”. A
focused regression confirms Q4 revenue is `$24.9B`, not the FX impact.

Production numeric grounding now also separates reported actuals from
forward-looking guidance. Guidance-only facts cannot support a reported
performance claim; guidance is eligible only when the question and claim both
explicitly ask/state a forecast or outlook. Tests cover wrong modality,
allowed explicit outlook, and a mixed actual-plus-guidance chunk. These checks
run in `sanitize_answer`, the same grounding boundary used by the production
answer policy.

GitHub implementation review found relevant structure-preserving patterns:

- Docling `HybridChunker` builds on document hierarchy, can repeat table
  headers across chunks, and exposes contextualized chunk text plus metadata:
  <https://github.com/docling-project/docling/blob/main/docs/concepts/chunking.md>
- Unstructured `chunk_by_title` preserves document elements and supports table
  isolation and repeated headers; its PDF partitioner documents `hi_res` layout
  extraction and row/cell-preserving `text_as_html` for tables:
  <https://github.com/Unstructured-IO/unstructured/blob/main/unstructured/chunking/title.py>
  <https://github.com/Unstructured-IO/unstructured/blob/main/unstructured/partition/pdf.py>

The project already has per-format parsers, source locators, period-bound table
rows, quarantine for ambiguous tables, and cross-format PDF/XLSX/DOCX/CSV
FactLedger regressions. Therefore this sprint keeps the existing parser
boundary rather than adding a second production parser stack; the GitHub
patterns are used as validation criteria (preserve table structure, isolate
tables, retain headers/metadata), not as a claim that a replacement has been
installed.

The same frozen 2026-09-16 baseline was replayed again without overwriting v13
at `evaluation/results/offline_grounding_replay_20260918_v15`. It remains 100
historical answers, 341 citation records, zero Provider/evaluator calls, $0
cost, zero unsupported final numeric claims, and the unchanged historical
grades: 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED. Deterministic
required-fact parity remains 5/50 (010, 021, 036, 037, 046), not a semantic
equivalence score. The separate, earlier 2026-09-14 baseline is preserved at
`evaluation/results/offline_grounding_replay_20260918_v14` and is not directly
comparable (243 citations; 39/25/35/1 historical grades).

Verification after the follow-up:

```text
Focused format/retrieval/grounding regressions: 122 passed
Full offline pytest: 2406 passed, 23 skipped, 1 existing warning
ruff check .: All checks passed
git diff --check: PASS (only existing mixed-LF/CRLF working-copy warnings)
DeepSeek/provider/evaluator calls: 0
```

## 2026-09-18 follow-up: preserve annual periods in table evidence

An additional offline review found a period-labeling error in year-only table
columns. Tesla's FY2025 financial summary has columns 2021–2025, but the Fact
Ledger inferred the filing's Q4_2025 label for those annual values. That could
turn FY revenue ($94.827B) into an apparent Q4 result. The parser now represents
year columns as FY2021–FY2025; duration tables such as Apple's “Three Months
Ended” / “Six Months Ended” continue to map their columns to their verified
quarter and duration. When a filing-level quarter has no matching row-level
fact, required-fact planning prefers the matching annual period rather than
inventing a Q4 fact.

Regression coverage includes the real Tesla PDF summary, an annual table whose
parent document is labeled Q4/FY2025, a guard that the annual $94.827B value is
not exposed as Q4 revenue, quarter-duration controls, public hybrid retrieval
for English and Chinese two-company risk queries (both issuer-specific risk
chunks survive while higher-scoring generic forward-looking disclaimer chunks
do not consume either slot), and one equivalent Apple financial table ingested
from PDF/XLSX/DOCX/CSV through the public HybridRetriever entry point.

Focused offline verification after the annual-period repair:

```text
pytest tests/retrieval/test_period_aware_retrieval.py tests/evaluation/test_fact_ledger_row_grounding.py tests/test_hybrid_retrieval.py::test_public_retrieve_keeps_each_company_risk_and_excludes_disclaimer_slots tests/test_hybrid_retrieval.py::test_real_tesla_annual_summary_rows_are_not_labeled_as_q4_actuals tests/test_document_formats.py::test_equivalent_financial_table_values_match_across_supported_formats
plus Tesla Q4/FY comparison and public Q2-period retrieval regressions
51 passed, 1 existing Starlette/httpx deprecation warning
ruff check on touched files: PASS; git diff --check: PASS
DeepSeek/provider/evaluator calls: 0; cost: $0
```

This fixes a reproduced period/provenance error for year-only comparative
tables; it does not resolve the frozen historical answer grades or all citation
entailment / bilingual semantic disagreements. The 100-answer historical
semantic gate remains unregraded, and real-provider use remains prohibited.

## 2026-09-18 follow-up: bilingual evidence coverage regressions

The five differing bilingual coverage pairs in v23 are EN/ZH-010, 021, 036,
037, and 046. The replay is based on frozen answer/citation records and cannot
show current retrieval behavior. Focused provider-free regressions now exercise
the current path on the public Apple, Tesla, and NVIDIA PDFs:

- Pair 010: English and Chinese Q1 FY2027 margin questions retrieve the same
  reported NVIDIA margin evidence. Both finalizer outputs retain the supported
  74.9% claim, expose matching required-fact signatures, and reject Q2 FY2027
  outlook as Q1 actual.
- Pair 021: both languages retrieve Apple and Tesla partitions for a general
  financial comparison. With no period in the question, Apple evidence stays
  anchored to the Apple Q2 FY2026 filing and Tesla to its FY2025 annual table;
  when Q2 periods are explicitly requested, the context instead contains
  Tesla Q2 2025 values. The test deliberately does not treat an unspecified
  comparison as permission to silently select Tesla's older Q2 row.
- Pair 036: both chip-company aliases resolve to NVIDIA, and the public filing
  supplies Data Center revenue plus reported AI-factory/agentic-AI drivers for
  the corresponding English and Chinese causal queries.
- Pair 037: the existing public-PDF test verifies equivalent Apple facts for
  “iPhone maker” and its Chinese counterpart.
- Pair 046: the existing PDF-backed follow-up regression inherits Tesla and
  Q2 2025 from the prior user turn in both languages, keeps Tesla-only evidence,
  and finalizes both margin facts.

The confirmed public `HybridRetriever.retrieve` risk-comparison contract also
passes with local synthetic evidence: each named company retains one concrete
risk passage, while safe-harbor boilerplate cannot consume either evidence
slot. No Provider is used in any of these tests.

Focused verification:

```text
ALLOW_REAL_PROVIDER=false pytest -q [five bilingual/public retrieval and routing regressions]: 31 passed
ruff check tests/test_hybrid_retrieval.py: PASS
git diff --check: PASS (existing mixed-LF/CRLF warnings only)
DeepSeek/provider/evaluator calls: 0
```

These tests prove current offline retrieval/finalization behavior for the five
historical mismatch scenarios, not a semantic regrade of the frozen answers.
The 33 INCORRECT / 1 FAILED labels, the 46 citations still needing entailment
review, and human-reviewed bilingual answer equivalence remain unresolved.

This is an offline production-policy and parser-regression improvement, not a
semantic regrade. The historical 33 INCORRECT, 1 FAILED, 19 bilingual grade
disagreements, and 46 integrity-checked same-provider
`VALID_BUT_NOT_SUPPORTED` reviews remain unresolved. The earlier count of 223
is not a defensible count of 223 proven entailment failures. Revalidation split
those original labels into 122 not referenced by an answer citation marker,
55 annotation-integrity failures now indeterminate, and 46 still labeled
unsupported after integrity validation. Across all 341 records, 127 were
unused retrieved context and 74 were indeterminate. Do not enable DeepSeek or
run another live evaluation until the remaining offline semantic review and
targeted fixes are complete and explicitly accepted.

## 2026-09-18 follow-up: bilingual scope, Tesla alias, and public retrieval

Inspection of the frozen 19 bilingual grade-disagreement pairs found two
reproducible routing asymmetries and one entity-resolution gap:

- EN/ZH-002 asked for Tesla Q2 revenue, but the Chinese phrase “营收表现如何”
  was classified as SUMMARY while the English equivalent was FACT. Explicitly
  scoped metric questions now retain FACT scope even when phrased as “how did it
  perform”; deliberate summary commands and company-level performance questions
  remain summaries.
- EN/ZH-009 used “main drivers of growth” in English and “主要驱动因素” in
  Chinese. The English wording previously fell through to FACT; both variants
  now classify as ANALYSIS.
- EN/ZH-035 referred to Tesla as “the EV maker” / “那家电动车公司”. The English
  alias existed, but the Chinese alias did not. Both “电动车公司” and
  “电动汽车公司” now resolve to Tesla without benchmark-ID-specific rules.

A provider-free `HybridRetriever.retrieve` regression now builds a local fake
vector/lexical store from the public `demo/documents/Tesla_sample.pdf`, then
runs both EN/ZH-035 phrasings through retrieval and the production
`finalize_grounded_answer` boundary. It verifies that the historical Q2 column
($22,496 million revenue) is found, Q4-only highlights do not displace it, and
an old refusal is completed from the retrieved Q2 evidence. A separate
citation-gate contract confirms that a stale document-period field cannot
override a conflicting explicit Q4 chunk period, while a comparative table
that includes Q2 remains eligible. The already-approved multi-company risk
test also passes through the public retriever: each company keeps its own risk
evidence and generic forward-looking disclaimers do not occupy the two result
slots.

These are architecture fixes, not new semantic grades. The non-overwriting
v17 offline replay (`evaluation/results/offline_grounding_replay_20260918_v17`)
processed the same frozen 100 answers and 341 citations with zero Provider or
evaluator calls and $0 cost. It still records the historical grades unchanged
(29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED), zero final unsupported
numeric claims, and 5/50 deterministic required-fact parity differences.
Historical grade mismatches are immutable inputs to this replay; the replay
does not re-grade semantic equivalence. Three of the 19 disagreeing pairs now
have explicit, passing routing/retrieval regression coverage, but the 19
historical grade disagreements as a whole remain open. The 33/1 semantic
quality totals and 46 integrity-checked unsupported-citation reviews also
remain open; this work does not claim they are cleared.

Final verification on the current worktree:

```text
ALLOW_REAL_PROVIDER=false pytest -q: 2412 passed, 23 skipped, 1 existing warning
ruff check .: All checks passed
git diff --check: PASS (Git emitted only existing mixed-LF/CRLF warnings)
ALLOW_REAL_PROVIDER in parent shell after tests: UNSET (default-disabled)
DeepSeek/provider/evaluator calls this turn: 0

## 2026-09-18 follow-up: answer-scope grounding for risk and segment summaries

The production `finalize_grounded_answer` boundary now applies a query-scope
projection before citation grounding:

- Risk-only questions no longer retain detached, merely same-filing financial
  metric claims (for example an appended total-revenue sentence). A financial
  metric remains eligible when the same claim explicitly connects it to a risk
  mechanism such as concentration, dependency, exposure, or liquidity. The
  check handles Chinese and English and splits sentence/semicolon clauses
  without breaking decimal values or moving citation markers to another claim.
- Broad business-segment summaries require only segment-level revenue facts
  actually present in the trusted ledger; they do not automatically request
  consolidated revenue, net income, EPS, or company-level margins. A supported
  segment fact can still replace an evidence-contradicted “no segment data”
  denial. Segment-level facts are not invented when absent.

Provider-free regressions cover risk comparisons, an evidence-supported
quantified risk link, Chinese risk-scope filtering, mixed segment/consolidated
claims in one line, and the existing public `HybridRetriever.retrieve`
multi-company risk path. The focused policy file passes 36 tests; the broader
scope/retrieval/grounding set passes 103 tests.

The non-overwriting v19 replay at
`evaluation/results/offline_grounding_replay_20260918_v19` still processed the
same 100 frozen answers and 341 citation records, with zero Provider/evaluator
calls and $0 cost. It reports zero unsupported final numeric claims, while
historical semantic grades remain 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1
FAILED and deterministic required-fact parity remains 5/50. A diagnostic exact
string check found 33 of the 46 integrity-checked
`VALID_BUT_NOT_SUPPORTED` answer-claim strings absent from the replayed final
answers, with 13 exact strings still present. This is only a string-presence
diagnostic: absence does not prove a paraphrase is semantically supported, and
presence does not replace a human entailment judgement. Therefore it does not
clear the remaining citation-entailment reviews.

This follow-up improves production answer scope, but does not claim to have
cleared the 33 historical incorrect grades, the 1 failed grade, all 46
integrity-checked citation reviews, or all 19 bilingual semantic grade
disagreements. No frozen expected answer/criteria were changed and no live
Provider was enabled.

Final verification for this follow-up:

```text
ALLOW_REAL_PROVIDER=false pytest -q: 2416 passed, 23 skipped, 1 existing warning
ruff check .: All checks passed
git diff --check: PASS (Git emitted only existing mixed-LF/CRLF working-copy warnings)
DeepSeek/provider/evaluator calls: 0
Docker/runtime changes: none
Git add/commit/push: none
```

## 2026-09-18 follow-up: causal-driver evidence must survive grounding

The P1.1/v20 offline replay exposed an answer-scope defect for causal driver
questions: a retrieved numeric segment fact could be deterministically
appended after a provider refusal, making a metric-only response look like an
answer to "why did this business grow?" Meanwhile, the citation evidence gate
filtered narrative driver passages because they do not carry the requested
financial metric label.

The retrieval and citation gates now share provider-free driver-intent
recognition. For a driver question, a passage explicitly classified as
management-driver or causal evidence may bypass only the metric-label filter;
issuer and requested-period checks remain mandatory. If the generated answer
does not use a cited driver passage, the production answer boundary may include
a short, visibly labeled original-source excerpt with its actual evidence
rank, and removes a contradictory driver-absence sentence. This prevents a
related number from standing in for the requested cause. Forward-looking
safe-harbor boilerplate, other-company evidence, and conflicting-period
passages are not eligible. Financial RAG and comparison prompt assets were
bumped to 2.4.1 to state the causal-answer contract.

The deterministic regression uses NVIDIA's public Q1 FY2027 PDF for both
English and Chinese causal questions, asserts retrieval includes the reported
AI-factory/agentic-AI commentary, and checks the final answer cites that
passage rather than presenting the $75.2B figure alone. The fixture also
contains wrong-company, wrong-period and safe-harbor distractors.

The non-overwriting v21 replay still processes 100 frozen historical answers
and 341 original citations with zero real Provider calls, zero evaluator calls,
and $0 cost. It continues to report the historical grades unchanged
(29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED), zero final unsupported
numeric claims, and 5/50 required-fact coverage parity differences. That
replay is citation-input-only: it does not re-run retrieval. Historical EN-036
and ZH-036 cited context does not contain the driver passage, so the replay
cannot demonstrate this retrieval-path repair for those old answers. The
current PDF-backed public-retrieval plus production-finalizer regression does
demonstrate it. Therefore the historic 33/1 semantic grades, all remaining
citation-entailment judgements, and the full bilingual semantic-equivalence
gate remain open; no real Provider was used to claim those issues are resolved.

Follow-up focused verification:

```text
pytest tests/test_citation_gate.py tests/evaluation/test_final_answer_policy.py tests/test_prompt_builder.py tests/test_hybrid_retrieval.py tests/test_query_enrichment.py: 144 passed
Growth-driver bilingual finalizer regression: PASS
NVIDIA public-PDF bilingual driver retrieval regression: PASS
Prompt 2.4.1 causal-answer contract regression: PASS
v21 replay: 100/100; real_provider_calls=0; evaluator_calls=0; api_cost_usd=0
```

## 2026-09-18 follow-up: external implementation patterns and public-retrieval risk coverage

The GitHub review found three relevant patterns in established open-source
projects. Docling's chunking guide makes table-header repetition explicit for
table chunks and warns that Markdown serialization may lose merged-cell
structure; it recommends HTML or structured export when that structure is
important. Unstructured's implementation history likewise treats tables as
special chunk elements rather than ordinary prose. LangChain's
`ParentDocumentRetriever` separates small retrieval units from the larger
parent context returned to answer generation. These are design references,
not claims that adopting a library alone guarantees financial-answer quality:

- [Docling: chunking and table header handling](https://github.com/docling-project/docling/blob/cea4b4500c0277684c98697ead406838081060c6/docs/concepts/chunking.md)
- [Docling: serialization and table-cell spans](https://github.com/docling-project/docling/blob/cea4b4500c0277684c98697ead406838081060c6/docs/concepts/serialization.md)
- [Unstructured: table-aware chunking change](https://github.com/Unstructured-IO/unstructured/blob/3376cc96a49521669f3b64028799db16ca76136f/CHANGELOG.md)
- [LangChain: ParentDocumentRetriever](https://github.com/langchain-ai/langchain/blob/3ecff312901725b6b81529eabc778d3d7dd46666/libs/langchain/langchain_classic/retrievers/parent_document_retriever.py)

Applied principle in this repository: normalize evidence before retrieval so
table rows carry their inherited headers, issuer, verified filing period,
section and source locator; keep row-sized retrieval units while retaining
enough parent/table context to interpret the values. Parser/layout metadata is
authoritative where verified; filename and incidental outlook dates are not.
This work does not switch parsers or claim support for arbitrary layouts just
because they share a file extension.

The user-approved regression exercises only the public
`HybridRetriever.retrieve` path with local synthetic evidence and a fake vector
store. It checks both English and Chinese Apple-vs-NVIDIA risk comparisons:
one relevant risk chunk per named company must survive, while safe-harbor
disclaimers must not occupy the final slots. It calls no Provider.

Focused verification:

```text
5 bilingual/company-coverage and output-scope tests: PASS
Real Provider / evaluator calls: 0
```

## 2026-09-18 follow-up: enumerated absence assertions

The frozen EN-021 answer contained a comma-enumerated statement that no Apple
cost/profit figures appeared in retrieved evidence. The production absence
detector previously required a short uninterrupted list and missed that
sentence, allowing it to retain an unrelated citation. The bilingual detector
now accepts bounded punctuation-rich lists and Chinese “没有出现 / 沒有出現”
wording; the sanitizer replaces the claim with a retrieval-scoped limitation
and strips its misleading evidence marker.

The new bilingual production-finalizer regression passes. A fresh non-overwrite
replay, `evaluation/results/offline_grounding_replay_20260918_v24/`, reprocessed
all 100 frozen raw answers and 341 citation inputs through the current
production grounding boundary: EN-021 no longer asserts the unsupported Apple
absence; unsupported final numeric claims remain 0; real Provider calls,
evaluator calls, and cost remain 0. The frozen semantic labels necessarily
remain 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED, and the deterministic
required-fact parity check remains 5/50. This replay therefore verifies this
specific sanitizer repair only; it is not a semantic regrade or a claim that
the four release blockers are resolved.

Regression verification for this change:

```text
ALLOW_REAL_PROVIDER=false focused retrieval/period/grounding suite: 143 passed
ALLOW_REAL_PROVIDER=false full pytest: 2442 passed, 23 skipped, 1 setup error
Isolated rerun of the sole setup error: 1 passed
Ruff on touched Python modules/tests: PASS
git diff --check: PASS (repository-wide mixed-LF/CRLF warnings only)
DeepSeek/provider/evaluator calls: 0
```

The full-suite setup error was `RuntimeError: can't start new thread` while
Starlette's TestClient attempted to create its portal thread after the full
suite had already started many test clients; the exact test passed alone. This
is recorded as a runner resource limit, not hidden or relabeled as a full-suite
PASS.
```

## 2026-09-18 follow-up: absence claims must be retrieval-scoped

The frozen review still shows 33 INCORRECT and one FAILED answer, so those
historical grades are not cleared by sanitizer replay. The citation audit
provides a more precise diagnosis than the initial 223 count:

- Of 223 historical `VALID_BUT_NOT_SUPPORTED` labels, offline annotation
  integrity validation reclassifies 122 as unused retrieved context (their
  evidence rank is not cited in the answer), 55 as indeterminate because the
  citation annotation is incomplete or not attached to the claimed answer
  span, and 46 remain structurally valid but still require substantive
  claim-to-source review.
- The production API projects citations from the final sanitized answer's
  surviving `[Evidence N]` markers, rather than returning every retrieved
  chunk as if it supported a response. This excludes unused-context records
  from the user-visible citation list. It does not by itself prove semantic
  entailment for the 46 remaining reviews.

A separate recurring cause is a model turning “this top-k context did not
retrieve the requested item” into “the filing/report does not contain it.” A
partial retrieval cannot establish document-wide absence. The production
finalizer now replaces unmatched absence assertions with a localized
retrieval limitation, strips citations that only pointed to unrelated
passages, and preserves the existing ledger completion when a matching
company/period/metric fact was actually retrieved. This is bilingual and does
not make any provider call.

The regression includes the historical Apple Services pattern: a retrieved
regulatory-risk passage cannot be cited to assert that Services results are
absent from the report. The final answer is explicitly limited to what the
retrieved passages establish. The finalizer still deterministically completes
facts from matching ledger rows, and a generic safe insufficiency refusal is
preserved when no fact is available.

The non-overwriting v23 replay at
`evaluation/results/offline_grounding_replay_20260918_v23` processed all 100
frozen answers and 341 original citation records with zero real Provider
calls, zero evaluator calls, and $0 cost. It continues to report zero
unsupported final numeric claims. Since it does not regenerate answers or
re-run retrieval, the frozen semantic grade counts remain 29 CORRECT / 37
PARTIAL / 33 INCORRECT / 1 FAILED, and deterministic bilingual required-fact
coverage still differs on 5/50 pairs. These metrics remain open; this replay
does not claim a semantic regrade.

Verification after this follow-up:

```text
ALLOW_REAL_PROVIDER=false pytest -q: 2437 passed, 23 skipped, 1 warning
ruff check .: All checks passed
git diff --check: PASS (existing mixed-LF/CRLF warnings only)
v23 offline replay: 100/100; real_provider_calls=0; evaluator_calls=0; api_cost_usd=0
DeepSeek/provider/evaluator calls: 0
```

## 2026-09-18 follow-up: verified table rows, metric units, and bilingual retrieval

The approved offline acceptance for multi-company risk questions now runs
through the public `HybridRetriever.retrieve` entry point with a fake vector
store. English and Chinese Apple/NVIDIA comparisons each retain one
company-matched concrete risk passage at `top_k=2`; high-scoring safe-harbor
disclaimers do not occupy either result slot. This does not require a Provider
or relax company partitioning.

The canonical Apple PDF exposed a separate production-path issue: parser-built
verified statement rows were present, but duplicated `unverified_table` text
could consume the limited fact-coverage slots ahead of those rows. Numeric
coverage dimensions now require a verified row binding; unverified chunks are
not removed from the candidate corpus or treated as authoritative facts. This
lets the selector reserve the actual revenue, net-income, gross-profit, and
diluted-EPS rows. The PDF labels its dollar-valued gross-profit line “Gross
margin”; the fact ledger now distinguishes that amount from true percentage
gross margin, and derives structured EPS only from the diluted EPS row (not
the nearby shares-used row). YoY cells are excluded when identifying the
metric row's unit type.

The same regression also found a stale refusal: a draft saying the retrieved
passages lacked all financial results survived after the finalizer appended
verified facts. That contradiction is now removed only for the exact
retrieval-limitation placeholder when supported required facts are present;
when no supported facts exist, the limitation remains. The canonical Apple
PDF test compares finalizer fact-plan coverage for English, English issuer
alias, and Chinese issuer alias, while asserting the key values and requested
language are preserved.

Verification after this follow-up:

```text
ALLOW_REAL_PROVIDER=false focused retrieval/document/fact-ledger/policy suite: 264 passed
ALLOW_REAL_PROVIDER=false full backend pytest: 2443 passed, 23 skipped
Ruff on touched Python modules/tests: PASS
git diff --check: PASS (repository-wide mixed-LF/CRLF warnings only)
Fresh non-overwriting v25 production-grounding replay: 100 answers / 341 citations
  final unsupported numeric claims: 0
  frozen grades unchanged: 29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED
  deterministic bilingual required-fact parity differences: 5 / 50
  real Provider calls: 0; evaluator calls: 0; cost: $0
DeepSeek/provider/evaluator calls: 0
```

These changes repair retrieval-slot selection and false table metric typing for
the covered formats and reports; they do not semantically re-grade the frozen
100Q answers, resolve the 33 INCORRECT / one FAILED labels, prove entailment
for the 46 citations still requiring substantive review, or close the five
bilingual fact-coverage differences. Those release-quality issues remain
open, and no live Provider run is authorized by this offline work.

## 2026-09-18 follow-up: parity triage and public implementation scan

The five v25 bilingual required-fact-coverage differences were checked against
the frozen query/setup data and existing current-path regressions. Three are
historical evidence-availability differences (the frozen Chinese NVIDIA driver
and Apple-summary rows have no citations, while their English counterparts do;
the NVIDIA margin pair has different historical answers). Current offline
regressions exercise both languages through `HybridRetriever.retrieve` and the
grounded finalizer for these query families. The Apple summary regression
asserts the same required-fact signature across English, issuer-description
English, and Chinese variants. This does not rewrite the historical inputs or
constitute a semantic re-grade.

EN-046 is a concrete historical context-contamination example: its setup turn
asks about Tesla Q2 2025, but the frozen English answer cites Apple Q2 2026
margin disclosures. The current runtime has a role-checked follow-up resolver,
passes persisted thread history to the agent, and has bilingual offline tests
that assert Tesla/company and Q2-period preservation through retrieval. The
frozen replay only has the old citations, so it cannot prove a fresh production
retrieval after the fix; the saved bad answer remains a historical regression
fixture, not evidence that the current runtime still returns Apple.

A read-only scan of public GitHub implementations found two applicable design
patterns:

- [Docling](https://github.com/docling-project/docling) represents tables as
  structured `TableItem`s and supports exporting them to data frames or
  Markdown, rather than flattening all content into one undifferentiated text
  stream.
- [Unstructured's PDF partitioner](https://github.com/Unstructured-IO/unstructured/blob/3376cc96a49521669f3b64028799db16ca76136f/unstructured/partition/pdf.py)
  exposes high-resolution parsing and table-structure inference. Its
  [changelog](https://github.com/Unstructured-IO/unstructured/blob/3376cc96a49521669f3b64028799db16ca76136f/CHANGELOG.md)
  documents isolating table elements during chunking, adding table-structure
  evaluation helpers, and removing duplicate PDF text extraction from inside
  detected tables.

These references support the current architecture direction: preserve table
boundaries and page/row/column provenance, evaluate extracted table structure,
and prevent duplicate parser representations from competing for retrieval
slots. They are design references, not proof that any parser handles every
filing layout; the project's own PDF fixtures and format regressions remain the
acceptance evidence.

No additional code or provider call was made during this triage. The unresolved
historical semantic grades, 46 citation-entailment reviews, and frozen
cross-language differences remain release blockers; DeepSeek stays disabled.

## 2026-09-18 follow-up: issuer-scoped candidates and period-bound summaries

The approved synthetic multi-company risk acceptance was executed through the
public ``HybridRetriever.retrieve`` path. Local fake-vector results containing
Apple and NVIDIA safe-harbor disclaimers plus issuer-specific risk passages
confirm that English and Chinese comparisons keep both requested issuers'
concrete risks and do not spend either ``top_k=2`` slot on a generic disclaimer.
No Provider was called.

Two more causes were reproduced with the canonical Apple and Tesla PDFs:

- Comparative table cells often omit the issuer name in their text. A targeted
  lexical search such as ``Tesla net income`` over the entire tenant corpus
  then competed against all other issuers' frequent ``net income`` rows, and
  the Tesla row could fall outside the bounded candidate list before reranking.
  Targeted probes now use a metadata-scoped issuer corpus to augment candidates
  only; the final reranker still applies its normal company/evidence checks.
- Dense multi-metric summary chunks were appended after the large BM25 list and
  could be truncated by RRF before coverage selection. Verified issuer
  summaries are now kept inside the bounded candidate pool. For a broad,
  unqualified financial comparison, an explicit latest annual column is
  preferred when a filing provides one; explicit quarter requests continue to
  select their issuer-specific quarter instead.
- Chinese ``和`` / ``与`` / ``及`` connectors were not splitting company-period
  clauses, so a bilingual Apple-vs-Tesla query could not bind each quarter to
  its issuer. The clauses now bind independently.
- Metadata period strings such as ``Q2_FY2026`` did not match an otherwise
  identical request represented as ``Q2_2026`` in coverage selection, even
  when the document quarter independently confirmed the same quarter/year.
  Exact quarter/year matches now normalize only the optional fiscal marker;
  a different quarter or year remains a mismatch.
- A broad Apple financial summary could miss authoritative period-mapped
  revenue/net-income/gross-profit/EPS rows because the parser also emitted
  older flattened rows. Unverified rows remain quarantined; when a compact,
  verified multi-metric highlight is available it is preserved, otherwise the
  summary selector reserves the verified split statement rows.

Offline verification after these changes:

```text
pytest -q tests/test_hybrid_retrieval.py tests/retrieval/test_period_aware_retrieval.py tests/test_document_loader.py tests/test_document_formats.py tests/evaluation/test_answer_grounding_contract.py tests/evaluation/test_fact_ledger_row_grounding.py tests/evaluation/test_final_answer_policy.py tests/test_citation_gate.py
259 passed, 1 warning
ruff check on touched parser/retrieval/grounding modules and tests: PASS
git diff --check: PASS (mixed-LF/CRLF normalization warnings only)
DeepSeek/Provider/evaluator calls: 0; cost: $0
```

The test suite includes the real Apple/Tesla cross-report comparisons, Apple
quarterly statement summary, NVIDIA compact quarterly highlights, Chinese
company-period binding, and the approved English/Chinese multi-company risk
retrieval boundary. It is not a fresh 5Q/100Q semantic evaluation. The frozen
100Q answer grades, citation entailment review, and bilingual semantic parity
issues above remain unresolved release blockers; no expected answers or
historical artifacts were changed.

## 2026-09-18 follow-up: release-highlight parsing and bilingual comparison coverage

Inspection of the actual ``NVIDIA_sample.pdf`` found a parser false positive on
the first-page release highlights. PyMuPDF had concatenated several clearly
labelled claims into one block (Q1 revenue, Data Center revenue, year-over-year
growth, and capital-return announcements). Because the block contained several
numbers, the row heuristic labelled it ``unverified_table``; retrieval then
correctly quarantined it and consequently lost the valid ``$75.2 billion`` Data
Center fact. This was a parser classification defect, not absent source data.

The parser now recognizes long financial release prose with explicit reporting
or growth language as ``narrative`` evidence while giving explicit comparative
period columns precedence, so flattened statement rows remain quarantined. The
parser version is bumped to
``pymupdf-blocks-ocr-v16-financial-release-narrative`` so persisted indexes can
identify that their old chunk classification needs re-ingestion. A regression
parses the checked-in NVIDIA PDF, checks the chunk classification, and passes
the evidence through public ``HybridRetriever.retrieve`` with an isolated fake
store; the final context contains ``$75.2 billion`` and no
``unverified_table`` chunk.

A separate bilingual comparison diagnostic showed that Chinese broad
comparisons received a financial-summary BM25 hint while equivalent English
``financial performance`` comparisons did not. English now receives the same
structural hint. Broad comparison candidate expansion also retains
issuer-scoped, verified numeric rows for the comparison metrics before the
coverage-aware selector runs; this prevents bounded BM25 rankings from omitting
an issuer's gross-margin row. Regression coverage now checks English and
Chinese broad and period-specific Apple/Tesla comparisons for revenue, net
income, and gross-margin evidence for both issuers in the final context. It
does not add question-ID-specific routing or use filenames as period truth.

Focused current-source checks using the three checked-in Apple, NVIDIA, and
Tesla public PDFs and a fake embedding/store observed:

- NVIDIA Q1 FY2027 margin and data-center follow-ups: equal required-fact
  availability for English/Chinese; ``$75.2 billion`` is retained; no
  quarantined table reaches final retrieval context.
- Apple Q2 2026 summary and Tesla Q2 2025 margin follow-up: equal required-fact
  availability in English/Chinese.
- Broad Apple/Tesla comparison: with the full parser-derived issuer, period,
  metric, table-context, and provenance metadata, the current public retrieval
  path produces identical available required-fact sets for English and Chinese
  at ``top_k=8`` for both unqualified and explicitly period-scoped comparisons.
  Both contain revenue, net income, and gross margin for each issuer. A
  regression now asserts the full deterministic required-fact parity, not only
  those three visible core metrics.

These are current-source retrieval/coverage results with deterministic fake
embeddings, not regenerated model answers or human semantic grades. The frozen
historical 33 ``INCORRECT``, 1 ``FAILED``, 46 citation-entailment cases still
needing substantive review, and 19 historical English/Chinese answer-grade
disagreements remain open. The frozen offline production-policy replay also
remains a policy replay, not a re-grade. No DeepSeek, Provider, or evaluator
call was made. A parser-version bump means currently indexed PDFs need a
controlled re-ingestion before a running instance can benefit; this change
does not mutate the existing vector database.

Verification after the v16 parser and comparison-candidate changes:

```text
Provider-disabled full backend suite: 2457 passed, 23 skipped, 1 warning
Focused parser/retrieval/query-enrichment suite: 130 passed, 1 warning
Ruff on touched Python modules/tests: PASS
git diff --check: PASS (Git emitted only existing mixed-LF/CRLF notices)
DeepSeek/provider/evaluator calls: 0
```
