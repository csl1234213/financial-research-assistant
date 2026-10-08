# Official Filing Discovery

When a chat response has no citations but the planner identifies exactly one
company, the React client requests `POST /api/v1/knowledge/discover`. The
backend routes SEC issuers to SEC EDGAR and Chinese company names/A-share
tickers to 巨潮资讯 (CNINFO). SEC discovery downloads the newest matching
10-K or 10-Q. CNINFO discovery accepts only an exact A-share issuer match,
searches full Chinese annual reports, and downloads the newest report PDF.

The downloaded SEC HTML or CNINFO PDF is stored in the authenticated tenant's
upload volume and sent through the existing document task, embedding, and
Chroma pipeline. It is not injected directly into a chat response. The UI
reports the download/indexing status and the Knowledge page shows the
document, period, checksum, and official source link/provider.

For CNINFO, the downloaded PDF must have a valid PDF signature and a readable
“审计报告” section before it can be queued. This verifies that the annual
report contains an audit-report section; it does not grade the auditor's
opinion (for example, unqualified vs. qualified). Interim reports, annual
report summaries, English summaries, and ESG reports are excluded.

Security boundaries:

- SEC requests accept only `www.sec.gov` and `data.sec.gov` HTTPS hosts.
- CNINFO requests accept only `www.cninfo.com.cn` and
  `static.cninfo.com.cn` HTTPS hosts, including after redirects.
- SEC company names are resolved through the official SEC company index;
  ambiguous matches fail closed.
- A-share companies are resolved by exact company name or six-digit ticker;
  ambiguous/fuzzy matches and mismatched exchange suffixes fail closed.
- SEC accession numbers and filenames are allowlisted before URL creation.
- CNINFO announcement paths must match the expected dated PDF artifact format.
- Responses are size-bounded; CNINFO artifacts must be parseable PDFs with an
  audit-report section before tenant storage.
- The response and download are tenant-scoped and subject to the existing
  document quota.
- Duplicate company/content checks prevent repeated downloads.
- SEC traffic uses `SEC_USER_AGENT`, which operators should set to a
  descriptive application name and monitored contact before production use.

The mainland A-share path uses CNINFO as its primary official
discovery/download source. SSE, SZSE, and BSE issuer queries are routed by
market code where CNINFO's company metadata identifies the issuer as `A股`.
No arbitrary web search is performed and no report is downloaded from a
third-party finance portal. Reports are only downloaded when the chat's
existing no-citation company discovery flow calls the endpoint; the app does
not silently add a report during indexing or analysis.
