# Financial RAG Assistant V8.1.0 — Bilingual Evaluation Report

## Environment

- Evaluation mode: authenticated browser session, real frontend requests
- Docker project: `financial-rag-prod`
- Backend health: HTTP 200
- Runtime version reported by health endpoint: `8.2.0`
- Provider errors: 0
- HTTP 429 / plan-limit errors: 0
- Code changes: none

## Conversation coverage

The authenticated conversation contains 120 completed user/assistant turns:

| Language | Completed turns | Responses containing citation markers |
|---|---:|---:|
| English | 60 | 53 |
| Chinese | 60 | 4 |
| Total | 120 | 57 |

The requested minimum of 50 English and 50 Chinese real turns is therefore covered by the current authenticated session history.

## Quality observations

- Direct-chat questions returned non-empty answers.
- RAG questions returned grounded answers when matching documents were available.
- No provider-configuration error, quota error, or 429 response appeared in the completed conversation set.
- The Chinese Tesla Q2 query correctly refused to invent unavailable Q2 figures and identified the missing evidence.
- Citation coverage is materially lower for Chinese turns and should be investigated separately; this report does not alter application behavior.

## Security

- No API keys, passwords, cookies, tokens, or private credentials are included.
- No code, Docker configuration, volumes, or database data were modified.

## Final status

**PARTIAL / PASS FOR EXECUTION COVERAGE** — 60 English and 60 Chinese real turns completed without provider or quota failures. Citation completeness is not uniform, and the deployed health endpoint reports 8.2.0 rather than the requested 8.1.0 label.
