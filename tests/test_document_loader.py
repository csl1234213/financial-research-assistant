from __future__ import annotations

from pathlib import Path

import fitz
import pytest

import document_loader
from agent.reasoning_models import Evidence
from core.fact_ledger import FactLedger
from document_loader import (
    DocumentChunk,
    DocumentProcessingError,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
    chunk_document,
    get_document_period,
    load_pdf_chunks,
    parse_pdf,
)


def _write_text_pdf(path) -> None:
    with fitz.open() as pdf:
        first = pdf.new_page()
        first.insert_text((72, 72), "Revenue Overview", fontsize=16)
        first.insert_text(
            (72, 160),
            "Tesla automotive revenue increased during the quarter.",
        )
        second = pdf.new_page()
        second.insert_text((72, 72), "Risk Factors", fontsize=16)
        second.insert_text(
            (72, 160),
            "Supply chain constraints remain a material risk.",
        )
        pdf.save(path)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("opening_text", "expected"),
    (
        (
            "Apple Inc. Form 10-Q. For the quarterly period ended March 28, 2026.",
            "Q2_FY2026",
        ),
        (
            "NVIDIA Announces Financial Results for First Quarter Fiscal 2027. "
            "Q1 FY27 Q4 FY26 Q1 FY26 financial summary.",
            "Q1_FY2027",
        ),
        (
            "Tesla Q4 and FY 2025 Update. Q4-2024 Q1-2025 Q2-2025 Q3-2025 Q4-2025.",
            "Q4_2025",
        ),
        (
            "Financial Summary Highlights: Q4 & FY’25. Q4 revenue and FY 2025 results.",
            "Q4_2025",
        ),
    ),
)
def test_get_document_period_prefers_content_derived_issuer_filing_header(
    opening_text, expected
):
    chunks = [
        DocumentChunk(
            text=opening_text,
            page=1,
            section="Cover",
            ocr_used=False,
            chunk_index=0,
        )
    ]

    assert get_document_period(chunks) == expected


@pytest.mark.unit
def test_verified_structured_row_inherits_unique_statement_group_label():
    source = ParsedBlock(
        text="Services 30,976 26,645 60,989 52,985",
        page=4,
        section="Net sales:",
        ocr_used=False,
        content_type="unverified_table",
    )
    structured = ParsedBlock(
        text=(
            "Structured financial table row (PDF page 4).\n"
            "Financial table row — Metric: Services | Q2 FY2026: 30,976 | "
            "Q2 FY2025: 26,645 | YTD Q2 FY2026: 60,989 | "
            "YTD Q2 FY2025: 52,985"
        ),
        page=4,
        section="Table 1",
        ocr_used=False,
        content_type="table",
    )

    [bound] = document_loader._inherit_statement_group_labels([source], [structured])

    assert "Verified statement group: Net sales." in bound.text
    assert "Resolved financial label: Services net sales" in bound.text


@pytest.mark.unit
def test_verified_structured_row_does_not_inherit_ambiguous_statement_group():
    sources = [
        ParsedBlock(
            text="Services 30,976 26,645 60,989 52,985",
            page=4,
            section="Net sales:",
            ocr_used=False,
            content_type="unverified_table",
        ),
        ParsedBlock(
            text="Services 30,976 26,645 60,989 52,985",
            page=4,
            section="Cost of sales:",
            ocr_used=False,
            content_type="unverified_table",
        ),
    ]
    structured = ParsedBlock(
        text=(
            "Structured financial table row (PDF page 4).\n"
            "Financial table row — Metric: Services | Q2 FY2026: 30,976 | "
            "Q2 FY2025: 26,645 | YTD Q2 FY2026: 60,989 | "
            "YTD Q2 FY2025: 52,985"
        ),
        page=4,
        section="Table 1",
        ocr_used=False,
        content_type="table",
    )

    [bound] = document_loader._inherit_statement_group_labels(sources, [structured])

    assert "Resolved financial label" not in bound.text


@pytest.mark.unit
def test_parse_pdf_preserves_sorted_page_and_section_provenance(tmp_path):
    pdf_path = tmp_path / "Tesla_Q2_2025.pdf"
    _write_text_pdf(pdf_path)

    parsed = parse_pdf(pdf_path, ocr_enabled=False)

    assert parsed.parser_version == "pymupdf-blocks-ocr-v20-financial-row-reconstruction"
    assert [page.number for page in parsed.pages] == [1, 2]
    assert [block.text for block in parsed.pages[0].blocks] == [
        "Revenue Overview",
        "Tesla automotive revenue increased during the quarter.",
    ]
    assert parsed.pages[0].blocks[1].section == "Revenue Overview"
    assert parsed.pages[1].blocks[1].section == "Risk Factors"
    assert not any(page.ocr_used for page in parsed.pages)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "metric", "current", "prior", "growth"),
    (
        (
            "归属于上市公司股东的净利润",
            "Net Income Attributable to Shareholders",
            "82320067101.68",
            "86228146421.62",
            "-4.53",
        ),
        (
            "经营活动产生的现金流量净额",
            "Operating Cash Flow",
            "61522204989.35",
            "92463692168.43",
            "-33.46",
        ),
    ),
)
def test_cninfo_annual_summary_binds_whitelisted_metric_rows(
    label, metric, current, prior, growth
):
    blocks = [
        ParsedBlock("七、近三年主要会计数据和财务指标", 6, "", False),
        ParsedBlock("主要会计数据", 6, "", False),
        ParsedBlock("2025年", 6, "", False),
        ParsedBlock("2024年", 6, "", False),
        ParsedBlock("本期比上年同期增减", 6, "", False),
        ParsedBlock("(%)", 6, "", False),
        ParsedBlock("2023年", 6, "", False),
        ParsedBlock(
            f"{label} {current} {prior} {growth} 74734071550.75",
            6,
            "",
            False,
            content_type="unverified_table",
        ),
    ]

    attached = document_loader._attach_table_context(blocks)

    row = attached[-1]
    assert row.content_type == "table"
    assert f"Metric: {metric}" in row.text
    assert f"FY2025: {current} CNY" in row.text
    assert f"FY2024: {prior} CNY" in row.text
    assert f"YoY: {growth}%" in row.text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("heading", "label", "dimension", "revenue", "margin", "growth"),
    (
        (
            "主营业务分产品情况",
            "茅台酒",
            "product",
            "146499906480.49",
            "93.53",
            "0.39",
        ),
        (
            "主营业务分产品情况",
            "其他系列酒",
            "product",
            "22274678707.16",
            "76.11",
            "-9.76",
        ),
        (
            "主营业务分地区情况",
            "国内",
            "region",
            "163924442864.97",
            "91.21",
            "-0.91",
        ),
        (
            "主营业务分地区情况",
            "国外",
            "region",
            "4850142322.68",
            "91.69",
            "-6.52",
        ),
        (
            "主营业务分销售模式情况",
            "批发代理",
            "sales_mode",
            "84231553333.02",
            "87.86",
            "-12.05",
        ),
        (
            "主营业务分销售模式情况",
            "直销",
            "sales_mode",
            "84543031854.63",
            "94.58",
            "12.96",
        ),
    ),
)
def test_cninfo_segment_table_requires_headers_and_preserves_row_labels(
    heading, label, dimension, revenue, margin, growth
):
    blocks = [
        ParsedBlock(heading, 10, "", False),
        ParsedBlock("单位：元 币种：人民币", 10, "", False),
        ParsedBlock("营业收入 营业成本 毛利率（%）", 10, "", False),
        ParsedBlock(
            f"{label} {revenue} 9484757825.54 {margin} {growth} 9.50 减少0.53 个百 分点",
            10,
            "",
            False,
            content_type="unverified_table",
        ),
    ]

    attached = document_loader._attach_table_context(blocks)

    row = attached[-1]
    assert row.content_type == "table"
    assert f"Dimension: {dimension}; Category: {label}" in row.text
    assert f"Metric: Revenue | FY2025: {revenue} CNY | YoY: {growth}%" in row.text
    assert f"Metric: Gross Margin | FY2025: {margin}%" in row.text
    assert "FY2025" in row.table_context


@pytest.mark.unit
def test_cninfo_segment_table_rejects_rows_without_recognized_section_headers():
    blocks = [
        ParsedBlock("Other discussion", 10, "", False),
        ParsedBlock(
            "茅台酒 146,499,906,480.49 9,484,757,825.54 93.53 0.39 9.50 减少0.53 个百分点",
            10,
            "",
            False,
            content_type="unverified_table",
        ),
    ]

    [_, row] = document_loader._attach_table_context(blocks)

    assert row.content_type == "unverified_table"


@pytest.mark.unit
def test_parse_pdf_keeps_two_column_prose_in_column_reading_order(tmp_path):
    pdf_path = tmp_path / "two-column-quarterly-report.pdf"
    left_column = (
        "Revenue increased during the quarter as demand strengthened.",
        "Operating income grew as gross profit improved.",
        "Net income reflected stronger operating performance.",
        "Operating cash flow also increased year over year.",
    )
    right_column = (
        "Data Center sales were the primary growth contributor.",
        "Gross margin expanded due to a favorable product mix.",
        "Capital spending funded new production capacity.",
        "Risk factors include supply and regulatory uncertainty.",
    )
    merged_line_left = "Revenue growth continued into the following quarter."
    merged_line_right = "Management expects demand to remain strong."
    with fitz.open() as pdf:
        page = pdf.new_page(width=720, height=792)
        page.insert_text((72, 45), "Quarterly Financial Results", fontsize=15)
        for y, text in zip((100, 130, 160, 190), left_column, strict=True):
            page.insert_text((72, y), text, fontsize=10)
        for y, text in zip((100, 130, 160, 190), right_column, strict=True):
            page.insert_text((390, y), text, fontsize=10)
        page.insert_text((72, 230), merged_line_left, fontsize=10)
        page.insert_text((390, 230), merged_line_right, fontsize=10)
        pdf.save(pdf_path)

    parsed = parse_pdf(pdf_path, ocr_enabled=False)
    texts = [block.text for block in parsed.pages[0].blocks]

    left_positions = [texts.index(text) for text in left_column]
    right_positions = [texts.index(text) for text in right_column]
    assert left_positions == sorted(left_positions)
    assert right_positions == sorted(right_positions)
    left_positions.append(texts.index(merged_line_left))
    right_positions.append(texts.index(merged_line_right))
    assert max(left_positions) < min(right_positions)
    assert texts.index("Quarterly Financial Results") < min(left_positions)


@pytest.mark.unit
def test_column_reading_order_respects_full_width_section_breaks():
    blocks = [
        (72.0, 10.0, 640.0, 30.0, "Quarterly Financial Results", 0, 0),
        (72.0, 50.0, 280.0, 70.0, "Revenue increased during the quarter.", 1, 0),
        (390.0, 50.0, 600.0, 70.0, "Segment revenue increased during the quarter.", 2, 0),
        (72.0, 90.0, 280.0, 110.0, "Operating income grew year over year.", 3, 0),
        (390.0, 90.0, 600.0, 110.0, "Gross margin improved during the quarter.", 4, 0),
        (72.0, 140.0, 640.0, 160.0, "Business Outlook and Risks", 5, 0),
        (72.0, 180.0, 280.0, 200.0, "Revenue growth is expected to continue.", 6, 0),
        (390.0, 180.0, 600.0, 200.0, "Demand remains a key uncertainty.", 7, 0),
    ]

    ordered = document_loader._column_reading_order(blocks, fitz.Rect(0, 0, 720, 792))

    assert ordered is not None
    assert [block[5] for block in ordered] == [0, 1, 3, 2, 4, 5, 6, 7]


@pytest.mark.unit
@pytest.mark.parametrize(
    "table_cell",
    [
        "2Q-2025",
        "March 28,",
        "Revenue",
        "$12.4",
        "2025",
    ],
)
def test_table_cells_are_not_misclassified_as_headings(table_cell):
    assert not document_loader._looks_like_heading(
        table_cell,
        table_cell,
    )


@pytest.mark.unit
def test_real_multiword_title_remains_a_heading():
    assert document_loader._looks_like_heading(
        "Revenue Overview",
        "Revenue Overview",
    )


@pytest.mark.unit
def test_flattened_multi_period_financial_table_is_marked_unverified():
    text = (
        "Financial Summary Q4-2024 Q1-2025 Q2-2025 Q3-2025. "
        "Total revenues 25,707 19,335 22,496 28,095. "
        "Gross margin 16.3% 16.3% 17.2% 18.0%. "
        "Operating income 1,583 399 923 1,624. "
        "Net income 2,128 409 1,172 1,373. "
        "Cash generated by operating activities 4,814 2,156 2,540 6,238."
    )

    assert document_loader._looks_like_unverified_financial_table(text)
    assert not document_loader._looks_like_unverified_financial_table(
        "Tesla revenue was $22.496 billion in Q2 2025."
    )
    apple_table = (
        "Condensed financial results (In millions). Three Months Ended Six Months Ended "
        "March 28, 2026 March 29, 2025 March 28, 2026 March 29, 2025. "
        "Total net sales $111,184 $95,359 $238,560 $210,328. "
        "Net income $29,578 $24,780 $71,675 $61,110. "
        "Operating income $34,300 $29,600 $84,000 $68,000."
    )
    assert document_loader._looks_like_unverified_financial_table(apple_table)
    assert document_loader._looks_like_financial_table_row("Gross margin 17.2% 16.4%")


@pytest.mark.unit
def test_flattened_financial_table_without_period_headers_is_marked_unverified():
    text = "\n".join(
        (
            "Americas Europe China Japan Rest of Asia Pacific Corporate Total",
            "Net sales $ 92,963 $ 58,315 $ 34,515 $ 16,285 $ 17,581 $ — $ 219,659",
            "Cost of sales (49,589) (31,068) (18,553) (8,003) (9,304) — (116,517)",
            "Research and development — — — — — (16,818) (16,818)",
            "Selling and marketing (5,091) (2,324) (1,176) (534) (707) — (9,832)",
            "General and administrative — — — — — (4,071) (4,071)",
            "Operating income/(loss) $ 38,283 $ 24,923 $ 14,786 $ 7,748 $ 7,570 $ (20,889) $ 72,421",
            "Apple Inc. | Q2 2026 Form 10-Q | 12",
        )
    )

    blocks = [
        ParsedBlock(text=line, page=1, section="Report", ocr_used=False)
        for line in text.splitlines()
        if line.strip()
    ]
    assert not document_loader._has_comparative_period_columns(text)
    assert any(
        block.content_type == "unverified_table"
        for block in document_loader._attach_table_context(blocks)
    )
    assert document_loader._looks_like_dense_unmapped_financial_row(
        "Operating income/(loss) $ 38,283 $ 24,923 $ 14,786 $ 7,748 "
        "$ 7,570 $ (20,889) $ 72,421"
    )
    assert not document_loader._looks_like_unverified_financial_table(
        "Revenue was $22.5 billion. Operating income was $1.6 billion. "
        "The company expects demand to remain strong next quarter."
    )


@pytest.mark.unit
def test_split_cninfo_annual_header_binds_revenue_cells_without_yoy_shift():
    blocks = [
        ParsedBlock("主要会计数据", 6, "主要会计数据", False, is_heading=True),
        ParsedBlock("2025年", 6, "主要会计数据", False),
        ParsedBlock("2024年", 6, "主要会计数据", False),
        ParsedBlock("2023年", 6, "主要会计数据", False),
        ParsedBlock("本期比", 6, "主要会计数据", False),
        ParsedBlock("上年同", 6, "主要会计数据", False),
        ParsedBlock("期增减", 6, "主要会计数据", False),
        ParsedBlock("(%)", 6, "主要会计数据", False),
        ParsedBlock(
            "营业收入 168,838,102,514.79 170,899,152,276.34 -1.21 147,693,604,994.14",
            6,
            "主要会计数据",
            False,
            content_type="unverified_table",
        ),
    ]

    attached = document_loader._attach_table_context(blocks)
    row = attached[-1]

    assert row.content_type == "table"
    assert row.table_context == (
        "CNINFO annual summary; Comparative columns: FY2025 | FY2024 | FY2023; Currency: CNY"
    )
    assert "FY2025: 168838102514.79 CNY" in row.text
    assert "FY2024: 170899152276.34 CNY" in row.text
    assert "FY2023: 147693604994.14 CNY" in row.text
    assert "YoY: -1.21%" in row.text
    assert "FY2023: CNY -1.21" not in row.text

    ledger = FactLedger.from_evidence(
        [
            Evidence(
                content=row.text,
                source="贵州茅台2025年度报告.pdf",
                company="贵州茅台",
                confidence=1.0,
                metadata={
                    "content_type": row.content_type,
                    "table_context": row.table_context,
                    "page": row.page,
                    "chunk_id": "cninfo-page-6-revenue",
                },
            )
        ]
    )

    facts = ledger.lookup(company="Kweichow Moutai", metric_id="revenue")
    assert [(fact.fact_period, str(fact.value)) for fact in facts] == [
        ("FY2025", "168838102514.79"),
        ("FY2024", "170899152276.34"),
        ("FY2023", "147693604994.14"),
    ]
    assert [fact.currency for fact in facts] == ["cny", "cny", "cny"]


@pytest.mark.unit
def test_chunker_keeps_verified_cninfo_row_separate_from_quarantined_table_rows():
    blocks = [
        ParsedBlock(
            text="Unverified neighboring row: total assets 303,834,844,021.44",
            page=6,
            section="主要会计数据",
            ocr_used=False,
            content_type="unverified_table",
        ),
        ParsedBlock(
            text=(
                "Structured financial table row — Metric: Net Income Attributable "
                "to Shareholders | FY2025: 82320067101.68 CNY | "
                "FY2024: 86228146421.62 CNY | FY2023: 74734071550.75 CNY | "
                "YoY: -4.53%"
            ),
            page=6,
            section="主要会计数据",
            ocr_used=False,
            table_context="CNINFO annual summary; Currency: CNY",
            content_type="table",
        ),
        ParsedBlock(
            text="Unverified following row: net assets 244,637,811,032.18",
            page=6,
            section="主要会计数据",
            ocr_used=False,
            content_type="unverified_table",
        ),
    ]

    chunks = document_loader._chunk_block_group(
        blocks,
        chunk_size=2_000,
        overlap=200,
        start_index=0,
    )

    assert [chunk.content_type for chunk in chunks] == [
        "unverified_table",
        "table",
        "unverified_table",
    ]
    assert "Net Income Attributable" not in chunks[0].text
    assert "Unverified neighboring row" not in chunks[1].text
    assert "Unverified following row" not in chunks[1].text
    assert "FY2025: 82320067101.68 CNY" in chunks[1].text

    merged = document_loader._merge_tiny_page_chunks(
        chunks,
        minimum_chars=2_000,
    )
    assert [chunk.content_type for chunk in merged] == [
        "unverified_table",
        "table",
        "unverified_table",
    ]


@pytest.mark.unit
def test_split_cninfo_header_does_not_promote_without_explicit_yoy_mapping():
    blocks = [
        ParsedBlock("主要会计数据", 6, "主要会计数据", False, is_heading=True),
        ParsedBlock("2025年", 6, "主要会计数据", False),
        ParsedBlock("2024年", 6, "主要会计数据", False),
        ParsedBlock("2023年", 6, "主要会计数据", False),
        ParsedBlock(
            "营业收入 168,838,102,514.79 170,899,152,276.34 -1.21 147,693,604,994.14",
            6,
            "主要会计数据",
            False,
            content_type="unverified_table",
        ),
    ]

    attached = document_loader._attach_table_context(blocks)

    assert attached[-1].content_type == "unverified_table"


@pytest.mark.unit
def test_nvidia_release_highlights_remain_financial_narrative_evidence():
    source = (
        Path(__file__).resolve().parents[1]
        / "demo"
        / "documents"
        / "NVIDIA_sample.pdf"
    )
    parsed = parse_pdf(source, ocr_enabled=False)
    highlight = next(
        block
        for page in parsed.pages
        for block in page.blocks
        if "Data Center revenue" in block.text and "$75.2 billion" in block.text
    )

    assert highlight.content_type == "narrative"
    assert not document_loader._looks_like_financial_table_row(highlight.text)

    chunks = chunk_document(parsed)
    evidence_chunk = next(
        chunk
        for chunk in chunks
        if "Data Center revenue" in chunk.text and "$75.2 billion" in chunk.text
    )
    assert evidence_chunk.content_type == "narrative"


@pytest.mark.unit
def test_pdf_parser_quarantines_flattened_multi_period_financial_table(tmp_path):
    path = tmp_path / "flattened.pdf"
    text = (
        "Financial Summary Q4-2024 Q1-2025 Q2-2025 Q3-2025.\n"
        "Total revenues 25,707 19,335 22,496 28,095.\n"
        "Gross margin 16.3% 16.3% 17.2% 18.0%.\n"
        "Operating income 1,583 399 923 1,624.\n"
        "Net income 2,128 409 1,172 1,373.\n"
        "Cash generated by operating activities 4,814 2,156 2,540 6,238."
    )
    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_textbox(fitz.Rect(72, 72, 540, 400), text, fontsize=10)
        pdf.save(path)

    parsed = parse_pdf(path, ocr_enabled=False)

    assert any(
        block.content_type == "unverified_table"
        for block in parsed.pages[0].blocks
    )


@pytest.mark.unit
def test_pdf_spatial_table_binding_joins_split_columns_and_maps_fiscal_periods(tmp_path):
    path = tmp_path / "spatial-report.pdf"
    centers = (350.0, 430.0, 510.0)

    def insert_centered(page, text: str, center: float, y: float, *, fontsize: int = 10):
        width = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
        page.insert_text((center - width / 2, y), text, fontsize=fontsize)

    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_text((72, 38), "NVIDIA Corporation Q1 FY2027", fontsize=12)
        page.insert_text((72, 66), "($ in millions)", fontsize=9)
        insert_centered(page, "Three Months Ended", 430, 88)
        for center, month, day, year in zip(
            centers,
            ("April", "January", "April"),
            ("26,", "25,", "27,"),
            ("2026", "2026", "2025"),
            strict=True,
        ):
            insert_centered(page, f"{month} {day}", center, 110)
            insert_centered(page, year, center, 124)

        page.insert_text((72, 153), "Revenue", fontsize=10)
        for center, value in zip(centers, ("81,615", "68,127", "44,062"), strict=True):
            insert_centered(page, value, center, 153)
        page.insert_text((72, 173), "Gross margin", fontsize=10)
        for center, value in zip(centers, ("74.9%", "75.0%", "60.5%"), strict=True):
            insert_centered(page, value, center, 173)
        page.insert_text((72, 193), "Incomplete metric", fontsize=10)
        insert_centered(page, "12,000", centers[0], 193)
        insert_centered(page, "10,000", centers[2], 193)
        page.insert_text((72, 253), "Later unrelated metric", fontsize=10)
        for center, value in zip(centers, ("9,000", "8,000", "7,000"), strict=True):
            insert_centered(page, value, center, 253)
        pdf.save(path)

    parsed = parse_pdf(path, ocr_enabled=False)
    spatial_rows = [
        block
        for page in parsed.pages
        for block in page.blocks
        if block.content_type == "table" and "spatial table row" in (block.source_locator or "")
    ]

    revenue = next(block.text for block in spatial_rows if "Metric: Revenue" in block.text)
    margin = next(block.text for block in spatial_rows if "Metric: Gross margin" in block.text)
    assert "Q1 FY2027" in revenue and "81,615" in revenue
    assert "Q4 FY2026" in revenue and "68,127" in revenue
    assert "Q1 FY2026" in revenue and "44,062" in revenue
    assert "three months ended" in revenue.casefold()
    assert "incomplete metric" not in "\n".join(block.text for block in spatial_rows).casefold()
    assert "later unrelated metric" not in "\n".join(block.text for block in spatial_rows).casefold()
    assert "74.9%" in margin and "75.0%" in margin and "60.5%" in margin


@pytest.mark.unit
def test_pdf_spatial_table_binding_maps_explicit_quarter_label_columns(tmp_path):
    path = tmp_path / "quarter-label-report.pdf"
    centers = (300.0, 390.0, 480.0)

    def insert_centered(page, text: str, center: float, y: float):
        width = fitz.get_text_length(text, fontname="helv", fontsize=10)
        page.insert_text((center - width / 2, y), text, fontsize=10)

    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_text((72, 38), "Tesla Financial Summary", fontsize=12)
        page.insert_text((72, 66), "($ in millions, except per share data)", fontsize=9)
        for center, period in zip(centers, ("Q4-2024", "Q2-2025", "Q4-2025"), strict=True):
            insert_centered(page, period, center, 88)
        for metric, values, y in (
            ("Total revenues", ("25,707", "22,496", "24,901"), 116),
            ("Diluted EPS", ("0.60", "0.33", "0.50"), 136),
        ):
            page.insert_text((72, y), metric, fontsize=10)
            for center, value in zip(centers, values, strict=True):
                insert_centered(page, value, center, y)
        pdf.save(path)

    parsed = parse_pdf(path, ocr_enabled=False)
    rows = [
        block
        for page in parsed.pages
        for block in page.blocks
        if block.content_type == "table" and "spatial table row" in (block.source_locator or "")
    ]
    revenue = next(block for block in rows if "Metric: Total revenues" in block.text)
    eps = next(block for block in rows if "Metric: Diluted EPS" in block.text)

    assert "Q4-2024" in revenue.table_context
    assert "Q2-2025" in revenue.table_context
    assert "Q4 2025 (ended Q4-2025): 24,901" in revenue.text
    assert "Q2 2025 (ended Q2-2025): 0.33" in eps.text

    ledger = FactLedger.from_evidence(
        [
            Evidence(
                content=eps.text,
                source=path.name,
                company="Tesla",
                metadata={
                    "chunk_id": "quarter-label-eps",
                    "table_context": eps.table_context,
                    "content_type": eps.content_type,
                },
            )
        ]
    )
    assert [
        str(fact.normalized_value)
        for fact in ledger.lookup(company="Tesla", metric_id="eps", period="Q2_2025")
    ] == ["0.33"]


@pytest.mark.unit
def test_pdf_spatial_header_does_not_promote_inline_narrative_dates(tmp_path):
    path = tmp_path / "narrative-dates.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_text((72, 38), "NVIDIA Corporation Q1 FY2027", fontsize=12)
        page.insert_text(
            (72, 110),
            "Three months ended April 26, 2026 and April 27, 2025.",
            fontsize=10,
        )
        page.insert_text((72, 150), "Revenue", fontsize=10)
        page.insert_text((330, 150), "81,615", fontsize=10)
        page.insert_text((430, 150), "44,062", fontsize=10)
        pdf.save(path)

    with fitz.open(path) as pdf:
        page = pdf[0]
        header = document_loader._find_spatial_table_header(
            page,
            document_loader._pdf_word_lines(page),
            page_number=1,
            ocr_used=False,
            document_period_hint="Q1_FY2027",
            section="Income Statement",
        )

    assert header is None


@pytest.mark.unit
def test_unverified_table_provenance_survives_chunking():
    text = (
        "Financial Summary Q4-2024 Q1-2025 Q2-2025 Q3-2025. "
        "Total revenues 25,707 19,335 22,496 28,095. "
        "Gross margin 16.3% 16.3% 17.2% 18.0%. "
        "Operating income 1,583 399 923 1,624. "
        "Net income 2,128 409 1,172 1,373. "
        "Cash generated by operating activities 4,814 2,156 2,540 6,238."
    )
    document = ParsedDocument(
        filename="ambiguous.pdf",
        pages=(
            ParsedPage(
                number=1,
                ocr_used=False,
                blocks=(
                    ParsedBlock(
                        text="A filing narrative paragraph with stable discussion around the business operations.",
                        page=1,
                        section="Financial Summary",
                        ocr_used=False,
                    ),
                    ParsedBlock(
                        text=text,
                        page=1,
                        section="Financial Summary",
                        ocr_used=False,
                        content_type="unverified_table",
                    ),
                ),
            ),
        ),
    )

    chunks = chunk_document(document, chunk_size=1_000, overlap=0)

    table_chunk = next(chunk for chunk in chunks if "Financial Summary Q4" in chunk.text)
    assert table_chunk.content_type == "unverified_table"


@pytest.mark.unit
def test_chunk_document_keeps_page_and_section_boundaries():
    document = ParsedDocument(
        filename="report.pdf",
        pages=(
            ParsedPage(
                number=1,
                ocr_used=False,
                blocks=(
                    ParsedBlock(
                        text="Revenue Overview",
                        page=1,
                        section="Revenue Overview",
                        ocr_used=False,
                        is_heading=True,
                    ),
                    ParsedBlock(
                        text="Revenue increased by ten percent.",
                        page=1,
                        section="Revenue Overview",
                        ocr_used=False,
                    ),
                ),
            ),
            ParsedPage(
                number=2,
                ocr_used=True,
                blocks=(
                    ParsedBlock(
                        text="Risk Factors",
                        page=2,
                        section="Risk Factors",
                        ocr_used=True,
                        is_heading=True,
                    ),
                    ParsedBlock(
                        text="Supply chain constraints remain material.",
                        page=2,
                        section="Risk Factors",
                        ocr_used=True,
                    ),
                ),
            ),
        ),
    )

    chunks = chunk_document(document, chunk_size=100, overlap=10)

    assert [chunk.page for chunk in chunks] == [1, 2]
    assert [chunk.section for chunk in chunks] == [
        "Revenue Overview",
        "Risk Factors",
    ]
    assert [chunk.ocr_used for chunk in chunks] == [False, True]
    assert "Risk Factors" not in chunks[0].text
    assert "Revenue Overview" not in chunks[1].text


@pytest.mark.unit
def test_chunk_document_merges_heading_only_and_tiny_same_page_chunks():
    document = ParsedDocument(
        filename="table-report.pdf",
        pages=(
            ParsedPage(
                number=1,
                ocr_used=False,
                blocks=(
                    ParsedBlock(
                        text="Revenue Overview",
                        page=1,
                        section="Revenue Overview",
                        ocr_used=False,
                        is_heading=True,
                    ),
                    ParsedBlock(
                        text="Risk Factors",
                        page=1,
                        section="Risk Factors",
                        ocr_used=False,
                        is_heading=True,
                    ),
                    ParsedBlock(
                        text="Supply constraints remain material.",
                        page=1,
                        section="Risk Factors",
                        ocr_used=False,
                    ),
                ),
            ),
        ),
    )

    chunks = chunk_document(document, chunk_size=200, overlap=20)

    assert len(chunks) == 1
    assert "Revenue Overview" in chunks[0].text
    assert "Risk Factors" in chunks[0].text
    assert "Supply constraints remain material." in chunks[0].text
    assert chunks[0].section == "Risk Factors"


@pytest.mark.unit
def test_chunk_document_removes_duplicate_normalized_content():
    repeated_text = "Tesla automotive revenue increased year over year."
    document = ParsedDocument(
        filename="duplicate-report.pdf",
        pages=(
            ParsedPage(
                number=1,
                ocr_used=False,
                blocks=(
                    ParsedBlock(
                        text=repeated_text,
                        page=1,
                        section="Page 1",
                        ocr_used=False,
                    ),
                ),
            ),
            ParsedPage(
                number=2,
                ocr_used=False,
                blocks=(
                    ParsedBlock(
                        text="  TESLA   AUTOMOTIVE REVENUE increased year over year. ",
                        page=2,
                        section="Page 2",
                        ocr_used=False,
                    ),
                ),
            ),
        ),
    )

    chunks = chunk_document(document, chunk_size=200, overlap=20)

    assert len(chunks) == 1
    assert chunks[0].page == 1


@pytest.mark.unit
def test_chunk_document_carries_table_columns_to_metric_rows():
    document = ParsedDocument(
        filename="Apple_Q2_2026.pdf",
        pages=(
            ParsedPage(
                number=1,
                ocr_used=False,
                blocks=(
                    ParsedBlock(
                        text="Six Months Ended",
                        page=1,
                        section="Six Months Ended",
                        ocr_used=False,
                        is_heading=True,
                    ),
                    ParsedBlock(text="March 28,", page=1, section="Six Months Ended", ocr_used=False),
                    ParsedBlock(text="March 29,", page=1, section="Six Months Ended", ocr_used=False),
                    ParsedBlock(text="2026", page=1, section="Six Months Ended", ocr_used=False),
                    ParsedBlock(text="2025", page=1, section="Six Months Ended", ocr_used=False),
                    ParsedBlock(
                        text="Cash generated by operating activities 82,627 53,887",
                        page=1,
                        section="Changes in operating assets and liabilities:",
                        ocr_used=False,
                    ),
                ),
            ),
        ),
    )

    chunks = chunk_document(document, chunk_size=120, overlap=10)

    row = next(chunk for chunk in chunks if "Cash generated" in chunk.text)
    assert row.table_context is not None
    assert "Six Months Ended" in row.table_context
    assert "2026" in row.table_context
    assert row.content_type == "unverified_table"


@pytest.mark.unit
def test_comparative_period_context_is_bounded_to_table_rows():
    blocks = [
        ParsedBlock("Three Months Ended Six Months Ended", 1, "Page 1", False),
        ParsedBlock("March 28,", 1, "Page 1", False),
        ParsedBlock("March 29,", 1, "Page 1", False),
        ParsedBlock("March 28,", 1, "Page 1", False),
        ParsedBlock("March 29,", 1, "Page 1", False),
        ParsedBlock("2026", 1, "Page 1", False),
        ParsedBlock("2025", 1, "Page 1", False),
        ParsedBlock("Total revenue $100 $80 $200 $150", 1, "Page 1", False),
        ParsedBlock(
            "Management expects revenue to increase by 20% next year.",
            1,
            "Page 1",
            False,
        ),
    ]

    attached = document_loader._attach_table_context(blocks)

    assert attached[7].table_context is not None
    assert attached[7].content_type == "unverified_table"
    assert attached[8].table_context is None
    assert attached[8].content_type == "narrative"


@pytest.mark.unit
def test_comparative_period_dates_split_across_blocks_are_captured_and_quarantined():
    blocks = [
        ParsedBlock(
            text="Three Months Ended",
            page=1,
            section="Three Months Ended",
            ocr_used=False,
            is_heading=True,
        ),
        ParsedBlock(
            text="April 26, January 25, April 27,",
            page=1,
            section="Three Months Ended",
            ocr_used=False,
        ),
        ParsedBlock(
            text="2026 2026 2025",
            page=1,
            section="Three Months Ended",
            ocr_used=False,
        ),
        ParsedBlock(
            text="GAAP gross margin 74.9% 75.0% 60.5%",
            page=1,
            section="Three Months Ended",
            ocr_used=False,
        ),
    ]

    attached = document_loader._attach_table_context(blocks)

    assert "April 26" in attached[0].table_context
    assert "2026 2026 2025" in attached[0].table_context
    assert attached[3].content_type == "unverified_table"


@pytest.mark.unit
def test_comparative_table_scope_survives_subheadings_and_wrapped_metric_labels():
    blocks = [
        ParsedBlock(
            text="Three Months Ended",
            page=1,
            section="Three Months Ended",
            ocr_used=False,
            is_heading=True,
        ),
        ParsedBlock(text="April 26, 2026 January 25, 2026 April 27, 2025", page=1, section="Three Months Ended", ocr_used=False),
        ParsedBlock(text="GAAP gross margin 74.9% 75.0% 60.5%", page=1, section="Three Months Ended", ocr_used=False),
        ParsedBlock(text="Other comprehensive income:", page=1, section="Other comprehensive income:", ocr_used=False, is_heading=True),
        ParsedBlock(text="Change in unrealized gains and losses on derivative instruments", page=1, section="Other comprehensive income:", ocr_used=False),
        ParsedBlock(text="Change in fair value of derivative instruments 162 (318) 373", page=1, section="Other comprehensive income:", ocr_used=False),
    ]

    attached = document_loader._attach_table_context(blocks)

    assert attached[2].content_type == "unverified_table"
    assert attached[5].content_type == "unverified_table"


@pytest.mark.unit
def test_financial_table_continuation_page_is_quarantined_from_period_section():
    blocks = [
        ParsedBlock(
            text="GAAP gross margin 74.9% 75.0% 60.5%",
            page=7,
            section="Three Months Ended",
            ocr_used=False,
        ),
        ParsedBlock(
            text="GAAP net income $58,321 $42,960 $18,775",
            page=7,
            section="Three Months Ended",
            ocr_used=False,
        ),
        ParsedBlock(
            text="Management expects revenue to increase next year.",
            page=7,
            section="Three Months Ended",
            ocr_used=False,
        ),
    ]

    attached = document_loader._attach_table_context(blocks)

    assert [block.content_type for block in attached] == [
        "unverified_table",
        "unverified_table",
        "narrative",
    ]


@pytest.mark.unit
def test_cover_page_period_is_not_mistaken_for_comparative_table_header():
    blocks = [
        ParsedBlock(
            "For the quarterly period ended March 28, 2026",
            1,
            "Page 1",
            False,
        ),
        ParsedBlock("Commission file number 1934", 1, "Page 1", False),
        ParsedBlock("Financial statements follow", 1, "Page 1", False),
        ParsedBlock("Revenue $100 $80", 1, "Page 1", False),
    ]

    attached = document_loader._attach_table_context(blocks)

    assert all(block.table_context is None for block in attached)
    assert all(block.content_type == "narrative" for block in attached)


@pytest.mark.unit
def test_low_text_page_uses_ocr_and_marks_chunk_provenance(
    monkeypatch,
    tmp_path,
):
    pdf_path = tmp_path / "scan.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(pdf_path)

    ocr_calls: list[tuple[int, str, int]] = []

    def fake_ocr(_page, *, page_number, languages, dpi):
        ocr_calls.append((page_number, languages, dpi))
        return [
            "Revenue Overview",
            "OCR recovered multilingual revenue evidence.",
        ]

    monkeypatch.setattr(document_loader, "_extract_ocr_blocks", fake_ocr)

    chunks = load_pdf_chunks(
        pdf_path,
        ocr_enabled=True,
        ocr_languages="eng+chi_sim",
        ocr_dpi=300,
        ocr_min_text_chars=20,
    )

    assert ocr_calls == [(1, "eng+chi_sim", 300)]
    assert chunks[0].page == 1
    assert chunks[0].section == "Revenue Overview"
    assert chunks[0].ocr_used is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "ocr_text",
    [
        (
            "Tesla automotive revenue increased during the quarter, "
            "while operating margin remained stable."
        ),
        "财 务 报 告 显 示 公 司 营 收 和 利 润 持 续 稳 定 增 长",
        (
            "2025 年 Tesla 营 收 增 长 remained strong, with revenue "
            "reaching USD 25.5 billion."
        ),
        "2Q-2025",
        "$12.4",
        "(18.6%)",
        (
            "TESLA SEMI - MEGACHARGER NETWORK PLANNED SITES FOR 2026 "
            "VANCOUVER SEATTLE TACOMA PORTLAND RENO MODESTO "
            "LOS ANGELES PHOENIX"
        ),
    ],
)
def test_ocr_quality_gate_preserves_useful_english_chinese_and_financial_text(
    ocr_text,
):
    assert document_loader._is_usable_ocr_block(ocr_text)


@pytest.mark.unit
@pytest.mark.parametrize(
    "ocr_text",
    [
        "|||| |||| ---- ____ <<<< >>>>",
        "\ufffd\ufffd\ufffd broken OCR text",
        "llllllllllllllllllllllllllllllllllllllll",
        "l I l I l I l I l I l I l I l I l I l I",
        (
            "TESLA SEMI 一 本 有 7 ‘ =. —_— << = son 1 一一 ad — = , "
            "| er| |) me ty | ras | | 外 — | \\"
        ),
        (
            "GIGAFACTORY SHANGHAI - 9 MILLIONTH VEHICLE PRODUCED "
            "(GLOBALLY) - "
            + " | i SS oes ee aye ee — ) | 二) 二 o> Lars | a| 1 em)! "
            * 8
        ),
        (
            "NEXT GENERATION VEHICLE PLATFORM "
            + "= ns! zor2 J 多 3 — es » * 第 一 a | n | 2 | x | "
            * 8
        ),
    ],
)
def test_ocr_quality_gate_rejects_image_derived_character_noise(ocr_text):
    assert not document_loader._is_usable_ocr_block(ocr_text)


@pytest.mark.unit
def test_ocr_quality_gate_filters_only_unusable_blocks():
    useful = (
        "Revenue increased year over year based on the scanned report. "
        "Operating income and free cash flow also improved during the quarter."
    )
    noise = "l | I | l | I | l | I | l | I | l | I | l | I |"

    assert document_loader._filter_ocr_blocks([noise, useful]) == [useful]


@pytest.mark.unit
def test_ocr_quality_gate_rejects_noise_split_across_small_blocks():
    blocks = [
        "TESLA SEMI -—-",
        "_ P Ee 4",
        '= ‘| > =" = ‘ae NG ~ 人',
        '| ”有 | n ,',
        "| fy ‘ iq lf ) on oie . | ) me. oO} ip",
        "| at —",
        "\\",
    ]

    assert document_loader._filter_ocr_blocks(blocks) == []


@pytest.mark.unit
def test_ocr_quality_gate_rechecks_filtered_blocks_as_one_page():
    heading = "GIGAFACTORY SHANGHAI - 9 MILLIONTH VEHICLE PRODUCED"
    fragment = "NA Fx a ie oe ae i vere al x noise"
    blocks = [heading, *([fragment] * 12)]

    assert document_loader._is_usable_ocr_block(fragment)
    assert document_loader._filter_ocr_blocks(blocks) == []


@pytest.mark.unit
def test_ocr_quality_gate_preserves_long_coherent_english_page():
    paragraph = (
        "Revenue increased year over year, supported by automotive sales, "
        "energy generation, storage deployments, and services. "
    )
    page_text = paragraph * 3

    assert len(page_text) >= 200
    assert document_loader._is_usable_ocr_block(page_text)
    assert document_loader._filter_ocr_blocks([page_text]) == [page_text]


@pytest.mark.unit
def test_rejected_ocr_falls_back_to_native_page_text(monkeypatch, tmp_path):
    pdf_path = tmp_path / "native-fallback.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(pdf_path)

    monkeypatch.setattr(
        document_loader,
        "_extract_text_blocks",
        lambda _page: ["Short native financial note retained."],
    )
    monkeypatch.setattr(
        document_loader,
        "_extract_ocr_blocks",
        lambda _page, **_kwargs: [
            "l | I | l | I | l | I | l | I | l | I | l | I |"
        ],
    )

    parsed = parse_pdf(
        pdf_path,
        ocr_enabled=True,
        ocr_min_text_chars=80,
    )

    assert [block.text for block in parsed.pages[0].blocks] == [
        "Short native financial note retained."
    ]
    assert parsed.pages[0].ocr_used is False
    assert parsed.pages[0].blocks[0].ocr_used is False


@pytest.mark.unit
def test_rejected_ocr_on_image_only_pdf_produces_no_content(
    monkeypatch,
    tmp_path,
):
    pdf_path = tmp_path / "image-only.pdf"
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.save(pdf_path)

    monkeypatch.setattr(
        document_loader,
        "_extract_ocr_blocks",
        lambda _page, **_kwargs: ["|||| ---- ____ <<<< >>>>"],
    )

    with pytest.raises(
        DocumentProcessingError,
        match="PDF contains no extractable text",
    ):
        parse_pdf(
            pdf_path,
            ocr_enabled=True,
            ocr_min_text_chars=80,
        )


@pytest.mark.unit
def test_ocr_runtime_failure_has_page_and_language_context():
    class BrokenPage:
        def get_textpage_ocr(self, **_kwargs):
            raise RuntimeError("tesseract data unavailable")

    with pytest.raises(
        DocumentProcessingError,
        match=r"OCR failed on page 3.*eng\+chi_sim.*tesseract data unavailable",
    ):
        document_loader._extract_ocr_blocks(
            BrokenPage(),
            page_number=3,
            languages="eng+chi_sim",
            dpi=300,
        )
