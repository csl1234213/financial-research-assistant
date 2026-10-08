from decimal import Decimal

import pytest

from agent.reasoning_models import Evidence
from core.fact_ledger import FactLedger
from core.financial_table_rows import (
    FinancialTableRow,
    VerificationStatus,
    financial_table_rows_from_chunk,
    financial_table_rows_json,
)


def test_explicit_period_row_becomes_verified_only_with_complete_dimensions():
    rows = financial_table_rows_from_chunk(
        content=(
            "Structured financial table row — Metric: Revenue | FY2025: 100.25 CNY "
            "| FY2024: 90.00 CNY"
        ),
        content_type="table",
        document_id="tenant_7_document_42",
        company="Example issuer",
        section="Consolidated statement of operations",
        table_context="Consolidated statement of operations; Unit: 元; Currency: CNY",
        page=12,
        source="annual_report.pdf",
        source_locator="PDF page 12, table 1, row 3",
    )

    assert len(rows) == 2
    assert rows[0].verification_status == VerificationStatus.VERIFIED
    assert rows[0].eligible_for_deterministic_fact is True
    assert rows[0].canonical_metric == "revenue"
    assert rows[0].statement_type == "income_statement"
    assert rows[0].scope == "consolidated"
    assert rows[0].period == "FY2025"
    assert rows[0].value == Decimal("100.25")
    assert rows[0].currency == "CNY"


def test_balance_sheet_row_without_proven_columns_is_not_verified():
    row = FinancialTableRow.assess(
        document_id="doc-1",
        company="Example issuer",
        statement_type="balance_sheet",
        table_title="资产负债表",
        scope="consolidated",
        row_label="资产总计",
        canonical_metric=None,
        column_label=None,
        fiscal_year=None,
        period=None,
        value="1234",
        raw_value="1,234",
        unit="元",
        currency="CNY",
        source="annual_report.pdf",
        source_locator="PDF page 57",
        page=57,
        source_text="资产总计 1,234 1,100",
        column_binding_proven=False,
    )

    assert row.verification_status == VerificationStatus.UNVERIFIED
    assert row.eligible_for_deterministic_fact is False
    assert "row_column_binding_not_proven" in row.verification_reasons
    assert "period" in row.verification_reasons


def test_partial_row_can_be_serialized_but_is_not_fact_eligible():
    rows = financial_table_rows_from_chunk(
        content=(
            "Structured financial table row — Metric: Net Income Attributable to Shareholders "
            "| FY2025: 12.34 CNY | FY2024: 11.11 CNY"
        ),
        content_type="table",
        document_id="tenant_7_document_42",
        company="Example issuer",
        section="单位：元 币种：人民币",
        table_context="CNINFO annual summary; Comparative columns: FY2025 | FY2024; Currency: CNY",
        page=6,
        source="annual_report.pdf",
    )

    assert len(rows) == 2
    assert all(row.verification_status == VerificationStatus.PARTIAL for row in rows)
    assert all(row.eligible_for_deterministic_fact is False for row in rows)
    assert "statement_type" in rows[0].verification_reasons
    assert "scope" in rows[0].verification_reasons
    assert rows[0].canonical_metric is None
    serialized = financial_table_rows_json(rows)
    assert '"verification_status": "PARTIAL"' in serialized
    assert '"currency": "CNY"' in serialized


def test_unverified_table_text_is_not_guessed_into_rows():
    assert financial_table_rows_from_chunk(
        content="资产总计 303,834,844,021.44 299,000,000,000.00",
        content_type="unverified_table",
        document_id="doc-1",
        company="Example issuer",
        section="合并资产负债表",
        table_context="",
        page=57,
        source="annual_report.pdf",
    ) == ()


def test_verified_status_cannot_be_constructed_with_missing_provenance():
    with pytest.raises(ValueError, match="complete source dimensions"):
        FinancialTableRow(
            document_id="doc-1",
            company="Example issuer",
            statement_type="balance_sheet",
            table_title="资产负债表",
            scope="consolidated",
            row_label="total_assets",
            canonical_metric="total_assets",
            column_label="FY2025",
            fiscal_year=2025,
            period="FY2025",
            value=Decimal("100"),
            raw_value="100",
            unit="元",
            currency="CNY",
            source="annual_report.pdf",
            source_locator=None,
            page=1,
            source_text="Financial table row — Metric: total_assets | FY2025: 100",
            verification_status=VerificationStatus.VERIFIED,
            column_binding_proven=False,
        )


def test_unknown_scope_or_mismatched_period_cannot_be_verified():
    candidate = FinancialTableRow.assess(
        document_id="doc-1",
        company="Example issuer",
        statement_type="balance_sheet",
        table_title="Balance Sheet",
        scope="unknown",
        row_label="total_assets",
        canonical_metric="total_assets",
        column_label="FY2025",
        fiscal_year=2024,
        period="FY2025",
        value="100",
        raw_value="100 CNY",
        unit="元",
        currency="CNY",
        source="annual_report.pdf",
        source_locator="PDF page 12, table 1, row 2",
        page=12,
        source_text="Financial table row — Metric: total_assets | FY2025: 100 CNY",
        column_binding_proven=True,
    )

    assert candidate.verification_status == VerificationStatus.PARTIAL
    assert "scope_not_resolved" in candidate.verification_reasons
    assert "fiscal_year_period_mismatch" in candidate.verification_reasons
    assert candidate.eligible_for_deterministic_fact is False


def test_structural_verification_does_not_require_canonical_metric():
    row = FinancialTableRow.assess(
        document_id="doc-1",
        company="Example issuer",
        statement_type="balance_sheet",
        table_title="合并资产负债表",
        scope="consolidated",
        row_label="新准则科目",
        canonical_metric=None,
        column_label="2025 年12 月31 日",
        fiscal_year=2025,
        period="2025-12-31",
        value=Decimal("1234.50"),
        raw_value="1,234.50",
        unit="元",
        currency="CNY",
        source="annual_report.pdf",
        source_locator="PDF page 56, table 1, row 3, column 3",
        page=56,
        source_text="新准则科目 | 七、21 | 1,234.50 | 1,100.00",
        column_binding_proven=True,
        note_reference="七、21",
        source_region="PDF page 56; bbox=(100.0,200.0,300.0,220.0)",
        column_role="closing_balance",
    )

    assert row.verification_status == VerificationStatus.VERIFIED
    assert row.canonical_metric is None
    assert row.period == "2025-12-31"
    assert row.note_reference == "七、21"
    assert row.column_role == "closing_balance"
    assert row.value == Decimal("1234.50")


def test_fact_ledger_does_not_reparse_typed_partial_rows_as_legacy_facts():
    rows = financial_table_rows_from_chunk(
        content="Structured financial table row — Metric: Revenue | FY2025: 100 CNY",
        content_type="table",
        document_id="tenant_7_document_42",
        company="Example issuer",
        section="单位：元 币种：人民币",
        table_context="CNINFO annual summary; Comparative columns: FY2025; Currency: CNY",
        page=6,
        source="annual_report.pdf",
    )
    evidence = Evidence(
        content="Structured financial table row — Metric: Revenue | FY2025: 100 CNY",
        company="Example issuer",
        source="annual_report.pdf",
        metadata={
            "chunk_id": "summary-row",
            "content_type": "table",
            "quarter": "FY2025",
            "table_context": "CNINFO annual summary; Currency: CNY",
            "financial_table_rows_json": financial_table_rows_json(rows),
        },
    )

    ledger = FactLedger.from_evidence([evidence])

    assert rows[0].verification_status == VerificationStatus.PARTIAL
    assert ledger.facts == ()
