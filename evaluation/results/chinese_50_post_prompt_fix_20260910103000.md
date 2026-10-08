# Chinese 50-turn evaluation after evidence-language prompt fix

## Scope

- Runtime: authenticated Docker frontend session
- Test type: 50 new real Chinese questions
- No code or deployment configuration changed during the run

## Results

| Metric | Result |
|---|---:|
| Questions submitted | 50 |
| Completed responses | 50 |
| Provider configuration errors | 0 |
| HTTP 429 / quota errors | 0 |
| Responses still loading | 0 |
| Responses containing citation markers or source references | 37 |

## Evidence-language behavior

- Chinese answers were generated in Chinese even when retrieved evidence was in English.
- Numeric values, reporting periods, company names, units, and uncertainty statements were preserved in the sampled answers.
- When the knowledge base lacked the requested period or metric, the assistant stated that the evidence was insufficient instead of filling the gap from memory.
- English source filenames/content remain visible as provenance; they are not silently translated or replaced.

## Notable observations

- Some prompts intentionally requested facts that were absent from the current knowledge base. Those answers correctly returned an evidence-insufficient response.
- Citation presence varies by workflow response format: some answers use `[1]` markers while others expose an expanded citation section. Both were counted as citation references.

## Verification

- Prompt regression suite: `32 passed, 1 warning`
- No provider error, quota error, or unfinished response in this 50-turn run.
- No secrets, tokens, cookies, or credentials were written to the report.

## Status

**PASS** for the 50-turn Chinese post-fix execution and language-consistency checks. Citation coverage is 37/50 because several evidence-insufficient/general responses did not include a formal citation block.
