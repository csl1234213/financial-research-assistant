# EN-019 / ZH-019 offline repair and local Qwen3.8 validation

Date: 2026-09-25

## Scope

This validation is offline-only. It used the current local Chroma retrieval,
the production evidence-first context builder, the production grounding
sanitizer, and local Ollama model
`srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`. No DeepSeek, evaluator, or paid
provider request was made.

## Repair

For a comparison query that asks for revenue performance, the retriever now
promotes already-retrieved, verified structured total-revenue rows immediately
before reciprocal-rank fusion. The rule is language-independent and does not
hard-filter on filename or metadata. It ensures the Chinese query retains the
same authoritative Tesla table row as the English query.

The existing period-binding repair then validates the printed table period
against the stable document identity. The resulting required fact plan for
both queries is:

```text
Tesla  revenue  Q2_2025
NVIDIA revenue  Q1_FY2027
```

## Local Qwen3.8 results

Fresh retrieval and generation artifacts are in:

`evaluation/results/local_ollama_en019_zh019_qwen38_offline_fix_20260925_v3/`

| Case | Result | Core facts retained | Final unsupported numeric claims |
|---|---|---|---:|
| EN-019 | CORRECT | Tesla Q2 2025 = 22,496 million USD; NVIDIA Q1 FY2027 = 81,615 million USD | 0 |
| ZH-019 | CORRECT | Tesla Q2 2025 = 22,496 million USD; NVIDIA Q1 FY2027 = 81,615 million USD | 0 |

Measured local generation latency was 49.5s for EN-019 and 54.1s for ZH-019.
The raw model answers contained additional claims; the production sanitizer
removed unsupported lines while preserving both required company values.
Both final fact-plan statuses are answer-present. Citation mapping was checked
against the final evidence list: Tesla's claim cites Tesla_Q2_2025.pdf and
NVIDIA's claim cites NVIDIA_Q1_FY2027.pdf in both languages.

## TypeSafe review

The typed citation boundary was reviewed using the TypeSafe principles: keep
scope, period, metric, and numeric normalization deterministic in code; treat
ambiguous qualitative overlap as `REVIEW`; never promote a rejected citation.
The provider-free TypeSafe contract tests passed, including supported numeric,
wrong value, wrong period, wrong company, Chinese normalization, and sanitizer
integration cases.

## Verification

```text
pytest -q tests/test_typesafe_citation.py \
  tests/test_hybrid_retrieval.py::test_bilingual_revenue_comparison_promotes_period_mapped_table_rows \
  tests/evaluation/test_p1_4_evidence_first.py::test_compare_plan_uses_validated_document_identity_for_mismatched_filing_quarters
11 passed
ruff check (touched retrieval/ledger/plan files): PASS
git diff --check: PASS
Docker services: frontend, backend, agent-worker, postgres, redis, chromadb healthy
ALLOW_REAL_PROVIDER: false
```

No production volumes or database data were deleted. No commit or push was
performed.
