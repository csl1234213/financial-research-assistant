from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from core.financial_statement_reconstruction import reconstruct_financial_statements
from core.financial_table_rows import VerificationStatus
from document_loader import chunk_document, parse_pdf


def _region(text: str, y0: float, y1: float) -> SimpleNamespace:
    return SimpleNamespace(text=text, bbox=(80.0, y0, 540.0, y1))


def _table(
    page: int,
    table_index: int,
    rows: list[tuple[str | None, ...]],
    *,
    y0: float = 100.0,
) -> SimpleNamespace:
    parsed_rows = []
    for index, cells in enumerate(rows):
        cell_bboxes = tuple(
            (80.0 + cell * 110, y0 + index * 18, 180.0 + cell * 110, y0 + (index + 1) * 18)
            for cell in range(len(cells))
        )
        parsed_rows.append(
            SimpleNamespace(
                cells=cells,
                cell_bboxes=cell_bboxes,
                bbox=(80.0, y0 + index * 18, 520.0, y0 + (index + 1) * 18),
            )
        )
    return SimpleNamespace(
        page=page,
        table_index=table_index,
        bbox=(80.0, y0, 520.0, y0 + len(rows) * 18),
        rows=tuple(parsed_rows),
    )


def _page(
    number: int,
    regions: list[SimpleNamespace],
    tables: list[SimpleNamespace],
    blocks: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        number=number,
        text_regions=tuple(regions),
        table_candidates=tuple(tables),
        blocks=tuple(blocks or ()),
    )


def test_reconstructs_atomic_rows_and_inherits_only_adjacent_continuation():
    header = ("项目", "附注", "2025 年12 月31 日", "2024 年12 月31 日")
    first = _page(
        1,
        [
            _region("合并资产负债表", 10, 22),
            _region("编制单位：示例股份有限公司\n单位：元\n币种：人民币", 28, 70),
        ],
        [
            _table(
                1,
                1,
                [header, ("货币资金", "七、1", "1,234.50", "(123.45)"), ("固定资产", "七、21", "—", "900.00")],
            )
        ],
    )
    continuation = _page(
        2,
        [],
        [_table(2, 1, [("存货", "七、5", "2,000", "1,800")])],
    )
    parent = _page(
        3,
        [
            _region("母公司资产负债表", 10, 22),
            _region("单位：万元\n币种：人民币\n项目\n附注\n2025年度\n2024年度", 28, 80),
        ],
        [_table(3, 1, [("项目", "附注", "2025年度", "2024年度"), ("货币资金", "", "8.25", "7.50")])],
    )

    result = reconstruct_financial_statements(
        (first, continuation, parent),
        filename="example.pdf",
        document_id="tenant-1-doc-1",
    )

    consolidated_cash = [
        row for row in result.rows
        if row.scope == "consolidated" and row.row_label == "货币资金"
    ]
    assert [(row.period, row.value) for row in consolidated_cash] == [
        ("2025-12-31", Decimal("1234.50")),
        ("2024-12-31", Decimal("-123.45")),
    ]
    assert all(row.verification_status == VerificationStatus.VERIFIED for row in consolidated_cash)
    assert all(row.canonical_metric is None for row in consolidated_cash)
    assert all(row.note_reference == "七、1" for row in consolidated_cash)
    assert all(row.column_role in {"closing_balance", "comparative_balance"} for row in consolidated_cash)
    assert all(row.source_region and "bbox=" in row.source_region for row in consolidated_cash)

    carried = next(row for row in result.rows if row.row_label == "存货")
    assert carried.scope == "consolidated"
    assert carried.period == "2025-12-31"
    assert carried.page == 2
    assert carried.note_reference == "七、5"

    parent_cash = [
        row for row in result.rows
        if row.scope == "parent" and row.row_label == "货币资金"
    ]
    assert {row.period for row in parent_cash} == {"FY2025", "FY2024"}
    assert all(row.unit == "万元" and row.currency == "CNY" for row in parent_cash)


def test_unproven_opening_period_or_ambiguous_scope_never_verifies():
    page = _page(
        1,
        [
            _region("资产负债表", 10, 22),
            _region("截至2025年12月31日\n单位：元\n币种：人民币", 28, 50),
        ],
        [
            _table(
                1,
                1,
                [("项目", "期末余额", "期初余额"), ("货币资金", "100", "90")],
            )
        ],
    )

    result = reconstruct_financial_statements((page,), filename="example.pdf", document_id="doc-1")

    assert result.rows
    assert all(row.scope == "unknown" for row in result.rows)
    assert all(row.verification_status != VerificationStatus.VERIFIED for row in result.rows)
    assert {row.period for row in result.rows} == {"2025-12-31", "2024-12-31"}
    assert {row.column_role for row in result.rows} == {
        "closing_balance", "comparative_balance"
    }


def test_non_table_section_heading_terminates_previous_statement_context():
    first = _page(
        1,
        [
            _region("合并资产负债表", 10, 22),
            _region("单位：元\n币种：人民币", 28, 50),
        ],
        [_table(1, 1, [("项目", "2025年度", "2024年度"), ("货币资金", "100", "90")])],
    )
    second = _page(
        2,
        [],
        [_table(2, 1, [("存货", "200", "180")])],
        blocks=[
            SimpleNamespace(
                text="业务经营情况",
                is_heading=True,
                bbox=(80.0, 10.0, 540.0, 22.0),
            )
        ],
    )

    result = reconstruct_financial_statements((first, second), filename="example.pdf", document_id="doc-1")

    assert len(result.contexts) == 1
    assert {row.row_label for row in result.rows} == {"货币资金"}
    assert all(row.page == 1 for row in result.rows)


def test_skips_repeated_headers_and_never_turns_dash_or_blank_into_values():
    header = ("项目", "附注", "2025年度", "2024年度")
    page = _page(
        1,
        [
            _region("合并资产负债表", 10, 22),
            _region("单位：元\n币种：人民币", 28, 50),
        ],
        [
            _table(
                1,
                1,
                [
                    header,
                    ("货币资金", "七、1", "1,234.50", "900"),
                    header,
                    ("固定资产", "七、21", "—", ""),
                ],
            )
        ],
    )

    result = reconstruct_financial_statements((page,), filename="example.pdf", document_id="doc-1")

    assert [(row.row_label, row.period, row.value) for row in result.rows] == [
        ("货币资金", "FY2025", Decimal("1234.50")),
        ("货币资金", "FY2024", Decimal("900")),
    ]
    assert all("项目" not in (row.row_label or "") for row in result.rows)


def test_explicit_period_header_is_not_shifted_into_the_note_column():
    page = _page(
        1,
        [
            _region("合并利润表", 10, 22),
            _region("单位：元\n币种：人民币", 28, 50),
        ],
        [
            _table(
                1,
                1,
                [
                    ("项目", "附注", "2025年度", "2024年度"),
                    ("营业收入", "44", "1,000.00", "900.00"),
                ],
            )
        ],
    )

    result = reconstruct_financial_statements((page,), filename="example.pdf", document_id="doc-1")
    revenue = [row for row in result.rows if row.row_label == "营业收入"]

    assert [row.period for row in revenue] == ["FY2025", "FY2024"]
    assert all(row.note_reference == "44" for row in revenue)
    assert all(row.value not in {Decimal("44"), Decimal("2025"), Decimal("2024")} for row in revenue)


def test_real_moutai_statement_excerpt_reconstructs_auditable_verified_rows():
    fixture = Path(__file__).parent / "fixtures" / "moutai-standard-statements-2025.pdf"
    document = parse_pdf(fixture, ocr_enabled=False, document_id="moutai-fixture-2025")
    rows = document.financial_table_rows
    verified = [row for row in rows if row.verification_status == VerificationStatus.VERIFIED]
    chunks = chunk_document(document)
    chunk_rows = [row for chunk in chunks for row in chunk.financial_table_rows]
    # Chunk overlap may repeat atomic observations, but must neither invent
    # nor lose any reconstructed row.
    assert set(chunk_rows) == set(rows)
    assert all(row.source_region and row.source_locator for row in chunk_rows if row.verification_status == VerificationStatus.VERIFIED)

    for statement_type, minimum in (
        ("balance_sheet", 10),
        ("income_statement", 5),
        ("cash_flow_statement", 5),
    ):
        assert sum(row.statement_type == statement_type for row in verified) >= minimum

    contexts = {(context.statement_type, context.scope) for context in document.financial_table_contexts}
    assert ("balance_sheet", "consolidated") in contexts
    assert ("balance_sheet", "parent") in contexts
    assert ("income_statement", "consolidated") in contexts
    assert ("income_statement", "parent") in contexts
    assert ("cash_flow_statement", "consolidated") in contexts
    assert ("cash_flow_statement", "parent") in contexts
    assert ("equity_statement", "consolidated") in contexts
    assert ("equity_statement", "parent") in contexts
    consolidated_equity = next(
        context
        for context in document.financial_table_contexts
        if context.statement_type == "equity_statement" and context.scope == "consolidated"
    )
    assert len(consolidated_equity.column_headers) >= 9
    assert any("归属于母公司所有者权益" in header for header in consolidated_equity.column_headers)
    assert any("实收资本" in header for header in consolidated_equity.column_headers)
    assert any("未分配利润" in header for header in consolidated_equity.column_headers)
    assert all(
        row.verification_status != VerificationStatus.VERIFIED
        for row in rows
        if row.scope == "unknown"
    )

    # Manually transcribed from the native table cells of original report pages.
    # Tuple order: statement, scope, row-label fragment, period, raw amount, page.
    ground_truth = (
        ("balance_sheet", "consolidated", "货币资金", "2025-12-31", "51,690,610,946.50", 56),
        ("balance_sheet", "consolidated", "货币资金", "2024-12-31", "59,295,822,956.89", 56),
        ("balance_sheet", "consolidated", "应收账款", "2025-12-31", "2,609,048.49", 57),
        ("balance_sheet", "consolidated", "存货", "2025-12-31", "61,427,421,796.18", 57),
        ("balance_sheet", "consolidated", "固定资产", "2025-12-31", "22,488,122,304.35", 57),
        ("balance_sheet", "consolidated", "在建工程", "2025-12-31", "2,471,886,030.58", 57),
        ("balance_sheet", "consolidated", "资产总计", "2025-12-31", "303,834,844,021.44", 57),
        ("balance_sheet", "consolidated", "负债合计", "2025-12-31", "49,875,590,112.37", 58),
        ("balance_sheet", "parent", "货币资金", "2025-12-31", "85,687,080,245.45", 59),
        ("balance_sheet", "parent", "资产总计", "2025-12-31", "195,350,142,529.19", 60),
        ("income_statement", "consolidated", "其中：营业收入", "FY2025", "168,838,102,514.79", 61),
        ("income_statement", "consolidated", "其中：营业成本", "FY2025", "14,892,277,570.91", 61),
        ("income_statement", "consolidated", "三、营业利润", "FY2025", "114,808,950,164.24", 62),
        ("income_statement", "consolidated", "五、净利润", "FY2025", "85,310,324,833.67", 62),
        ("income_statement", "consolidated", "归属于母公司股东的净利润", "FY2025", "82,320,067,101.68", 62),
        ("cash_flow_statement", "consolidated", "经营活动产生的现金流", "FY2025", "61,522,204,989.35", 65),
        ("cash_flow_statement", "consolidated", "投资活动产生的现金流", "FY2025", "-31,641,898,948.89", 65),
        ("cash_flow_statement", "consolidated", "筹资活动产生的现金流", "FY2025", "-73,427,081,208.87", 66),
        ("cash_flow_statement", "consolidated", "现金及现金等价物净增加额", "FY2025", "-43,544,479,810.11", 66),
        ("cash_flow_statement", "consolidated", "期末现金及现金等价物余额", "FY2025", "126,425,609,447.72", 66),
    )

    assert len(ground_truth) >= 20
    for statement, scope, label_fragment, period, raw_value, page in ground_truth:
        matches = [
            row
            for row in rows
            if row.statement_type == statement
            and row.scope == scope
            and label_fragment in (row.row_label or "")
            and row.period == period
            and row.raw_value == raw_value
            and row.page == page
        ]
        assert len(matches) == 1, (statement, scope, label_fragment, period, raw_value, page)
        match = matches[0]
        assert match.verification_status == VerificationStatus.VERIFIED
        assert match.value == Decimal(raw_value.replace(",", ""))
        assert match.unit == "元"
        assert match.currency == "CNY"
        assert match.source_region and "bbox=" in match.source_region

    # Cross-page income continuation has a grid artifact on one row. Geometry,
    # not column ordinal, must keep FY2024 attached to its original x position.
    parent_profit = next(
        row for row in rows
        if row.statement_type == "income_statement"
        and row.scope == "consolidated"
        and "归属于母公司股东的净利润" in (row.row_label or "")
        and row.period == "FY2024"
    )
    assert parent_profit.raw_value == "86,228,146,421.62"
    assert parent_profit.page == 62
