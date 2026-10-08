# Local Qwen3.8 10Q quality diagnostic — 2026-09-25

## Scope

This is a local Ollama diagnostic, not a paid-provider release gate. It used
the same frozen ten-question selection as the DeepSeek smoke, the current
retrieval audit, production prompt builders, and the production grounding
policy. It called only:

`srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`

No DeepSeek call, evaluator call, or network Provider call was made.

## Runtime and grounding

- Cases: 10/10
- Application success: 10/10
- Empty output: 0
- Truncated output: 0
- Final unsupported numeric claims: 0
- Raw unsupported claims removed by policy: 66
- Total measured model latency: about 573.1 seconds (9.6 minutes)

The zero final unsupported-numeric count proves the grounding policy removed or
refused unsupported numeric claims; it does not prove that every retained claim
used the intended period or answered the frozen criterion.

## Manual deterministic quality review

| Case | Grade | Finding |
|---|---|---|
| EN-002 | CORRECT | Tesla Q2 2025 revenue `$22,496m` retained. |
| EN-007 | CORRECT | NVIDIA Q1 FY2027 revenue, Data Center, margins and growth facts retained. |
| EN-019 | INCORRECT | Used Tesla Q4 2025 instead of the frozen Q2 2025 comparison basis. |
| ZH-044 | CORRECT | Clear concept explanation; no filing citations. |
| ZH-007 | PARTIAL | Core facts present, but one section reverses GAAP/non-GAAP EPS labels and later contradicts itself. |
| ZH-013 | CORRECT | Apple Q2 facts present; six-month cash flow is eventually labeled as cumulative. |
| EN-016 | CORRECT | Apple six-month operating cash flow correctly scoped. |
| ZH-008 | CORRECT | NVIDIA Data Center revenue and growth facts correct. |
| EN-033 | CORRECT | Microsoft/Azure request refused for missing evidence. |
| ZH-019 | INCORRECT | Used Tesla Q4 2025 and Q4 YoY comparison instead of the frozen Q2 basis. |

Manual total: **7 CORRECT / 1 PARTIAL / 2 INCORRECT**.

## Conclusion

Qwen3.8 is strong at citation-safe numeric projection and direct financial
fact extraction, but it is not yet reliable for period-sensitive
multi-company comparison or bilingual metric-label consistency. It should not
replace the release Provider for final quality claims without fixing the two
Tesla period cases and the NVIDIA EPS label contradiction.

Artifact directory:

`evaluation/results/local_ollama_qwen38_10q_20260925/`
