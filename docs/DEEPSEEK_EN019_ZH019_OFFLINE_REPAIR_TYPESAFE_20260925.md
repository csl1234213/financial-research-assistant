# EN-019 / ZH-019 offline period-binding repair

Date: 2026-09-25

## Scope and safety

This repair is offline-only. It made no DeepSeek, evaluator, or other paid
provider calls, and it did not change the API contract or delete data. The
Docker backend and worker were rebuilt with `ALLOW_REAL_PROVIDER=false`.

## Reproduced defect

The two real DeepSeek requests completed with HTTP 200 but selected Q4 values:

- Tesla Q4 revenue (`$24.901B` / `$25.707B` depending on the answer clause)
- NVIDIA Q4 FY2026 revenue (`$68.127B`)

The current public Tesla chunk is a Q4/FY2025 update whose comparative table
contains a validated Q2 2025 column. Its document-level `quarter=Q4_2025`
metadata was being used as the default comparison period. NVIDIA's table also
contains a Q4 comparison column. The old quarter-label intersection therefore
treated Tesla Q4 and NVIDIA Q4 as a comparable pair, even though they are
different reporting years and the frozen comparison contract requires Tesla
Q2 2025 and NVIDIA Q1 FY2027.

## Repair

1. `FinancialFact` now retains the stable ingestion `document_id` separately
   from content-derived reporting period metadata.
2. Unqualified cross-company comparisons use a document-identity period only
   when that period is independently present in the document's extracted
   printed facts. A filename or unchecked id cannot create a fact period.
3. Quarter alignment now requires all issuers' own reporting quarters to agree.
   A single unambiguous shared historical quarter remains supported; multiple
   historical overlaps fail closed instead of selecting an arbitrary column.
4. Smoke evidence diagnostics preserve `document_id` for provenance auditing.

The live Chroma evidence was rechecked through the patched backend without a
provider call. The required plan is now:

```text
Tesla  revenue  Q2_2025
NVIDIA revenue  Q1_FY2027
```

## TypeSafe review

The local typed citation boundary (`core/typesafe_citation.py`) was reviewed
using the `typesafe-ai` skill principles: exact financial values, company,
period, and metric remain deterministic code-owned checks; ambiguous
qualitative overlap returns `REVIEW` rather than being promoted to support.

Offline checks returned:

```text
Tesla Q2 numeric claim       SUPPORTS / ACCEPT
NVIDIA Q1 numeric claim     SUPPORTS / ACCEPT
Tesla Q2 claim vs Q4 source  CONTRADICTS / REJECT
```

No TypeSafe service call or credential was required.

## Validation

```text
Focused tests: 195 passed
Ruff: PASS
git diff --check: PASS
Docker backend: healthy
Docker agent-worker: healthy
/api/v1/health: 200
/api/v1/ready: 200
ALLOW_REAL_PROVIDER: false
```

The previous DeepSeek pair result remains historical evidence of the defect;
it was not overwritten. A new real-provider test is intentionally not part of
this offline repair.

## Changed files

- `core/fact_ledger.py`
- `core/required_fact_plan.py`
- `core/core_engine.py`
- `tests/evaluation/test_p1_4_evidence_first.py`
