from decimal import Decimal
from pathlib import Path

import pytest

from core.financial_metric_registry import (
    FINANCIAL_METRIC_REGISTRY,
    MetricMappingStatus,
    normalize_financial_table_row,
    normalize_row_label,
)
from core.financial_table_rows import FinancialTableRow, VerificationStatus
from document_loader import parse_pdf


def _row(
    label: str,
    statement: str = "balance_sheet",
    *,
    scope: str = "consolidated",
    period: str = "FY2025",
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> FinancialTableRow:
    fiscal_year = int(period[2:6] if period.startswith("FY") else period[:4])
    return (
        FinancialTableRow.assess(
            document_id="registry-test-doc",
            company="示例公司",
            statement_type=statement,
            table_title=f"{statement} report",
            scope=scope,
            row_label=label,
            canonical_metric=None,
            column_label=period,
            fiscal_year=fiscal_year,
            period=period,
            value=Decimal("1"),
            raw_value="1",
            unit="元",
            currency="CNY",
            source="fixture.pdf",
            source_locator="page=1;table=1;row=1",
            page=1,
            source_text=label,
            column_binding_proven=True,
            source_row_detected=True,
        )
        if status == VerificationStatus.VERIFIED
        else FinancialTableRow(
            document_id="registry-test-doc",
            company="示例公司",
            statement_type=statement,
            table_title=f"{statement} report",
            scope=scope,
            row_label=label,
            canonical_metric=None,
            column_label=period,
            fiscal_year=2025,
            period=period,
            value=Decimal("1"),
            raw_value="1",
            unit="元",
            currency="CNY",
            source="fixture.pdf",
            source_locator="page=1;table=1;row=1",
            page=1,
            source_text=label,
            verification_status=status,
            column_binding_proven=False,
        )
    )


@pytest.mark.parametrize(
    ("label", "statement", "metric", "mapping_status"),
    [
        ("资产总计", "balance_sheet", "total_assets", MetricMappingStatus.EXACT),
        ("资产合计", "balance_sheet", "total_assets", MetricMappingStatus.SUPPORTED),
        ("固定资产", "balance_sheet", "fixed_assets", MetricMappingStatus.EXACT),
        ("Total assets", "balance_sheet", "total_assets", MetricMappingStatus.SUPPORTED),
        ("资产总计", "cash_flow_statement", None, MetricMappingStatus.UNMAPPED),
        ("经营活动产生的现金流量净额", "cash_flow_statement", "operating_cash_flow", MetricMappingStatus.EXACT),
    ],
)
def test_registry_resolves_contextual_exact_and_supported_aliases(
    label: str,
    statement: str,
    metric: str | None,
    mapping_status: MetricMappingStatus,
):
    result = normalize_financial_table_row(_row(label, statement))

    assert result.canonical_metric == metric
    assert result.mapping_status == mapping_status


def test_normalization_handles_unicode_format_noise_without_erasing_hierarchy():
    label = "　其中：营业收入［注 1］　"
    assert normalize_row_label(label) == "其中:营业收入[注1]"
    result = normalize_financial_table_row(_row(label, "income_statement"))
    assert result.canonical_metric == "revenue"
    assert result.mapping_status == MetricMappingStatus.SUPPORTED
    assert result.original_label == label
    assert result.normalized_label.startswith("其中:")


def test_safe_statement_ordinal_variant_is_supported_and_original_is_preserved():
    row = _row("三、营业利润", "income_statement")
    result = normalize_financial_table_row(row)

    assert result.canonical_metric == "operating_income"
    assert result.mapping_status == MetricMappingStatus.SUPPORTED
    assert result.original_label == "三、营业利润"
    assert result.normalized_label == "三、营业利润"


def test_statement_mismatch_fails_closed_even_when_alias_exists():
    result = normalize_financial_table_row(_row("资产总计", "cash_flow_statement"))

    assert result.canonical_metric is None
    assert result.mapping_status == MetricMappingStatus.UNMAPPED
    assert result.mapping_rule == "statement_type_mismatch"
    assert "total_assets" in result.mapping_evidence


def test_generic_cash_is_ambiguous_and_moutai_cash_is_not_cash_equivalents():
    generic = normalize_financial_table_row(_row("现金"))
    chinese_cash = normalize_financial_table_row(_row("货币资金"))
    cash_equivalents = normalize_financial_table_row(_row("现金及现金等价物"))

    assert generic.canonical_metric is None
    assert generic.mapping_status == MetricMappingStatus.AMBIGUOUS
    assert chinese_cash.canonical_metric == "cash_and_bank_balances"
    assert chinese_cash.canonical_metric != "cash_and_cash_equivalents"
    assert cash_equivalents.canonical_metric == "cash_and_cash_equivalents"
    assert cash_equivalents.canonical_metric != chinese_cash.canonical_metric
    assert normalize_financial_table_row(_row("cash")).mapping_status == MetricMappingStatus.AMBIGUOUS


def test_operating_revenue_and_revenue_are_not_collapsed():
    total_revenue = normalize_financial_table_row(_row("营业总收入", "income_statement"))
    revenue = normalize_financial_table_row(_row("营业收入", "income_statement"))

    assert total_revenue.canonical_metric == "total_operating_revenue"
    assert revenue.canonical_metric == "revenue"
    assert total_revenue.canonical_metric != revenue.canonical_metric


@pytest.mark.parametrize(
    ("label", "statement"),
    [
        ("销售商品、提供劳务收到的现金", "cash_flow_statement"),
        ("自由现金流", "cash_flow_statement"),
        ("短期债务", "balance_sheet"),
    ],
)
def test_unregistered_near_synonyms_remain_unmapped(label: str, statement: str):
    result = normalize_financial_table_row(_row(label, statement))
    assert result.canonical_metric is None
    assert result.mapping_status == MetricMappingStatus.UNMAPPED


@pytest.mark.parametrize(
    ("label", "statement", "expected", "forbidden_equivalent"),
    [
        ("负债合计", "balance_sheet", "total_liabilities", "total_debt"),
        ("货币资金", "balance_sheet", "cash_and_bank_balances", "cash_and_cash_equivalents"),
        ("净利润", "income_statement", "net_income", "attributable_net_income"),
        ("归属于母公司股东的净利润", "income_statement", "attributable_net_income", "net_income"),
        ("所有者权益合计", "balance_sheet", "total_equity", "equity_attributable_to_parent"),
        (
            "归属于母公司所有者权益合计",
            "equity_statement",
            "equity_attributable_to_parent",
            "total_equity",
        ),
        ("固定资产", "balance_sheet", "fixed_assets", "capital_expenditure"),
        ("在建工程", "balance_sheet", "construction_in_progress", "capital_expenditure"),
        (
            "经营活动产生的现金流量净额",
            "cash_flow_statement",
            "operating_cash_flow",
            "free_cash_flow",
        ),
        (
            "期末现金及现金等价物余额",
            "cash_flow_statement",
            "cash_and_cash_equivalents_ending",
            "cash_and_bank_balances",
        ),
    ],
)
def test_negative_semantic_boundaries_are_distinct(
    label: str, statement: str, expected: str, forbidden_equivalent: str
):
    result = normalize_financial_table_row(_row(label, statement))
    assert result.canonical_metric == expected
    assert result.mapping_status in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}
    assert result.canonical_metric != forbidden_equivalent


def test_unverified_structural_row_cannot_become_a_canonical_metric():
    source = _row("资产总计", status=VerificationStatus.PARTIAL)
    result = normalize_financial_table_row(source)

    assert result.canonical_metric is None
    assert result.mapping_status == MetricMappingStatus.UNMAPPED
    assert result.mapping_rule == "source_row_not_structurally_verified"


def test_scope_period_and_structural_verification_are_not_changed_by_mapping():
    consolidated = _row("资产总计", scope="consolidated", period="2025-12-31")
    parent = _row("资产总计", scope="parent", period="2024-12-31")
    left = normalize_financial_table_row(consolidated)
    right = normalize_financial_table_row(parent)

    assert left.canonical_metric == right.canonical_metric == "total_assets"
    assert left.row.scope == "consolidated" and right.row.scope == "parent"
    assert left.row.period == "2025-12-31" and right.row.period == "2024-12-31"
    assert left.row.verification_status == right.row.verification_status == VerificationStatus.VERIFIED
    assert left.row.canonical_metric is None and right.row.canonical_metric is None


def test_registry_definitions_expose_required_metadata_and_scope_period_dimensions():
    assets = FINANCIAL_METRIC_REGISTRY.get("total_assets")
    assert assets is not None
    assert assets.category == "balance_sheet"
    assert assets.statement_types == ("balance_sheet",)
    assert assets.scope_rules
    assert assets.period_semantics == "point_in_time"
    assert assets.value_type == "monetary"
    assert assets.aggregation_semantics


def test_real_moutai_p1_3_rows_are_normalized_without_changing_source_rows():
    fixture = Path(__file__).parent / "fixtures" / "moutai-standard-statements-2025.pdf"
    document = parse_pdf(fixture, ocr_enabled=False, document_id="moutai-fixture-2025")
    verified = [row for row in document.financial_table_rows if row.verification_status == VerificationStatus.VERIFIED]
    normalized = [normalize_financial_table_row(row) for row in verified]

    assert len(verified) == 595
    assert len(normalized) == len(verified)
    assert all(item.row is row for item, row in zip(normalized, verified, strict=True))
    assert all(row.canonical_metric is None for row in verified)
    assert sum(item.mapping_status == MetricMappingStatus.EXACT for item in normalized) > 0
    assert sum(item.mapping_status == MetricMappingStatus.SUPPORTED for item in normalized) > 0
    assert sum(item.mapping_status == MetricMappingStatus.UNMAPPED for item in normalized) > 0

    expected_samples = {
        ("资产总计", "total_assets", "balance_sheet", "consolidated"),
        ("负债合计", "total_liabilities", "balance_sheet", "consolidated"),
        ("货币资金", "cash_and_bank_balances", "balance_sheet", "consolidated"),
        ("固定资产", "fixed_assets", "balance_sheet", "consolidated"),
        ("在建工程", "construction_in_progress", "balance_sheet", "consolidated"),
    }
    actual_samples = {
        (item.original_label, item.canonical_metric, item.statement_type, item.scope) for item in normalized
    }
    assert expected_samples <= actual_samples

    def has_canonical_fragment(metric: str, fragment: str, statement: str) -> bool:
        return any(
            item.canonical_metric == metric
            and statement == item.statement_type
            and item.scope == "consolidated"
            and fragment in item.normalized_label
            for item in normalized
        )

    assert has_canonical_fragment("net_income", "净利润", "income_statement")
    assert has_canonical_fragment("attributable_net_income", "归属于母公司股东的净利润", "income_statement")
    assert has_canonical_fragment("operating_cash_flow", "经营活动产生的现金流量净额", "cash_flow_statement")
    assert has_canonical_fragment("cash_and_cash_equivalents_ending", "期末现金及现金等价物余额", "cash_flow_statement")

    # These relations must never collapse to the same canonical metric.
    by_label = {}
    for item in normalized:
        by_label.setdefault(item.normalized_label, set()).add(item.canonical_metric)
    assert any(label.startswith("五、净利润") and values == {"net_income"} for label, values in by_label.items())
    assert any(
        label.startswith("1.归属于母公司股东的净利润") and values == {"attributable_net_income"}
        for label, values in by_label.items()
    )
    assert any(
        "所有者权益(或股东权益)合计" in label and values == {"total_equity"} for label, values in by_label.items()
    )
    assert any(
        label == "归属于母公司所有者权益" and values == {"equity_attributable_to_parent"}
        for label, values in by_label.items()
    )

    labels_by_metric = {}
    for item in normalized:
        if item.canonical_metric:
            labels_by_metric.setdefault(item.canonical_metric, set()).add(item.normalized_label)
    actual_collision_groups = {metric: labels for metric, labels in labels_by_metric.items() if len(labels) > 1}
    assert actual_collision_groups == {
        "net_income": {
            "五、净利润(净亏损以“-”号填列)",
            "四、净利润(净亏损以“-”号填列)",
        },
        "operating_income": {
            "三、营业利润(亏损以“-”号填列)",
            "二、营业利润(亏损以“-”号填列)",
        },
        "revenue": {"一、营业收入", "其中:营业收入"},
        "total_profit": {
            "三、利润总额(亏损总额以“-”号填列)",
            "四、利润总额(亏损总额以“-”号填列)",
        },
    }


def test_distinct_scope_and_period_observations_share_metric_without_identity_collision():
    observations = [
        normalize_financial_table_row(_row("资产总计", scope="consolidated", period="2025-12-31")),
        normalize_financial_table_row(_row("资产总计", scope="parent", period="2025-12-31")),
        normalize_financial_table_row(_row("资产总计", scope="consolidated", period="2024-12-31")),
    ]
    assert {item.canonical_metric for item in observations} == {"total_assets"}
    assert len({(item.row.scope, item.row.period) for item in observations}) == 3
