from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from agent.reasoning_models import Evidence
from core.fact_ledger import FactLedger
from core.financial_facts import (
    EligibilityStatus,
    FinancialDocumentContext,
    FinancialFactEligibilityGate,
    FinancialFactFactory,
    FinancialFactRepository,
    StructuredFinancialFactRetrieval,
    accounting_equation_audit,
    cash_flow_sanity_audit,
    financial_facts_from_rows,
)
from core.financial_metric_registry import MetricMappingStatus, normalize_financial_table_row
from core.financial_table_rows import VerificationStatus, financial_table_rows_json
from document_loader import parse_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "moutai-standard-statements-2025.pdf"
CONTEXT = FinancialDocumentContext(
    company_id="moutai",
    company_name="贵州茅台酒股份有限公司",
    accounting_standard="CAS",
    accounting_standard_source="2025 annual report, accounting policy, PDF page 53",
    fiscal_year_start="2025-01-01",
    fiscal_year_end="2025-12-31",
    fiscal_calendar_source="2025 annual report, fiscal year policy, PDF page 72",
)


@pytest.fixture(scope="module")
def moutai_rows():
    return parse_pdf(FIXTURE, ocr_enabled=False, document_id="moutai-fixture-2025").financial_table_rows


def _eligible_row(rows, label_fragment: str, statement: str, *, scope="consolidated"):
    row = next(
        row
        for row in rows
        if row.verification_status == VerificationStatus.VERIFIED
        and row.statement_type == statement
        and row.scope == scope
        and label_fragment in (row.row_label or "").replace(" ", "")
        and (row.period == "2025-12-31" or row.period == "FY2025")
    )
    mapped = normalize_financial_table_row(row)
    assert mapped.mapping_status in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}
    return row, mapped


def test_real_moutai_rows_generate_auditable_deterministic_facts(moutai_rows):
    verified = [row for row in moutai_rows if row.verification_status == VerificationStatus.VERIFIED]
    facts = financial_facts_from_rows(verified, context=CONTEXT)
    assert len(verified) == 595
    assert len(facts) == 98
    assert all(fact.source_kind == "FINANCIAL_STATEMENT" for fact in facts)
    assert all(fact.accounting_standard == "CAS" for fact in facts)
    assert all(fact.row_verification_status == "VERIFIED" for fact in facts)
    assert all(fact.page and fact.source_locator and fact.source_text for fact in facts)
    assert sum(fact.mapping_status == "EXACT" for fact in facts) == 58
    assert sum(fact.mapping_status == "SUPPORTED" for fact in facts) == 40
    assert sum(fact.statement_type == "balance_sheet" for fact in facts) == 36
    assert sum(fact.statement_type == "income_statement" for fact in facts) == 38
    assert sum(fact.statement_type == "cash_flow_statement" for fact in facts) == 24
    assert sum(fact.statement_type == "equity_statement" for fact in facts) == 0

    repository = FinancialFactRepository(facts)
    assert repository.conflicts == ()
    assert repository.duplicates == 0
    retrieval = StructuredFinancialFactRetrieval(repository)
    total_assets = retrieval.get_financial_fact(company="贵州茅台", metric="total_assets", fiscal_year=2025)
    assert len(total_assets.facts) == 1
    assert total_assets.facts[0].scope == "CONSOLIDATED"
    assert total_assets.facts[0].value == Decimal("303834844021.44")
    assert total_assets.facts[0].unit == "CNY_YUAN"
    assert total_assets.facts[0].period_type == "INSTANT"
    assert total_assets.facts[0].page == 57
    assert total_assets.facts[0].mapping_status == "EXACT"

    expected = {
        "cash_and_bank_balances",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "fixed_assets",
        "construction_in_progress",
        "revenue",
        "net_income",
        "attributable_net_income",
        "operating_cash_flow",
    }
    assert expected <= {fact.metric_id for fact in facts}
    duration = next(fact for fact in facts if fact.metric_id == "revenue" and fact.scope == "CONSOLIDATED")
    assert duration.period_type == "DURATION"
    assert duration.period_start == "2025-01-01"
    assert duration.period_end == "2025-12-31"
    comparative_beginning = next(
        fact
        for fact in facts
        if fact.metric_id == "cash_and_cash_equivalents_beginning"
        and fact.fiscal_year == "2024"
        and fact.scope == "CONSOLIDATED"
    )
    assert comparative_beginning.period_start == comparative_beginning.period_end == "2024-01-01"

    # Scope is part of fact identity: parent facts remain available separately.
    parent_total_assets = retrieval.get_financial_fact(
        company="贵州茅台", metric="total_assets", fiscal_year=2025, scope="PARENT_COMPANY"
    )
    assert len(parent_total_assets.facts) == 1
    assert parent_total_assets.facts[0].value == Decimal("195350142529.19")
    assert len(repository.find(company="贵州茅台", metric="total_assets", fiscal_year=2025, scope=None)) == 2
    assert not any(fact.metric_id == "total_debt" for fact in facts)
    assert not any(fact.metric_id == "cash_and_cash_equivalents" for fact in facts if fact.original_label == "货币资金")


def test_exact_supported_unmapped_partial_and_missing_dimensions(moutai_rows):
    gate = FinancialFactEligibilityGate()
    row, mapped = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    assert gate.assess(row, normalization=mapped, context=CONTEXT).status == EligibilityStatus.ELIGIBLE
    supported = next(
        (row, normalize_financial_table_row(row))
        for row in moutai_rows
        if row.verification_status == VerificationStatus.VERIFIED
        and normalize_financial_table_row(row).mapping_status == MetricMappingStatus.SUPPORTED
    )
    assert gate.assess(supported[0], normalization=supported[1], context=CONTEXT).status == EligibilityStatus.ELIGIBLE
    unmapped = next(
        row
        for row in moutai_rows
        if row.verification_status == VerificationStatus.VERIFIED
        and normalize_financial_table_row(row).mapping_status == MetricMappingStatus.UNMAPPED
    )
    assert "METRIC_UNMAPPED" in gate.assess(unmapped, context=CONTEXT).reasons
    partial = replace(
        row,
        verification_status=VerificationStatus.PARTIAL,
        verification_reasons=("synthetic partial candidate for gate coverage",),
        column_binding_proven=False,
    )
    assert "ROW_NOT_VERIFIED" in gate.assess(partial, context=CONTEXT).reasons
    incomplete = replace(
        row,
        verification_status=VerificationStatus.UNVERIFIED,
        verification_reasons=("incomplete",),
        column_binding_proven=False,
        scope=None,
    )
    assert "SCOPE_MISSING_OR_UNKNOWN" in gate.assess(incomplete, context=CONTEXT).reasons
    incomplete_unit = replace(incomplete, scope="consolidated", unit=None)
    assert "UNIT_MISSING" in gate.assess(incomplete_unit, context=CONTEXT).reasons
    incomplete_source = replace(incomplete, scope="consolidated", page=None)
    assert "SOURCE_PROVENANCE_INCOMPLETE" in gate.assess(incomplete_source, context=CONTEXT).reasons
    assert gate.assess(row, context=FinancialDocumentContext()).status == EligibilityStatus.ELIGIBLE

    mismatched_statement = replace(row, statement_type="cash_flow_statement")
    mismatch_decision = gate.assess(mismatched_statement, normalization=mapped, context=CONTEXT)
    assert "STATEMENT_TYPE_MISMATCH" in mismatch_decision.reasons

    flow_row, flow_mapping = _eligible_row(moutai_rows, "经营活动产生的现金流量净额", "cash_flow_statement")
    no_calendar = FinancialDocumentContext(company_id="moutai", company_name="贵州茅台")
    assert (
        "PERIOD_NOT_EXPLICITLY_CLASSIFIABLE"
        in gate.assess(flow_row, normalization=flow_mapping, context=no_calendar).reasons
    )


def test_decimal_conversion_and_unit_precision(moutai_rows):
    row, mapped = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    factory = FinancialFactFactory()
    fact = factory.create(row, context=CONTEXT, normalization=mapped)
    assert isinstance(fact.value, Decimal)
    assert fact.raw_value == "303,834,844,021.44"
    assert fact.source_unit == "元"
    assert fact.value == Decimal("303834844021.44")
    assert FinancialFactFactory().create(
        replace(row, value=Decimal("82.32"), raw_value="82.32", unit="亿元"),
        context=CONTEXT,
        normalization=mapped,
    ).value == Decimal("8232000000.00")
    for source_unit, expected in (
        ("千元", Decimal("1000")),
        ("万元", Decimal("10000")),
        ("百万元", Decimal("1000000")),
        ("亿元", Decimal("100000000")),
    ):
        converted = FinancialFactFactory().create(
            replace(row, value=Decimal("1"), raw_value="1", unit=source_unit),
            context=CONTEXT,
            normalization=mapped,
        )
        assert converted.value == expected


def test_repository_deduplicates_identical_facts_and_detects_conflicts(moutai_rows):
    row, mapped = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    fact = FinancialFactFactory().create(row, context=CONTEXT, normalization=mapped)
    duplicate = replace(fact, chunk_id="overlap-copy")
    repository = FinancialFactRepository([fact, duplicate])
    assert repository.duplicates == 1
    assert len(repository.duplicate_sources[fact.structured_identity]) == 2
    assert len(repository.facts) == 1
    conflict = replace(fact, value=fact.value + Decimal("1"), normalized_value=fact.value + Decimal("1"))
    conflicted = FinancialFactRepository([fact, conflict])
    assert conflicted.facts == ()
    assert len(conflicted.conflicts) == 1
    assert conflicted.conflicts[0].facts == (fact, conflict)
    ledger = FactLedger([fact, conflict])
    assert ledger.facts == ()
    assert len(ledger.conflicts) == 1


def test_factledger_consumes_typed_rows_without_relaxing_partial_table_safety(moutai_rows):
    row, _ = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    metadata = {
        "chunk_id": "indexed-balance-sheet-page-57",
        "content_type": "table",
        "financial_table_rows_json": financial_table_rows_json([row]),
        "accounting_standard": "CAS",
        "accounting_standard_source": CONTEXT.accounting_standard_source,
        "company_id": CONTEXT.company_id,
        "company_name": CONTEXT.company_name,
        "fiscal_year_start": CONTEXT.fiscal_year_start,
        "fiscal_year_end": CONTEXT.fiscal_year_end,
        "fiscal_calendar_source": CONTEXT.fiscal_calendar_source,
    }
    evidence = Evidence(content=row.source_text, source=row.source or "", company=row.company or "", metadata=metadata)
    ledger = FactLedger.from_evidence([evidence])
    assert len(ledger.facts) == 1
    assert ledger.facts[0].metric_id == "total_assets"
    assert ledger.facts[0].page == row.page
    assert ledger.facts[0].chunk_id == "indexed-balance-sheet-page-57"
    assert ledger.facts[0].source_locator == row.source_locator

    partial = replace(
        row,
        verification_status=VerificationStatus.PARTIAL,
        verification_reasons=("synthetic partial candidate for gate coverage",),
        column_binding_proven=False,
    )
    metadata["financial_table_rows_json"] = financial_table_rows_json([partial])
    assert FactLedger.from_evidence([Evidence(content=partial.source_text, metadata=metadata)]).facts == ()
    metadata["content_type"] = "unverified_table"
    metadata["financial_table_rows_json"] = financial_table_rows_json([row])
    assert FactLedger.from_evidence([Evidence(content=row.source_text, metadata=metadata)]).facts == ()
    metadata["content_type"] = "table"
    metadata["financial_table_rows_json"] = "not-json"
    assert FactLedger.from_evidence([Evidence(content=row.source_text, metadata=metadata)]).facts == ()


@pytest.mark.parametrize(
    ("label", "statement", "metric"),
    [
        ("货币资金", "balance_sheet", "cash_and_bank_balances"),
        ("资产总计", "balance_sheet", "total_assets"),
        ("负债合计", "balance_sheet", "total_liabilities"),
        ("营业收入", "income_statement", "revenue"),
        ("净利润", "income_statement", "net_income"),
        ("经营活动产生的现金流量净额", "cash_flow_statement", "operating_cash_flow"),
    ],
)
def test_real_moutai_core_statement_rows_keep_metric_and_citation_binding(
    moutai_rows, label, statement, metric
):
    row = next(
        row for row in moutai_rows
        if row.verification_status == VerificationStatus.VERIFIED
        and row.statement_type == statement
        and row.scope == "consolidated"
        and label in "".join(row.row_label.split())
        and normalize_financial_table_row(row).canonical_metric == metric
        and row.period in {"FY2025", "2025-12-31"}
    )
    evidence = Evidence(
        content=row.source_text,
        source=row.source or "",
        company=row.company or "",
        metadata={
            "chunk_id": f"indexed-statement-page-{row.page}",
            "content_type": "table",
            "financial_table_rows_json": financial_table_rows_json([row]),
            "company_id": CONTEXT.company_id,
            "company_name": CONTEXT.company_name,
            "accounting_standard": CONTEXT.accounting_standard,
            "accounting_standard_source": CONTEXT.accounting_standard_source,
            "fiscal_year_start": CONTEXT.fiscal_year_start,
            "fiscal_year_end": CONTEXT.fiscal_year_end,
            "fiscal_calendar_source": CONTEXT.fiscal_calendar_source,
        },
    )
    facts = FactLedger.from_evidence([evidence]).facts
    assert len(facts) == 1
    assert facts[0].metric_id == metric
    assert facts[0].chunk_id == f"indexed-statement-page-{row.page}"
    assert facts[0].source_locator == row.source_locator
    assert facts[0].scope == "CONSOLIDATED"


def test_factledger_prefers_structured_facts_and_does_not_reparse_them(moutai_rows):
    row, mapped = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    structured = FinancialFactFactory().create(row, context=CONTEXT, normalization=mapped)
    narrative = replace(structured, source_kind=None, structured_identity=None, chunk_id="narrative-window")
    ledger = FactLedger.from_financial_facts([narrative, structured])
    selected = ledger.lookup(company="moutai", metric_id="total_assets", period="2025-12-31")
    assert selected[0] == structured
    assert selected[0].source_kind == "FINANCIAL_STATEMENT"


def test_scope_and_standard_are_independent_dimensions_and_retrieval_is_deterministic(moutai_rows):
    consolidated, mapped = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    parent = next(
        row
        for row in moutai_rows
        if row.verification_status == VerificationStatus.VERIFIED
        and row.row_label
        and "资产总计" in row.row_label
        and row.scope == "parent"
        and row.period == "2025-12-31"
    )
    factory = FinancialFactFactory()
    con_fact = factory.create(consolidated, context=CONTEXT, normalization=mapped)
    parent_fact = factory.create(parent, context=CONTEXT)
    us_identity = list(con_fact.structured_identity)
    us_identity[2] = "US_GAAP"
    us_gaap = replace(con_fact, accounting_standard="US_GAAP", structured_identity=tuple(us_identity))
    repo = FinancialFactRepository([con_fact, parent_fact, us_gaap])
    assert len(repo.facts) == 3
    service = StructuredFinancialFactRetrieval(repo)
    default = service.get_financial_fact(company="moutai", metric="total_assets", fiscal_year=2025)
    assert default.selected_scope == "CONSOLIDATED"
    assert default.selection_reason == "preferred_scope:CONSOLIDATED"
    assert len(default.facts) == 2
    assert service.get_financial_fact(
        company="moutai", metric="total_assets", scope="CONSOLIDATED", accounting_standard="CAS"
    ).facts == (con_fact,)
    assert service.get_financial_fact(company="moutai", metric="total_assets", scope="PARENT_COMPANY").facts == (
        parent_fact,
    )
    assert len(repo.find(company="moutai", metric="total_assets", fiscal_year=2025, scope="CONSOLIDATED")) == 2

    # Similar liquidity labels retain their different accounting meanings.
    all_real_facts = financial_facts_from_rows(moutai_rows, context=CONTEXT)
    assert any(fact.metric_id == "cash_and_bank_balances" for fact in all_real_facts)
    assert any(fact.metric_id == "cash_and_cash_equivalents_ending" for fact in all_real_facts)
    assert "cash_and_bank_balances" != "cash_and_cash_equivalents_ending"


def test_reported_fact_audits_are_non_mutating_and_provenance_is_complete(moutai_rows):
    facts = financial_facts_from_rows(
        (row for row in moutai_rows if row.verification_status == VerificationStatus.VERIFIED), context=CONTEXT
    )
    equation = accounting_equation_audit(facts)
    assert equation and all(item["status"] == "PASS" for item in equation)
    cash = cash_flow_sanity_audit(facts)
    assert cash and all(item["status"] == "PASS" for item in cash)
    assert all(fact.source_text in fact.evidence_text for fact in facts)
    assert all(fact.source_locator in fact.provenance["source_locator"] for fact in facts)


def test_conflicting_identity_is_excluded_from_deterministic_retrieval(moutai_rows):
    row, mapped = _eligible_row(moutai_rows, "资产总计", "balance_sheet")
    fact = FinancialFactFactory().create(row, context=CONTEXT, normalization=mapped)
    other = replace(fact, value=Decimal("1"), normalized_value=Decimal("1"))
    repository = FinancialFactRepository([fact, other])
    result = StructuredFinancialFactRetrieval(repository).get_financial_fact(
        company="moutai", metric="total_assets", fiscal_year=2025
    )
    assert result.facts == ()
    assert len(result.conflicts) == 1
