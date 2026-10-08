from __future__ import annotations

import hashlib
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from agent.agent_runtime import AgentRuntime
from core.financial_facts import (
    FinancialDocumentContext,
    financial_facts_from_rows,
)
from core.financial_metric_registry import (
    FINANCIAL_METRIC_REGISTRY,
    MetricMappingStatus,
    extract_explicit_fiscal_year,
)
from core.intent_analyzer import IntentAnalyzer
from core.persistent_financial_facts import SQLFinancialFactRepository
from core.structured_financial_query import (
    StructuredLookupStatus,
    lookup_persisted_financial_fact,
)
from document_loader import parse_pdf
from models.document import Document
from models.financial_fact import (
    FinancialFactConflictRecord,
    FinancialFactIngestionRun,
)
from models.tenant import Tenant
from storage.database import _import_models

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "moutai-standard-statements-2025.pdf"
CONTEXT = FinancialDocumentContext(
    company_id="moutai",
    company_name="贵州茅台酒股份有限公司",
    accounting_standard="CAS",
    accounting_standard_source="fixture: audited annual report accounting policy",
    fiscal_year_start="2025-01-01",
    fiscal_year_end="2025-12-31",
    fiscal_calendar_source="fixture: annual reporting period",
)


@pytest.fixture(scope="module")
def moutai_rows():
    return parse_pdf(FIXTURE, ocr_enabled=False, document_id="moutai-fixture-2025").financial_table_rows


@pytest.fixture
def persisted_moutai(tmp_path: Path, monkeypatch, moutai_rows):
    _import_models()
    database_path = tmp_path / "p1_7_financial_fact_shadow.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    with Session(engine, expire_on_commit=False) as session:
        tenant = Tenant(name="P1.7 shadow", slug=f"p1-7-{tmp_path.name}")
        session.add(tenant)
        session.flush()
        payload = FIXTURE.read_bytes()
        document = Document(
            tenant_id=tenant.id,
            filename="moutai-2025-audited-fixture.pdf",
            company="贵州茅台",
            report_type="Annual Report",
            period="FY2025",
            status="indexed",
            content_sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )
        session.add(document)
        session.commit()

        def build_facts(document_row: Document) -> tuple:
            rebound = (replace(row, document_id=str(document_row.id)) for row in moutai_rows)
            return financial_facts_from_rows(rebound, context=CONTEXT)

        def ingest(document_row: Document) -> tuple:
            facts = build_facts(document_row)
            repository = SQLFinancialFactRepository(session, tenant_id=tenant.id)
            verified_count = sum(row.verification_status.value == "VERIFIED" for row in moutai_rows)
            repository.save_batch(
                facts,
                document_id=str(document_row.id),
                rows_seen=verified_count,
                rows_verified=verified_count,
                rows_mapped=len(facts),
                facts_rejected=verified_count - len(facts),
            )
            return facts

        facts = ingest(document)
        yield {
            "engine": engine,
            "session_factory": lambda: Session(engine, expire_on_commit=False),
            "session": session,
            "tenant_id": tenant.id,
            "document": document,
            "facts": facts,
            "build_facts": build_facts,
            "ingest": ingest,
        }
    engine.dispose()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("贵州茅台2025年总资产是多少？", "total_assets"),
        ("贵州茅台2025年归母净利润是多少？", "attributable_net_income"),
        ("贵州茅台FY2025 operating cash flow是多少？", "operating_cash_flow"),
        ("Apple FY2025 total assets", "total_assets"),
    ],
)
def test_query_metric_resolution_uses_the_canonical_registry(query, expected):
    resolution = FINANCIAL_METRIC_REGISTRY.resolve_query_metric(query)
    assert resolution.canonical_metric == expected
    assert resolution.status in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}


def test_query_metric_resolution_refuses_multiple_metrics_and_semantic_collisions():
    for query in ["贵州茅台2025年总资产和总负债分别是多少？", "贵州茅台2025年营业收入和净利润是多少？"]:
        assert FINANCIAL_METRIC_REGISTRY.resolve_query_metric(query).status == MetricMappingStatus.AMBIGUOUS
        intent = IntentAnalyzer().analyze(query)
        assert intent["intent"] == "FINANCIAL_FACT_QUERY"
        assert intent["canonical_metric"] == ""
        assert intent["metric_resolution_status"] == "AMBIGUOUS"
    multiple = FINANCIAL_METRIC_REGISTRY.resolve_query_metric("2025 revenue and net income")
    debt = FINANCIAL_METRIC_REGISTRY.resolve_query_metric("贵州茅台2025年债务")
    parent_profit = FINANCIAL_METRIC_REGISTRY.resolve_query_metric("贵州茅台2025年归母净利润")
    assert multiple.status == MetricMappingStatus.AMBIGUOUS
    assert debt.status == MetricMappingStatus.UNMAPPED
    assert parent_profit.canonical_metric == "attributable_net_income"


def test_fiscal_year_parser_requires_one_unambiguous_year():
    assert extract_explicit_fiscal_year("贵州茅台 2025 年总资产") == "2025"
    assert extract_explicit_fiscal_year("FY2025 total assets") == "2025"
    assert extract_explicit_fiscal_year("FY2025 vs FY2024 revenue") is None


def test_intent_marks_only_precise_company_metric_period_queries():
    analyzer = IntentAnalyzer()
    precise = analyzer.analyze("贵州茅台2025年总资产是多少？")
    coarse = analyzer.analyze("贵州茅台有多少钱？")
    debt = analyzer.analyze("贵州茅台债务是多少？")
    scoped = analyzer.analyze("2025年总资产是多少？", company_context="贵州茅台")
    assert precise["intent"] == "FINANCIAL_FACT_QUERY"
    assert precise["canonical_metric"] == "total_assets"
    assert coarse["intent"] == "SINGLE_COMPANY"
    assert debt["intent"] == "FINANCIAL_FACT_QUERY"
    assert debt["query_metric_status"] == "UNSUPPORTED_METRIC"
    assert debt["canonical_metric"] == ""
    assert scoped["intent"] == "FINANCIAL_FACT_QUERY"
    assert scoped["companies"] == ["贵州茅台"]


def test_multiple_company_candidates_are_not_collapsed_to_the_first_company():
    result = IntentAnalyzer().analyze("Apple NVIDIA 2025 revenue", company_context="Apple")
    assert result["intent"] == "UNKNOWN"
    assert result["companies"] == ["Apple", "NVIDIA"]


@pytest.mark.parametrize(
    ("query", "metric", "semantics"),
    [
        ("贵州茅台2025年总资产是多少？", "total_assets", "point_in_time"),
        ("贵州茅台2025年负债合计是多少？", "total_liabilities", "point_in_time"),
        ("贵州茅台2025年货币资金是多少？", "cash_and_bank_balances", "point_in_time"),
        ("贵州茅台2025年固定资产是多少？", "fixed_assets", "point_in_time"),
        ("贵州茅台2025年净利润是多少？", "net_income", "duration"),
        ("贵州茅台2025年归母净利润是多少？", "attributable_net_income", "duration"),
        ("贵州茅台2025年经营活动现金流量净额是多少？", "operating_cash_flow", "duration"),
    ],
)
def test_shadow_persisted_moutai_facts_route_before_rag(
    persisted_moutai,
    monkeypatch,
    query,
    metric,
    semantics,
):
    from core import core_engine

    runtime = AgentRuntime(
        planner=None,
        executor=None,
        reasoner=None,
        retriever=None,
        intent_analyzer=IntentAnalyzer(),
        structured_fact_lookup=partial(
            lookup_persisted_financial_fact,
            session_factory=persisted_moutai["session_factory"],
        ),
    )
    monkeypatch.setattr(core_engine, "_get_runtime", lambda: runtime)
    monkeypatch.setattr(
        core_engine,
        "call_llm",
        lambda *args, **kwargs: pytest.fail("structured fact hit must not call an LLM"),
    )
    monkeypatch.setattr(
        core_engine,
        "_get_retriever",
        lambda: pytest.fail("structured fact hit must not initialize retrieval"),
    )

    result = core_engine.run_rag(query, tenant_id=persisted_moutai["tenant_id"], answer_language="zh-CN")
    trace = result.planning["structured_financial_query"]
    assert result.intent["intent"] == "FINANCIAL_FACT_QUERY"
    assert result.intent["canonical_metric"] == metric
    assert trace["structured_lookup_status"] == StructuredLookupStatus.FOUND.value
    assert trace["final_route"] == "STRUCTURED_FINANCIAL_FACT"
    assert trace["vector_calls"] == trace["bm25_calls"] == trace["rerank_calls"] == 0
    assert len(result.citations) == 1
    assert result.citations[0]["page"]
    assert result.citations[0]["source"] == persisted_moutai["document"].filename
    assert result.citations[0]["canonical_metric"] == metric
    assert "[1]" in result.report


def test_structured_lookup_ambiguity_conflict_scope_and_tenant_isolation(persisted_moutai):
    fixture = persisted_moutai
    session = fixture["session"]
    first_fact = next(fact for fact in fixture["facts"] if fact.metric_id == "total_assets" and fact.scope == "CONSOLIDATED")
    run = session.scalar(
        select(FinancialFactIngestionRun).where(
            FinancialFactIngestionRun.document_id == fixture["document"].id
        )
    )
    assert run is not None

    session.add(
        FinancialFactConflictRecord(
            run_id=run.run_id,
            tenant_id=fixture["tenant_id"],
            document_id=fixture["document"].id,
            document_version=fixture["document"].content_sha256,
            fact_id=first_fact.fact_id,
            identity=list(first_fact.structured_identity),
            existing_value=first_fact.normalized_value,
            incoming_value=first_fact.normalized_value + 1,
            existing_provenance={"page": first_fact.page},
            incoming_provenance={"page": first_fact.page},
        )
    )
    session.commit()
    conflict = lookup_persisted_financial_fact(
        query="贵州茅台2025年总资产是多少？",
        company="贵州茅台",
        canonical_metric="total_assets",
        fiscal_year="2025",
        period_semantics="point_in_time",
        tenant_id=fixture["tenant_id"],
        response_language="zh-CN",
        session_factory=fixture["session_factory"],
    )
    assert conflict.status == StructuredLookupStatus.CONFLICT
    assert not conflict.trace.get("financial_presentation")
    assert conflict.evidence == ()
    assert conflict.terminal is True
    assert conflict.trace["final_route"] == "STRUCTURED_SAFE_FAILURE"


def test_competing_document_versions_return_ambiguity_not_latest(persisted_moutai):
    fixture = persisted_moutai
    session = fixture["session"]
    duplicate = Document(
        tenant_id=fixture["tenant_id"],
        filename="moutai-2025-second-upload.pdf",
        company="贵州茅台",
        report_type="Annual Report",
        period="FY2025",
        status="indexed",
        content_sha256=hashlib.sha256(b"independent second document version").hexdigest(),
        byte_size=36,
    )
    session.add(duplicate)
    session.commit()
    fixture["ingest"](duplicate)

    result = lookup_persisted_financial_fact(
        query="贵州茅台2025年总资产是多少？",
        company="贵州茅台",
        canonical_metric="total_assets",
        fiscal_year="2025",
        period_semantics="point_in_time",
        tenant_id=fixture["tenant_id"],
        response_language="zh-CN",
        session_factory=fixture["session_factory"],
    )
    assert result.status == StructuredLookupStatus.AMBIGUOUS
    assert not result.trace.get("financial_presentation")
    assert result.evidence == ()
    assert result.trace["fallback_reason"] == "multiple_matching_facts_or_document_versions"
    assert result.terminal is True


def test_default_scope_does_not_substitute_parent_only_fact(persisted_moutai):
    fixture = persisted_moutai
    session = fixture["session"]
    tenant = Tenant(name="Parent-only tenant", slug=f"parent-only-{fixture['tenant_id']}")
    session.add(tenant)
    session.flush()
    payload = b"parent-only shadow source"
    document = Document(
        tenant_id=tenant.id,
        filename="moutai-parent-only.pdf",
        company="贵州茅台",
        report_type="Annual Report",
        period="FY2025",
        status="indexed",
        content_sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
    )
    session.add(document)
    session.commit()
    parent_fact = next(
        fact
        for fact in fixture["build_facts"](document)
        if fact.metric_id == "total_assets" and fact.scope == "PARENT_COMPANY"
    )
    SQLFinancialFactRepository(session, tenant_id=tenant.id).save_batch(
        [parent_fact],
        document_id=str(document.id),
    )

    result = lookup_persisted_financial_fact(
        query="贵州茅台2025年总资产是多少？",
        company="贵州茅台",
        canonical_metric="total_assets",
        fiscal_year="2025",
        period_semantics="point_in_time",
        tenant_id=tenant.id,
        response_language="zh-CN",
        session_factory=fixture["session_factory"],
    )
    assert result.status == StructuredLookupStatus.NOT_FOUND
    assert not result.trace.get("financial_presentation")
    assert result.evidence == ()
    assert result.terminal is True
    assert result.trace["fallback_reason"] == "consolidated_scope_missing_parent_only_exists"
    assert "母公司口径" in result.answer


def test_structured_lookup_returns_miss_without_cross_tenant_leak(persisted_moutai):
    fixture = persisted_moutai
    session = fixture["session"]
    other = Tenant(name="Other tenant", slug=f"other-{fixture['tenant_id']}")
    session.add(other)
    session.commit()

    result = lookup_persisted_financial_fact(
        query="贵州茅台2025年总资产是多少？",
        company="贵州茅台",
        canonical_metric="total_assets",
        fiscal_year="2025",
        period_semantics="point_in_time",
        tenant_id=other.id,
        response_language="zh-CN",
        session_factory=fixture["session_factory"],
    )
    assert result.status == StructuredLookupStatus.NOT_FOUND
    assert result.trace["fallback_reason"] == "no_matching_persisted_fact"
    assert not result.trace.get("financial_presentation")
    assert result.evidence == ()
    assert result.terminal is False


def test_unsupported_debt_query_never_maps_to_total_liabilities(persisted_moutai, monkeypatch):
    from core import core_engine

    runtime = AgentRuntime(
        planner=None,
        executor=None,
        reasoner=None,
        retriever=None,
        intent_analyzer=IntentAnalyzer(),
        structured_fact_lookup=partial(
            lookup_persisted_financial_fact,
            session_factory=persisted_moutai["session_factory"],
        ),
    )
    monkeypatch.setattr(core_engine, "_get_runtime", lambda: runtime)
    result = core_engine.run_rag(
        "贵州茅台债务是多少？",
        tenant_id=persisted_moutai["tenant_id"],
        answer_language="zh-CN",
    )
    assert result.intent["intent"] == "FINANCIAL_FACT_QUERY"
    assert result.intent["canonical_metric"] == ""
    assert result.execution["status"] == StructuredLookupStatus.UNSUPPORTED_METRIC.value
    assert "total_liabilities" not in result.report
    assert result.citations == []
