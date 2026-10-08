# Financial RAG problem scope and validation boundaries

This note describes the document-analysis problems the project is built to address. It is a product-scope statement, not a market survey or a claim that every financial assistant has the same limitations.

## The problem

Financial reports mix narrative, tables, units, reporting periods, and consolidated or parent-company views. A plain-text RAG pipeline can lose the relationships among those fields when it extracts or chunks a PDF. A query can then fail even when the requested fact appears in the report. Retrieval may also find a plausible passage from the wrong period or scope, while a citation can point to a source that does not support the answer's exact claim.

These issues matter for everyday questions such as revenue comparisons, cash balances, liabilities, earnings, and financial-statement trends. Users should not need to know the exact row label before the system can search for a reported metric.

## What this project implements

The financial-data path separates several decisions that are often collapsed into one:

1. **Table structure:** reconstruct rows and columns with their period, unit, scope, page, and source location.
2. **Metric meaning:** map a row label through a deterministic registry. A structurally verified row is not automatically a semantically verified metric.
3. **Fact identity:** retain company, statement, period, reporting scope, currency, unit, and source provenance as separate dimensions.
4. **Persistence:** make ingestion idempotent and record conflicting values rather than silently replacing one observation with another.
5. **Query routing:** send supported structured financial questions to fact-aware retrieval, with period and scope constraints.
6. **Answer evidence:** preserve source references so the answer path can verify whether a claim is supported.

For Chinese reports, concepts that look similar in casual language remain distinct when accounting meaning differs. Examples include `货币资金` versus `现金及现金等价物`, `负债合计` versus `有息债务`, and `净利润` versus `归属于母公司所有者的净利润`.

## Validation boundary

The implementation has regression work based on a 2025 Guizhou Moutai annual-report sample and reconstructed standard financial statements. That is useful evidence for the tested document and cases; it is not proof of universal financial-report coverage. Other issuers, scans, unusual table layouts, footnotes, accounting standards, fiscal calendars, and bilingual equivalence need their own fixtures and acceptance checks.

The project does not guarantee investment conclusions, replace analyst review, or claim that every cited statement is correct merely because a citation exists. Coverage and answer quality depend on the source document, parser path, configured retrieval components, and selected language model. External providers may receive the question and retrieved context when enabled, and may incur usage charges.

## Related implementation notes

These phase notes are audit snapshots written during implementation. Their recorded status and deployment boundaries refer to the time of each audit; later commits may have resolved or superseded them.

- [P1.3: verified financial-statement row reconstruction](FINANCIAL_RAG_P1_3_TABLE_SEMANTIC_RECONSTRUCTION.md)
- [P1.4: canonical metric registry](FINANCIAL_RAG_P1_4_METRIC_REGISTRY.md)
- [P1.5: canonical financial fact layer](FINANCIAL_RAG_P1_5_FACT_LAYER.md)
- [P1.6: financial fact persistence](FINANCIAL_RAG_P1_6_FACT_PERSISTENCE.md)
