import re

from agent.reasoning_models import ReasoningResult

_CHINESE_CHARACTER = re.compile(r"[\u3400-\u9fff]")

_REPORT_LABELS = {
    "en": {
        "title": "Research Report",
        "question": "Question",
        "answer": "Answer (LLM Answer)",
        "agent_analysis": "Agent Evidence Analysis",
        "facts": "Key Facts",
        "risks": "Risk Signals",
        "opportunities": "Opportunity Signals",
        "conclusion": "AI Conclusion",
        "coverage": "Source Coverage",
        "chunks": "chunks",
    },
    "zh-CN": {
        "title": "研究报告",
        "question": "问题",
        "answer": "回答（LLM 模型回答）",
        "agent_analysis": "智能体证据分析",
        "facts": "关键事实",
        "risks": "风险信号",
        "opportunities": "机会信号",
        "conclusion": "AI 结论",
        "coverage": "来源覆盖",
        "chunks": "个文本块",
    },
}


def _labels_for_question(
    question: object,
    response_language: str | None = None,
) -> dict[str, str]:
    language = response_language or (
        "zh-CN" if _CHINESE_CHARACTER.search(str(question)) else "en"
    )
    return _REPORT_LABELS[language]


def build_research_report(
    question,
    answer,
    citations,
    evidence_stats,
    reasoning_result: ReasoningResult = None,
    *,
    response_language: str | None = None,
):
    labels = _labels_for_question(question, response_language)
    coverage_text = ""

    for source, count in evidence_stats.items():
        coverage_text += f"- {source}: {count} {labels['chunks']}\n"

    report = f"""
# {labels['title']}

## {labels['question']}
{question}

## {labels['answer']}
{answer}
"""

    report += f"""
## {labels['agent_analysis']}
"""

    if reasoning_result and reasoning_result.facts:
        report += f"""
## {labels['facts']}
"""
        for f in reasoning_result.facts:
            report += f"- {f}\n"

    if reasoning_result and reasoning_result.risks:
        report += f"""
## {labels['risks']}
"""
        for r in reasoning_result.risks:
            report += f"- {r}\n"

    if reasoning_result and reasoning_result.opportunities:
        report += f"""
## {labels['opportunities']}
"""
        for o in reasoning_result.opportunities:
            report += f"- {o}\n"

    if reasoning_result and reasoning_result.conclusion:
        report += f"""
## {labels['conclusion']}

{reasoning_result.conclusion}
"""

    report += f"""
## {labels['coverage']}
{coverage_text}
"""
    return report
