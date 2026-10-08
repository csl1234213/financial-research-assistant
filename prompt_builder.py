"""Versioned prompt rendering for direct chat and financial RAG workflows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from core.fact_ledger import canonical_metric_id
from core.query_scope import QueryScope, classify_query_scope
from prompts.registry import PromptDefinition, PromptRegistry

FINANCIAL_RAG_PROMPT_VERSION = "2.4.1"
FINANCIAL_COMPARE_PROMPT_VERSION = "2.4.1"
DIRECT_CHAT_PROMPT_VERSION = "1.0.0"

FINANCIAL_SYSTEM_PROMPT = "You are a professional financial analyst."

PROMPT_RULES = """
You are a professional financial analyst.

Rules:

1. Answer ONLY using information from the Evidence section.
2. Do NOT invent facts.
3. Do NOT use external knowledge.
4. Write the complete response in the same language as the QUESTION.
   Determine the response language from the QUESTION, not from the Evidence
   or conversation history.
   When the QUESTION is Chinese and the Evidence is English, translate the
   question and evidence into an internal English representation first,
   complete the evidence-grounded analysis in English, then translate only
   the final answer back to Chinese. Preserve every number, period, unit,
   company name, qualifier, and citation marker. Do not substitute facts from
   memory or from another language's conversation history.
5. If the Evidence does not contain enough information, state that clearly
   in the same language as the QUESTION.
6. When making a statement, cite the Evidence number.
7. Prefer supported numerical facts relevant to the QUESTION; do not add
   unrelated numbers merely because they appear in the Evidence.
8. Separate facts from interpretation.
9. Be concise and objective.
10. Keep evidence citation markers in this exact, language-independent format:
11. For flattened financial tables, align each value with its column header
    from left to right before calculating or describing a period change.
12. A trailing YoY value applies to the row's latest displayed period unless
    the Evidence explicitly maps it to another period.
13. Keep year-over-year and quarter-over-quarter comparisons distinct. Do not
    claim a YoY change for a requested period when its prior-year comparison
    value is absent from the Evidence.
14. Before drafting, build an internal evidence ledger for every requested
    financial fact: company, source document, reporting period, period
    duration, metric, value, unit/currency, accounting basis (GAAP or
    non-GAAP), result type (actual or guidance), and Evidence ID. Do not show
    this ledger unless the QUESTION asks for methodology.
15. Use the most specific period in the evidence: table-column header and row
    label take precedence over section heading, document title, and filename.
    A filename is never authoritative period evidence.
16. Keep reported actuals, outlook/guidance, estimates, and derived values
    separate. Never answer an actual-period question with an outlook value.
17. Distinguish reporting duration: three months, six months, quarter, fiscal
    year, and trailing/annual periods are not interchangeable. If a requested
    fact is only available for another duration, state that limit.
18. Preserve units and accounting basis. Normalize million/billion values only
    when the source unit is explicit, and label conversions. Do not merge GAAP
    and non-GAAP metrics or consolidated and segment metrics.
19. For a missing fact, write one concise evidence limitation and continue
    with supported requested facts. Do not repeat refusal text in multiple
    sections or append unrelated evidence analysis.
20. Any comparative financial table must include a visible header and identify
    the reporting period for every compared value in the same row. State the
    comparison basis (YoY or QoQ) explicitly; never output unlabeled adjacent
    amounts or infer the basis from a filename/document title.
21. Do not put a generic "insufficient evidence" sentence before or after
    supported figures. If only part of the requested comparison is supported,
    state exactly which period/basis is missing and keep that limitation
    separate from the supported fact.
22. For a why/driver question, answer with an explicitly cited causal or
    management-driver statement from the retrieved narrative. Do not substitute
    a related revenue/margin figure for the requested cause. If no such narrative
    is present, state that the causal evidence is unavailable; do not infer a
    cause from correlation or a safe-harbor disclaimer.

[Evidence 1]
[Evidence 2]

Never use:

(Evidence 1)
(Evidence 2)

Translate response headings when needed, but never translate or alter
[Evidence N] citation markers.
""".strip()

FINANCIAL_RAG_TEMPLATE = f"""
{PROMPT_RULES}

==================================================
CONVERSATION HISTORY
==================================================

{{history_text}}

==================================================
EVIDENCE
==================================================

{{context}}

==================================================
QUESTION
==================================================

{{question}}

==================================================
RESPONSE FORMAT
==================================================

{{response_format}}

==================================================

Requirements:

- Use ONLY the Evidence section.
- Never invent facts.
- Never use external knowledge.
- Write all response headings and prose in the same language as the QUESTION.
- For Chinese questions with English evidence, internally translate the
  question/evidence to English before reasoning, then translate the final
  answer to Chinese. Preserve figures, periods, units, entities, uncertainty,
  and citation markers exactly.
- Cite evidence numbers.
- Keep citation markers exactly as [Evidence N], regardless of response language.
- Prefer numerical facts that directly answer the QUESTION.
- If evidence is insufficient, state that clearly in the same language as
  the QUESTION.
- Before answering, reconcile the requested company, period, duration, metric,
  unit, accounting basis, and actual/guidance status against the Evidence.
- Prefer a table column explicitly labelled by the requested period over any
  document title or filename. Keep three-month and six-month values separate.
- Never use a later outlook/guidance row to answer an earlier reported period.
- Use one concise evidence-limitation sentence when a requested fact is absent;
  do not repeat the same refusal across sections.

==================================================

Answer:
""".strip()

FINANCIAL_COMPARE_TEMPLATE = """
You are a professional financial analyst.

Use ONLY the provided context.
If evidence is insufficient, state that clearly.
Do NOT invent facts.
Write the complete response in the same language as the QUESTION.
When evidence is insufficient, state that in the QUESTION's language.
When the QUESTION is Chinese and the evidence is English, translate the
 question and evidence into English before reasoning, then translate the
 final answer back to Chinese. Preserve every number, period, unit, company
 name, qualifier, and citation marker; never replace evidence with remembered
 facts.
Keep evidence citation markers exactly as [Evidence N].

==================================================
CONVERSATION HISTORY
==================================================

{history_text}

==================================================
QUESTION
==================================================

{question}

==================================================
RETRIEVED EVIDENCE
==================================================

{context}

==================================================

RESPONSE FORMAT

{response_format}

When the QUESTION is Chinese, translate every heading and section label into
Chinese. Use the company names requested by the QUESTION; never substitute
companies from a template or an unrelated evidence chunk.

==================================================
Rules
==================================================

1. Use ONLY evidence.
2. Compare the requested companies or periods on the requested dimensions.
3. Include only sections needed to answer the QUESTION and supported by evidence.
4. Reference evidence numbers.
5. Keep answers concise.
6. Do not invent risks.
7. State uncertainty explicitly.
8. Write all response headings and prose in the same language as the QUESTION.
9. Keep citation markers exactly as [Evidence N], regardless of response language.
10. Align flattened table values with their column headers from left to right.
11. Treat a trailing YoY value as applying to the latest displayed period unless
    the evidence explicitly maps it elsewhere.
12. Do not infer a YoY comparison when the corresponding prior-year value is absent.
13. Build an internal fact ledger before comparing: company, source document,
    period, duration, metric, value, unit/currency, GAAP/non-GAAP, actual/
    guidance, and Evidence ID.
14. For Tesla-style quarterly tables, select the exact requested column (for
    example Q2-2025), even when the document itself is titled Q4/FY2025.
15. For Apple-style statements, keep Three Months Ended and Six Months Ended
    columns separate; do not label six-month cash flow as quarterly cash flow.
16. For NVIDIA-style releases, keep current-quarter actuals separate from the
    next-quarter outlook; Q2 outlook is not Q1 actual.
17. Report only one concise limitation for missing evidence and do not repeat
    "insufficient evidence" in multiple sections.
18. For a why/driver question, answer with an explicitly cited causal or
    management-driver statement from the retrieved narrative. Do not substitute
    a related revenue/margin figure for the requested cause. If no such narrative
    is present, state that the causal evidence is unavailable; do not infer a
    cause from correlation or a safe-harbor disclaimer.
""".strip()

DIRECT_CHAT_TEMPLATE = """
CONVERSATION HISTORY

{history_text}

User: {question}

Assistant:
""".strip()

_PROMPT_DEFAULTS = {
    "financial_rag": FINANCIAL_RAG_PROMPT_VERSION,
    "financial_compare": FINANCIAL_COMPARE_PROMPT_VERSION,
    "direct_chat": DIRECT_CHAT_PROMPT_VERSION,
}

for _definition in (
    PromptDefinition(
        name="financial_rag",
        version=FINANCIAL_RAG_PROMPT_VERSION,
        content=FINANCIAL_RAG_TEMPLATE,
        system_prompt=FINANCIAL_SYSTEM_PROMPT,
        description="Evidence-grounded financial research response.",
        tags=("rag", "financial", "grounded"),
    ),
    PromptDefinition(
        name="financial_compare",
        version=FINANCIAL_COMPARE_PROMPT_VERSION,
        content=FINANCIAL_COMPARE_TEMPLATE,
        system_prompt=FINANCIAL_SYSTEM_PROMPT,
        description="Evidence-grounded financial comparison response.",
        tags=("rag", "comparison", "financial"),
    ),
    PromptDefinition(
        name="direct_chat",
        version=DIRECT_CHAT_PROMPT_VERSION,
        content=DIRECT_CHAT_TEMPLATE,
        system_prompt=FINANCIAL_SYSTEM_PROMPT,
        description="General assistant response without document retrieval.",
        tags=("direct", "chat"),
    ),
):
    PromptRegistry.register(_definition)


def get_prompt_metadata(
    name: str,
    version: str | None = None,
) -> dict[str, str]:
    return dict(PromptRegistry.metadata(name, version or _PROMPT_DEFAULTS[name]))


def get_prompt_system_prompt(
    name: str,
    version: str | None = None,
    *,
    response_language: str | None = None,
) -> str:
    definition = PromptRegistry.get(name, version or _PROMPT_DEFAULTS[name])
    system_prompt = definition.system_prompt
    if response_language == "zh-CN":
        return (
            f"{system_prompt}\n\n"
            "User-facing response language: Simplified Chinese. This is a system-level "
            "requirement and overrides the language of the question, evidence, or history. "
            "Use Chinese financial units such as 亿元人民币; keep citations unchanged."
        )
    if response_language == "en":
        return (
            f"{system_prompt}\n\n"
            "User-facing response language: English. This is a system-level requirement "
            "and overrides the language of the question, evidence, or history. Use English "
            "financial units such as CNY 82.32 billion; keep citations unchanged."
        )
    return system_prompt


def _format_history(history: Sequence[dict[str, Any]] | None) -> str:
    if not history:
        return ""

    if any("role" in item or "content" in item for item in history):
        lines: list[str] = []
        for item in history[-8:]:
            role = str(item.get("role", "user")).strip().lower()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                lines.append(f"{role.title()}: {content[:1500]}")
        return "\n".join(lines)

    return "\n".join(
        f"Q: {item.get('q', '')}\nA: {item.get('a', '')}"
        for item in history[-3:]
    )


def _financial_response_format(question: str, *, comparison: bool) -> str:
    """Budget the response from the request, never from retrieved side topics."""

    scope = classify_query_scope(question)
    has_metric = canonical_metric_id(question) is not None
    if comparison or scope == QueryScope.COMPARE:
        if has_metric:
            return """Focused financial comparison:
- Compare only the financial metrics explicitly requested in the QUESTION.
- Give each requested company's value with its company, reporting period,
  metric, unit/currency and supporting [Evidence N] citation.
- Keep periods explicit when the companies use different fiscal calendars.
- Add a difference, ratio or growth calculation only when requested; show
  the formula and cite both operands. Do not imply unlike periods are equal.
- End with a short conclusion answering the requested comparison.
- Do not add unrelated metrics, strategy, technology, risk, investment or
  outlook sections. An evidence chunk's other facts do not expand the task.
- If one requested fact is missing, identify that fact while preserving the
  supported comparison facts. Do not replace a missing fact with guidance."""
        return """Question-led comparison:
- Compare only the companies, periods and dimensions requested in the QUESTION.
- For an open-ended strategic comparison, possible dimensions include
  Business Strategy, AI Technology, Infrastructure, Competitive Advantages
  and Risks. These are optional: select only relevant, evidenced dimensions.
- Give each requested company's supporting [Evidence N] citations separately.
- Summarize supported similarities and differences. State limitations where
  they affect the requested comparison.
- Do not force a fixed section count or add an investment recommendation or
  future outlook unless the QUESTION requests it."""
    if scope == QueryScope.FACT or (scope == QueryScope.GENERAL_CONCEPT and has_metric):
        return """Direct financial answer:
- Answer only the requested metric or fact, with its company, reporting
  period, unit/currency and inline [Evidence N] citation.
- Include only the context needed to interpret that answer.
- Do not append a research report, unrelated metrics, risks or outlook.
- If the required fact is absent, name the missing fact clearly."""
    if scope == QueryScope.SUMMARY:
        return """Financial summary:
- Give a brief summary of the requested company and reporting period.
- Include a few supported headline facts with inline [Evidence N] citations.
- Keep component rows distinct from financial statement totals.
- Add other themes only when the QUESTION requests them; do not append
  speculative risks, outlook or investment recommendations."""
    if scope == QueryScope.RISK:
        return """Evidence-grounded risk answer:
- Address only the risks or challenges requested in the QUESTION.
- Separate disclosed facts from interpretations and cite [Evidence N].
- Do not add unrelated financial metrics or speculative recommendations."""
    if scope == QueryScope.ANALYSIS:
        return """Focused analysis:
- Start with a concise answer to the requested analytical question.
- Include only findings needed for that analysis, with [Evidence N] citations.
- Distinguish evidence, calculations and interpretations. Include limitations
  where they matter; do not require unrelated risk or outlook sections."""
    return """Concise explanation:
- Explain only the concept or issue requested in the QUESTION.
- Cite the supporting evidence and state any relevant evidence limitation.
- Do not expand into a company research report or unrelated numeric claims."""


def _render(
    name: str,
    *,
    version: str | None,
    question: str,
    history: Sequence[dict[str, Any]] | None = None,
    context: str = "",
    response_language: str | None = None,
) -> str:
    definition = PromptRegistry.get(name, version or _PROMPT_DEFAULTS[name])
    rendered = definition.content.format(
        question=question,
        context=context,
        history_text=_format_history(history),
        response_format=_financial_response_format(
            question, comparison=name == "financial_compare"
        ) if name != "direct_chat" else "",
    )
    if response_language not in {"en", "zh-CN"}:
        return rendered

    if response_language == "zh-CN":
        instruction = (
            "RESPONSE LANGUAGE OVERRIDE: Write all user-facing prose and headings in "
            "Simplified Chinese, regardless of the question or conversation language. "
            "Use Chinese financial number/currency conventions (for example, 823.20 亿元人民币). "
            "Keep source names and citation markers unchanged. This overrides conflicting "
            "language rules below.\n\n"
        )
        rendered = rendered.replace(
            "translate the final answer back to Chinese",
            "translate the final answer into Simplified Chinese",
        )
        rendered = rendered.replace(
            "translate every heading and section label into\nChinese",
            "write every heading and section label in Simplified Chinese",
        )
    else:
        instruction = (
            "RESPONSE LANGUAGE OVERRIDE: Write all user-facing prose and headings in "
            "English, regardless of the question or conversation language. Use English "
            "number/currency conventions (for example, CNY 82.32 billion). Keep source "
            "names and citation markers unchanged. This overrides conflicting language "
            "rules below.\n\n"
        )
        rendered = rendered.replace(
            "translate the final answer back to Chinese",
            "write the final answer in English",
        )
        rendered = rendered.replace(
            "translate every heading and section label into\nChinese",
            "write every heading and section label in English",
        )
    rendered = rendered.replace(
        "same language as the QUESTION",
        "selected response language",
    ).replace(
        "QUESTION's language",
        "selected response language",
    )
    return instruction + rendered


def build_prompt(
    question: str,
    context: str,
    history: Sequence[dict[str, Any]] | None = None,
    prompt_version: str | None = None,
    *,
    response_language: str | None = None,
) -> str:
    return _render(
        "financial_rag",
        version=prompt_version,
        question=question,
        context=context,
        history=history,
        response_language=response_language,
    )


def build_compare_prompt(
    question: str,
    context: str,
    prompt_version: str | None = None,
    *,
    history: Sequence[dict[str, Any]] | None = None,
    response_language: str | None = None,
) -> str:
    return _render(
        "financial_compare",
        version=prompt_version,
        question=question,
        context=context,
        history=history,
        response_language=response_language,
    )


def build_direct_chat_prompt(
    question: str,
    history: Sequence[dict[str, Any]] | None = None,
    prompt_version: str | None = None,
    *,
    response_language: str | None = None,
) -> str:
    return _render(
        "direct_chat",
        version=prompt_version,
        question=question,
        history=history,
        response_language=response_language,
    )
