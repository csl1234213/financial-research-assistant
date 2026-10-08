# DeepSeek EN-019 / ZH-019 pair test — 2026-09-25

## Requests

1. `EN-019`: `Compare Tesla and NVIDIA revenue performance.`
2. `ZH-019`: `比较特斯拉和英伟达的营收表现。`

Both requests completed through `POST /api/v1/chat` with HTTP 200 and one
DeepSeek call each. No evaluator call was made.

## Results

| Case | DeepSeek answer | Assessment |
|---|---|---|
| EN-019 | Tesla Q4 2024 revenue `$25.707bn`; NVIDIA Q4 FY2026 revenue `$68.127bn` | INCORRECT for the frozen benchmark period basis |
| ZH-019 | Tesla Q4 2025 revenue `$24.901bn`; NVIDIA Q4 FY2026 revenue `$68.127bn` | INCORRECT for the frozen benchmark period basis |

The frozen criteria require the Tesla Q2 2025 historical column (`$22,496m`)
and the NVIDIA Q1 FY2027 actual (`$81.615bn`) for this comparison family. Both
answers cited the correct source files, but selected the wrong periods/columns.

This reproduces the same failure seen with local Qwen3.8, so the issue is not
specific to one LLM provider. It is a period-binding/prompt/evidence-selection
problem in the comparison workflow.

## Runtime and cost

- HTTP success: 2/2
- Application success: 2/2
- Provider errors: 0
- DeepSeek calls: 2
- Total measured cost: `$0.015824424`
- Evaluator cost: `$0`

## Safety closure

- `ALLOW_REAL_PROVIDER=false` restored.
- `/api/v1/health`: 200.
- `/api/v1/ready`: 200.
- Six Docker services healthy.
- No secrets or bearer tokens were written to the artifact.

Artifacts:

`evaluation/results/deepseek_pair_en019_zh019_20260925/results.json`

No commit or push was performed.
