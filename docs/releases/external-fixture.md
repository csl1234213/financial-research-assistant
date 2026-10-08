# External full-report acceptance fixture

Ordinary unit/contract tests use synthetic fixtures. The full Narrative integration test additionally requires a controlled external report; a missing fixture is a failure, not a passing skip.

Set `FINANCIAL_RAG_TEST_PDF_PATH` to your local copy of the complete 143-page report. Do not place or commit the file inside this repository. The legacy `P2_2_ORIGINAL_REPORT` variable remains supported.

The qualified SHA256 is `474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288`. Source: [CNINFO original report](https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF). Qualification checks the cover issuer, page 8 listed-company business, and page 50 controlling-shareholder business; the latter must not authorize issuer claims.

Formal acceptance also requires `P23_ISOLATED_POSTGRES_URL`, pointing to an isolated database named `p23_upload_test` on `127.0.0.1`. Never point it at production. Tests create and remove uniquely named schemas. Real LLM calls remain disabled (`ALLOW_REAL_PROVIDER=false`).

Run the full-report test with `python -m pytest tests/test_rc1_candidate_narrative_delivery.py`. Run synthetic attribution and hostile-review regression with `python -m pytest tests/test_formal_evidence_subject.py`.
