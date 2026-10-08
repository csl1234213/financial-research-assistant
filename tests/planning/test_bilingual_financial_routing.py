"""Natural-language regression cases from the real failed evaluation Smoke."""

import pytest

from agent.planning import PlanningContext, TaskAnalyzer, TaskType
from agent.planning.entity_extractor import extract_companies
from core.intent_analyzer import IntentAnalyzer


@pytest.mark.parametrize(
    "question",
    [
        "Summarize Tesla's financial performance in Q2 2025.",
        "Summarize NVIDIA's financial performance in Q1 FY2027.",
        "How did Apple's Services business perform in Q2 2026?",
        "哪些因素影响了特斯拉 2025 年第二季度的汽车业务？",
        "苹果的服务相关业务表现如何？",
        "那个做 iPhone 的公司 2026 年二季度业绩怎么样？",
        "Tell me about NVDA's datacentre performance.",
    ],
)
def test_company_financial_question_uses_retrieval_task(question):
    result = TaskAnalyzer().analyze(PlanningContext(question=question))
    assert result.task.task_type == TaskType.DOCUMENT_QA
    assert result.extracted_entities


def test_implicit_iphone_company_alias_uses_runtime_retrieval_route():
    question = "那个做 iPhone 的公司 2026 年二季度业绩怎么样？"

    result = IntentAnalyzer().analyze(question)

    assert result["intent"] == "SINGLE_COMPANY"
    assert result["companies"] == ["Apple"]


def test_ev_maker_company_alias_is_consistent_across_english_and_chinese():
    assert extract_companies("How did the EV maker perform financially in Q2 2025?") == ["Tesla"]
    assert extract_companies("那家电动车公司 2025 年第二季度经营情况如何？") == ["Tesla"]


def test_gpu_company_alias_is_consistent_across_english_and_chinese():
    assert extract_companies("What drove the GPU company data-center business?") == ["NVIDIA"]
    assert extract_companies("那家做 GPU 的公司在一季度数据中心业务为什么增长？") == ["NVIDIA"]


def test_iphone_company_alias_is_consistent_across_english_and_chinese():
    assert extract_companies("How was the iPhone maker doing financially?") == ["Apple"]
    assert extract_companies("那个做 iPhone 的公司业绩怎么样？") == ["Apple"]


@pytest.mark.parametrize(
    "question",
    [
        "Explain gross margin in simple terms.",
        "Explain the difference between revenue and profit.",
        "What is revenue?",
        "What is an iPhone?",
        "用简单的话解释一下毛利率。",
        "解释一下营收和利润的区别。",
        "什么是毛利率？",
        "What is RAG?",
        "iPhone 是什么？",
    ],
)
def test_general_concept_does_not_retrieve_financial_reports(question):
    result = TaskAnalyzer().analyze(PlanningContext(question=question, companies=["Apple"]))
    assert result.task.task_type == TaskType.CHAT


@pytest.mark.parametrize(
    "question",
    [
        "什么叫毛利率？请用通俗的话解释。",
        "What does gross margin mean?",
        "What is an iPhone?",
    ],
)
def test_runtime_intent_router_keeps_general_finance_concepts_out_of_rag(question):
    """The legacy runtime router must agree with the planning router."""

    result = IntentAnalyzer().analyze(question)
    assert result["intent"] == "DIRECT_CHAT"
    assert result["companies"] is None


@pytest.mark.parametrize(
    "question",
    [
        "Explain Apple's gross margin in the uploaded report.",
        "What is Tesla's revenue in Q2 2025?",
        "请解释上传财报中的毛利率变化。",
        "What is the revenue in the uploaded document?",
    ],
)
def test_explicit_report_or_company_metric_keeps_retrieval(question):
    assert TaskAnalyzer().analyze(PlanningContext(question=question)).task.task_type == TaskType.DOCUMENT_QA


@pytest.mark.parametrize(
    "question",
    [
        "2025年直销和批发代理模式的收入分别是多少？各自同比如何变化？",
        "贵州茅台2025年度财务报表由哪家会计师事务所审计？审计意见是什么？",
    ],
)
def test_moutai_revenue_channel_and_audit_questions_use_document_qa(question):
    result = TaskAnalyzer().analyze(
        PlanningContext(question=question, companies=["贵州茅台"])
    )
    assert result.task.task_type == TaskType.DOCUMENT_QA


def test_legacy_intent_router_uses_api_company_context_for_financial_question():
    result = IntentAnalyzer().analyze(
        "2025年直销和批发代理模式的收入分别是多少？各自同比如何变化？",
        company_context="贵州茅台",
    )
    assert result["intent"] == "SINGLE_COMPANY"
    assert result["companies"] == ["贵州茅台"]


def test_api_company_context_does_not_turn_general_concept_into_rag():
    result = IntentAnalyzer().analyze(
        "什么叫毛利率？", company_context="贵州茅台"
    )
    assert result["intent"] == "DIRECT_CHAT"
    assert result["companies"] is None
