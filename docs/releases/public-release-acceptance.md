# V1 public-release qualification

Application authority: `ce0b9c64890c81519be7e06df46847adc2043bd7`. Publication starts a new Git history; it neither rewrites the old repository nor changes production.

## Test results

| Release check | Passed | Failed | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Security, dispatch, formal ingestion/recovery, full-report Narrative, deployment | 202 | 0 | 0 | 2 |
| User/workspace isolation | 38 | 0 | 0 | 0 |
| Offline Answer contracts | 104 | 0 | 0 | 0 |
| Final Nginx and hostile/unknown-subject harness recheck | 60 | 0 | 0 | 1 |

The last row repeats previously run cases and adds two unknown-subject API/SSE cases; do not add all rows as a unique-test total.

The skipped cases are explicit: SQLite cannot qualify PostgreSQL row locks (the PostgreSQL case ran); the historical canonical-artifact replay needs separately supplied immutable artifacts. The latter skip appears in both the main run and the recheck. No new passing skip was introduced.

The initial run had 155 passed, 2 failed, 45 setup errors and 2 skipped. All 45 errors shared the missing isolated PostgreSQL fixture URL. The failures were a missing external full-report path and an obsolete static Nginx upstream assertion. Test setup/expectations were repaired; product routing was not reverted.

## Boundaries

Full-report acceptance used the external, hash-qualified 143-page report described in [fixture setup](external-fixture.md). Formal READY, issuer identity, real local embedding/Hybrid evidence, source PDF/page binding and deterministic generation/review passed for SQLite and isolated PostgreSQL. The report is not a release asset.

Hostile `SUPPORTED` reviews cannot release issuer claims supported by parent-group page 50 or unknown-subject evidence. API/SSE fail closed; valid page 8 issuer claims remain supported.

Ruff, Compose configuration and current-tree secret/data scans passed. Publication removes the retired JWT literal while retaining its rejection through a digest predicate; 352 old/new decisions matched. No other application runtime source changed. Developer-specific paths and raw test logs are excluded from the public tree. Only two audited synthetic security fixtures receive exact secret-scan fingerprints.

Live LLM Provider calls: **0**. Production changes: **0**. This is an offline release qualification, not a new model-quality, availability or long-term SLA claim.
