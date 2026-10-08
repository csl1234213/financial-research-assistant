from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import fitz
import pytest
from docx import Document as WordDocument
from openpyxl import Workbook

from agent.reasoning_models import Evidence
from core.fact_ledger import FactLedger
from document_formats import load_structured_document_chunks, validate_document_payload
from document_loader import (
    DocumentChunk,
    DocumentProcessingError,
    _bind_financial_table_row,
    _find_reliable_table_header,
    _has_separated_financial_values,
    get_document_company,
    get_document_period,
    load_document_chunks,
)
from retrieval.hybrid_retriever import HybridRetriever
from retrieval.periods import extract_metrics, extract_periods
from retrieval.retrieval_context import RetrievalContext
from storage.vector_models import SearchResult


@pytest.mark.unit
def test_xlsx_preserves_financial_row_header_units_and_sheet_locator(tmp_path: Path):
    path = tmp_path / "filing.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Income Statement"
    sheet.append(["NVIDIA Corporation"])
    sheet.append(["Three months ended", "June 30, 2026", "June 30, 2025"])
    sheet.append(["Metric", "Q2 FY2027", "Q2 FY2026"])
    sheet.append(["Revenue", "$46.7 billion", "$30.0 billion"])
    workbook.save(path)
    workbook.close()

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)

    assert chunks
    content = "\n".join(chunk.text for chunk in chunks)
    assert "Revenue" in content
    assert "$46.7 billion" in content
    assert "Q2 FY2027" in content
    assert "June 30, 2026" in content
    assert "Financial table row — Metric: Revenue | Q2 FY2027: $46.7 billion | Q2 FY2026: $30.0 billion" in content
    assert chunks[0].source_format.endswith("spreadsheetml.sheet")
    assert all(chunk.page == 0 for chunk in chunks)
    assert any("Income Statement" in (chunk.source_locator or "") for chunk in chunks)


@pytest.mark.unit
def test_xlsx_merged_period_header_quarantines_nearby_financial_rows(tmp_path: Path):
    path = tmp_path / "merged-period-header.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Metric", "Q2 FY2026", "Q2 FY2025"])
    sheet.merge_cells("B1:C1")
    sheet.append(["Total revenue", "111,184", "95,359"])
    workbook.save(path)
    workbook.close()

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)
    revenue_row = next(chunk for chunk in chunks if "Total revenue" in chunk.text)

    assert revenue_row.content_type == "unverified_table"
    evidence = Evidence(
        content=revenue_row.text,
        source=path.name,
        company="Apple",
        metadata={"content_type": revenue_row.content_type},
    )
    assert not FactLedger.from_evidence([evidence]).facts


@pytest.mark.unit
def test_xlsx_streaming_parser_keeps_rows_after_large_blank_gap(tmp_path: Path):
    path = tmp_path / "sparse-used-range.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Metric", "Q2 FY2026", "Q2 FY2025"])
    sheet.append(["Revenue", "111,184", "95,359"])
    sheet["A702"] = "Net income"
    sheet["B702"] = "29,578"
    sheet["C702"] = "24,780"
    # A stale spreadsheet used range can extend well past its real data.
    # Keep the distant blank-like cell so ingestion proves it still streams
    # rows beyond large gaps rather than silently truncating the sheet.
    sheet["A12000"] = " "
    workbook.save(path)
    workbook.close()

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)
    content = "\n".join(chunk.text for chunk in chunks)

    assert "Row 702: A=Net income" in content
    assert "B=29,578" in content
    assert "C=24,780" in content
    assert any(
        chunk.source_locator and "row 702" in chunk.source_locator
        for chunk in chunks
    )


@pytest.mark.unit
def test_xlsx_repeated_period_header_quarantines_numeric_row(tmp_path: Path):
    path = tmp_path / "ambiguous.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Metric", "Q2 FY2026", "Q2 FY2026"])
    sheet.append(["Revenue", "$46.7 billion", "$30.0 billion"])
    workbook.save(path)
    workbook.close()

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)

    row = next(chunk for chunk in chunks if "Revenue" in chunk.text)
    assert row.content_type == "unverified_table"


@pytest.mark.unit
def test_xlsx_formula_without_cached_value_is_never_treated_as_numeric_evidence(tmp_path: Path):
    path = tmp_path / "model.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Metric", "Value"])
    sheet.append(["Revenue", "=SUM(B3:B4)"])
    sheet.append(["Quarter 1", 10])
    sheet.append(["Quarter 2", 20])
    workbook.save(path)
    workbook.close()

    content = "\n".join(chunk.text for chunk in load_structured_document_chunks(path, chunk_size=4_000, overlap=0))

    assert "FORMULA_WITHOUT_CACHED_RESULT (not numeric evidence)" in content
    assert "Revenue: 30" not in content


@pytest.mark.unit
def test_docx_table_keeps_metric_to_period_and_value_binding(tmp_path: Path):
    path = tmp_path / "report.docx"
    document = WordDocument()
    document.add_heading("Apple Inc. Quarterly Results", level=1)
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ("Metric", "Q1 FY2026", "Q1 FY2025"), strict=True):
        cell.text = value
    row = table.add_row().cells
    for cell, value in zip(row, ("Revenue", "$95.4 billion", "$90.8 billion"), strict=True):
        cell.text = value
    document.save(path)

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)
    content = "\n".join(chunk.text for chunk in chunks)

    assert "Metric: Revenue" in content
    assert "Q1 FY2026: $95.4 billion" in content
    assert "Q1 FY2025: $90.8 billion" in content
    assert any("DOCX table 1, row 2" in (chunk.source_locator or "") for chunk in chunks)


def test_segment_metrics_normalize_consistently_across_report_formats(tmp_path: Path):
    formats: dict[str, Path] = {}

    pdf_path = tmp_path / "nvidia-segments.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    for y, text in zip(
        (72, 96, 120, 144, 168),
        (
            "NVIDIA Q1 FY2027",
            "Data Center",
            "First-quarter revenue was $75.2 billion.",
            "Edge Computing",
            "First-quarter revenue was $6.4 billion.",
        ),
        strict=True,
    ):
        page.insert_text((72, y), text)
    pdf.save(pdf_path)
    pdf.close()
    formats["pdf"] = pdf_path

    xlsx_path = tmp_path / "nvidia-segments.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Business Segments"
    sheet.append(["Metric", "Q1 FY2027"])
    sheet.append(["Data Center revenue", "$75.2 billion"])
    sheet.append(["Edge Computing revenue", "$6.4 billion"])
    workbook.save(xlsx_path)
    workbook.close()
    formats["xlsx"] = xlsx_path

    docx_path = tmp_path / "nvidia-segments.docx"
    word = WordDocument()
    word.add_heading("NVIDIA Q1 FY2027", level=1)
    table = word.add_table(rows=1, cols=2)
    for cell, value in zip(table.rows[0].cells, ("Metric", "Q1 FY2027"), strict=True):
        cell.text = value
    for label, amount in (
        ("Data Center revenue", "$75.2 billion"),
        ("Edge Computing revenue", "$6.4 billion"),
    ):
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = amount
    word.save(docx_path)
    formats["docx"] = docx_path

    csv_path = tmp_path / "nvidia-segments.csv"
    csv_path.write_text(
        "Metric,Q1 FY2027\nData Center revenue,$75.2 billion\nEdge Computing revenue,$6.4 billion\n",
        encoding="utf-8",
    )
    formats["csv"] = csv_path

    normalized: dict[str, dict[str, list[Decimal]]] = {}
    for format_name, path in formats.items():
        chunks = load_document_chunks(path, chunk_size=4_000, overlap=0, ocr_enabled=False)
        evidence = [
            Evidence(
                content=chunk.text,
                source=path.name,
                company="NVIDIA",
                metadata={
                    "chunk_id": str(chunk.chunk_index),
                    "quarter": "Q1_FY2027",
                    "content_type": chunk.content_type,
                    "table_context": chunk.table_context or "",
                    "section": chunk.section,
                },
            )
            for chunk in chunks
            if chunk.content_type != "unverified_table"
        ]
        ledger = FactLedger.from_evidence(evidence)
        normalized[format_name] = {
            metric: [
                fact.normalized_value
                for fact in ledger.lookup(
                    company="NVIDIA",
                    metric_id=metric,
                    period="Q1_FY2027",
                )
            ]
            for metric in ("data_center_revenue", "edge_computing_revenue")
        }

    expected = {
        "data_center_revenue": [Decimal("75200000000")],
        "edge_computing_revenue": [Decimal("6400000000")],
    }
    assert normalized == {format_name: expected for format_name in formats}


@pytest.mark.unit
def test_docx_ragged_comparative_row_is_quarantined(tmp_path: Path):
    path = tmp_path / "ragged.docx"
    document = WordDocument()
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ("Metric", "Q2 FY2026", "Q2 FY2025"), strict=True):
        cell.text = value
    row = table.add_row().cells
    for cell, value in zip(row, ("Revenue", "$46.7 billion", ""), strict=True):
        cell.text = value
    document.save(path)

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)

    assert len(chunks) == 1
    assert chunks[0].content_type == "unverified_table"


@pytest.mark.unit
def test_docx_unit_note_is_carried_to_rows_outside_the_text_chunk(tmp_path: Path):
    path = tmp_path / "unit-context.docx"
    document = WordDocument()
    document.add_heading("Apple Inc. Quarterly Results", level=1)
    document.add_paragraph(
        "Amounts are stated in millions, except share data in thousands."
    )
    for index in range(12):
        document.add_paragraph(f"Non-financial disclosure paragraph {index} " + "detail " * 20)
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(
        table.rows[0].cells,
        ("Metric", "Q2 FY2026", "Q2 FY2025"),
        strict=True,
    ):
        cell.text = value
    row = table.add_row().cells
    for cell, value in zip(row, ("Total net sales", "111,184", "95,359"), strict=True):
        cell.text = value
    document.save(path)

    chunks = load_document_chunks(path, chunk_size=96, overlap=0)
    row_chunk = next(chunk for chunk in chunks if "Metric: Total net sales" in chunk.text)
    evidence = Evidence(
        content=row_chunk.text,
        source=path.name,
        company="Apple",
        metadata={
            "chunk_id": str(row_chunk.chunk_index),
            "content_type": row_chunk.content_type,
            "table_context": row_chunk.table_context,
        },
    )
    facts = FactLedger.from_evidence([evidence]).lookup(
        company="Apple",
        metric_id="revenue",
        period="Q2_FY2026",
    )

    assert "in millions" in (row_chunk.table_context or "").casefold()
    assert row_chunk.parser_version == "docx-python-docx-structured-v3"
    assert [fact.normalized_value for fact in facts] == [111_184_000_000]


@pytest.mark.unit
def test_docx_merged_financial_value_row_is_quarantined(tmp_path: Path):
    path = tmp_path / "merged-financial-row.docx"
    document = WordDocument()
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(
        table.rows[0].cells,
        ("Metric", "Q2 FY2026", "Q2 FY2025"),
        strict=True,
    ):
        cell.text = value
    row = table.add_row().cells
    row[0].text = "Revenue"
    row[1].text = "$46.7 billion"
    row[1].merge(row[2])
    document.save(path)

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)
    merged_row = next(chunk for chunk in chunks if "Revenue" in chunk.text)
    evidence = Evidence(
        content=merged_row.text,
        source=path.name,
        company="NVIDIA",
        metadata={
            "chunk_id": str(merged_row.chunk_index),
            "content_type": merged_row.content_type,
            "table_context": merged_row.table_context,
        },
    )

    assert merged_row.content_type == "unverified_table"
    assert not FactLedger.from_evidence([evidence]).facts


@pytest.mark.unit
def test_docx_merged_title_row_does_not_quarantine_unmerged_period_data(tmp_path: Path):
    path = tmp_path / "merged-title.docx"
    document = WordDocument()
    table = document.add_table(rows=1, cols=3)
    table.rows[0].cells[0].merge(table.rows[0].cells[2])
    table.rows[0].cells[0].text = "Consolidated statements of operations"
    header = table.add_row().cells
    for cell, value in zip(header, ("Metric", "Q2 FY2026", "Q2 FY2025"), strict=True):
        cell.text = value
    row = table.add_row().cells
    for cell, value in zip(row, ("Total net sales", "111,184", "95,359"), strict=True):
        cell.text = value
    document.save(path)

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)
    fact_row = next(chunk for chunk in chunks if "Metric: Total net sales" in chunk.text)

    assert fact_row.content_type == "table"
    assert "Q2 FY2026: 111,184" in fact_row.text


@pytest.mark.unit
def test_equivalent_financial_table_values_match_across_supported_formats(tmp_path: Path):
    headers = ["Metric", "Q2 FY2026", "Q2 FY2025"]
    rows = [
        ["Total net sales", "111,184", "95,359"],
        ["Net income", "29,578", "24,780"],
    ]

    pdf_path = tmp_path / "apple.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=600, height=300)
        page.insert_text((60, 55), "Apple Inc. Quarterly Results (in millions)", fontsize=10)
        table_rows = [headers, *rows]
        left, top, cell_width, cell_height = 60, 85, 170, 36
        for row_index, row in enumerate(table_rows):
            y0 = top + row_index * cell_height
            y1 = y0 + cell_height
            page.draw_line((left, y0), (left + len(row) * cell_width, y0))
            page.draw_line((left, y1), (left + len(row) * cell_width, y1))
            for column_index, value in enumerate(row):
                x0 = left + column_index * cell_width
                x1 = x0 + cell_width
                page.draw_line((x0, y0), (x0, y1))
                page.draw_line((x1, y0), (x1, y1))
                page.insert_text((x0 + 6, y0 + 22), value, fontsize=10)
        pdf.save(pdf_path)

    xlsx_path = tmp_path / "apple.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Apple Inc. Quarterly Results (in millions)"])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(xlsx_path)
    workbook.close()

    docx_path = tmp_path / "apple.docx"
    word_document = WordDocument()
    word_document.add_heading("Apple Inc. Quarterly Results (in millions)", level=1)
    table = word_document.add_table(rows=1, cols=len(headers))
    for cell, value in zip(table.rows[0].cells, headers, strict=True):
        cell.text = value
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row, strict=True):
            cell.text = value
    word_document.save(docx_path)

    csv_path = tmp_path / "apple.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Apple Inc. Quarterly Results (in millions)"])
        writer.writerow(headers)
        writer.writerows(rows)

    def extracted_facts(path: Path) -> set[tuple[str, str | None, str, str | None, str]]:
        chunks = load_document_chunks(path, chunk_size=4_000, overlap=0, ocr_enabled=False)
        evidence = [
            Evidence(
                content=chunk.text,
                source=path.name,
                company="Apple",
                metadata={
                    "content_type": chunk.content_type,
                    "table_context": chunk.table_context or "",
                    "page": chunk.page,
                    "section": chunk.section,
                    "chunk_id": str(chunk.chunk_index),
                },
            )
            for chunk in chunks
            if chunk.content_type != "unverified_table"
        ]
        ledger = FactLedger.from_evidence(evidence)
        return {
            (
                fact.metric_id,
                fact.fact_period,
                str(fact.normalized_value),
                fact.currency,
                fact.unit,
            )
            for fact in ledger.facts
            if fact.metric_id in {"revenue", "net_income"}
        }

    expected = {
        ("revenue", "Q2_FY2026", "111184000000", "usd", "billion"),
        ("revenue", "Q2_FY2025", "95359000000", "usd", "billion"),
        ("net_income", "Q2_FY2026", "29578000000", "usd", "billion"),
        ("net_income", "Q2_FY2025", "24780000000", "usd", "billion"),
    }
    class _Embedding(list):
        def tolist(self):
            return list(self)

    class _EmbeddingModel:
        def encode(self, _query, **_kwargs):
            return _Embedding([0.1, 0.2])

    class _Store:
        def __init__(self, results):
            self.results = results

        def similarity_search(self, *, query_embedding, top_k, tenant_id):
            del query_embedding, tenant_id
            return self.results[:top_k]

        def lexical_corpus(self, tenant_id=None):
            del tenant_id
            return self.results

    questions = (
        "What were Apple's Q2 FY2026 net sales and net income?",
        "苹果 2026 财年第二季度的净销售额和净利润是多少？",
    )
    for path in (pdf_path, xlsx_path, docx_path, csv_path):
        assert extracted_facts(path) == expected, path.suffix

        chunks = load_document_chunks(path, chunk_size=4_000, overlap=0, ocr_enabled=False)
        search_results = [
            SearchResult(
                document_id=path.name,
                chunk_id=f"{path.suffix}-{chunk.chunk_index}",
                score=1.0 - chunk.chunk_index / max(len(chunks), 1_000),
                content=chunk.text,
                metadata={
                    "tenant_id": 0,
                    "company": "Apple",
                    "source": path.name,
                    "page": chunk.page,
                    "section": chunk.section,
                    "content_type": chunk.content_type,
                    "table_context": chunk.table_context or "",
                    "source_locator": chunk.source_locator or "",
                    "periods": "|".join(
                        extract_periods(f"{chunk.table_context or ''}\n{chunk.text}")
                    ),
                    "metrics": "|".join(extract_metrics(chunk.text)),
                },
            )
            for chunk in chunks
        ]
        retriever = HybridRetriever(_EmbeddingModel())
        store = _Store(search_results)

        for question in questions:
            retrieved = retriever.retrieve(
                RetrievalContext(
                    question=question,
                    company="Apple",
                    top_k=8,
                    tenant_id=0,
                ),
                store,
            )
            evidence = [
                Evidence(
                    content=item.content,
                    source=item.metadata["source"],
                    company=item.metadata["company"],
                    metadata={**item.metadata, "chunk_id": item.chunk_id},
                )
                for item in retrieved
            ]
            retrieved_ledger = FactLedger.from_evidence(evidence)
            for metric_id, expected_value in (
                ("revenue", Decimal("111184000000")),
                ("net_income", Decimal("29578000000")),
            ):
                facts = retrieved_ledger.lookup(
                    company="Apple",
                    metric_id=metric_id,
                    period="Q2_FY2026",
                )
                assert any(fact.normalized_value == expected_value for fact in facts), (
                    path.suffix,
                    question,
                    metric_id,
                    [item.chunk_id for item in retrieved],
                )
                locator_by_chunk = {
                    item.metadata["chunk_id"]: item.metadata["source_locator"]
                    for item in evidence
                    if item.metadata.get("source_locator")
                }
                assert any(
                    locator_by_chunk.get(fact.chunk_id)
                    for fact in facts
                    if fact.normalized_value == expected_value
                ), (path.suffix, metric_id, "fact lost its source locator")


@pytest.mark.unit
def test_csv_rows_are_header_labeled_instead_of_flattened(tmp_path: Path):
    path = tmp_path / "results.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Metric", "Q2 2025", "Q2 2024", "Unit"])
        writer.writerow(["Automotive revenue", "20.7", "19.9", "USD billions"])

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)
    content = "\n".join(chunk.text for chunk in chunks)

    assert "Metric: Automotive revenue" in content
    assert "Q2 2025: 20.7" in content
    assert "Q2 2024: 19.9" in content
    assert "Unit: USD billions" in content
    assert "CSV row 2" in (chunks[0].source_locator or "")


@pytest.mark.unit
def test_csv_multirow_comparative_header_maps_by_exact_period_columns(tmp_path: Path):
    path = tmp_path / "multirow.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Financial results", "", ""])
        writer.writerow(["Metric", "Q2 FY2026", "Q2 FY2025"])
        writer.writerow(["Revenue", "$46.7 billion", "$30.0 billion"])

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)
    content = "\n".join(chunk.text for chunk in chunks)

    assert "Metric: Revenue | Q2 FY2026: $46.7 billion | Q2 FY2025: $30.0 billion" in content
    assert "CSV row 3" in (chunks[0].source_locator or "")
    assert all(chunk.content_type == "table" for chunk in chunks)


@pytest.mark.unit
def test_csv_repeated_period_labels_do_not_prove_column_mapping(tmp_path: Path):
    path = tmp_path / "ambiguous.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Metric", "Q2 FY2026", "Q2 FY2026"])
        writer.writerow(["Revenue", "$46.7 billion", "$30.0 billion"])

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0)

    assert len(chunks) == 1
    assert chunks[0].content_type == "unverified_table"


@pytest.mark.unit
def test_report_company_and_period_are_derived_from_content_not_filename():
    chunks = [
        DocumentChunk(
            text="Apple Inc. Quarterly Results for Q1 FY2026. Revenue increased.",
            page=1,
            section="Cover",
            ocr_used=False,
            chunk_index=0,
        )
    ]

    assert get_document_company(chunks) == "Apple"
    assert get_document_period(chunks) == "Q1_FY2026"


@pytest.mark.unit
def test_ambiguous_company_or_period_is_not_promoted_to_authoritative_metadata():
    chunks = [
        DocumentChunk(
            text=(
                "Apple Inc. and NVIDIA Corporation comparison for Q1 FY2026 and Q2 FY2026."
            ),
            page=1,
            section="Cover",
            ocr_used=False,
            chunk_index=0,
        )
    ]

    assert get_document_company(chunks) == "Unknown"
    assert get_document_period(chunks) == "Unknown"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename_hint", "content", "expected"),
    [
        ("Tesla", "Tesla Q4 and FY2025 Update. Tesla reported revenue.", "Tesla"),
        ("NVIDIA", "NVIDIA Announces Financial Results for Q1 FY2027.", "NVIDIA"),
        ("Tesla", "Apple Inc. Quarterly Report for Q1 FY2026.", "Unknown"),
        (
            "Apple",
            "Apple Inc. and NVIDIA Corporation comparative report.",
            "Unknown",
        ),
    ],
)
def test_company_hint_must_match_a_unique_issuer_in_document_content(
    filename_hint: str,
    content: str,
    expected: str,
):
    chunks = [
        DocumentChunk(
            text=content,
            page=1,
            section="Cover",
            ocr_used=False,
            chunk_index=0,
        )
    ]

    assert get_document_company(chunks, filename_hint=filename_hint) == expected


@pytest.mark.unit
def test_sec_registrant_field_takes_precedence_over_exchange_entities():
    chunks = [
        DocumentChunk(
            text=(
                "Example Technologies, Inc. (Exact name of Registrant as specified in its charter) "
                "Common stock listed on The Nasdaq Stock Market LLC."
            ),
            page=1,
            section="Cover",
            ocr_used=False,
            chunk_index=0,
        )
    ]

    assert get_document_company(chunks) == "Example Technologies"


@pytest.mark.unit
def test_pdf_table_rows_need_explicit_period_columns_and_separated_values():
    rows = [
        ["($ in millions)", "Q4-2024", "Q4-2025", "YoY"],
        ["Revenue", "100", "125", "25%"],
    ]

    assert _find_reliable_table_header(rows) == 0
    assert _has_separated_financial_values(rows[1])
    assert not _has_separated_financial_values(["Revenue 100 125", "25%"])
    assert _find_reliable_table_header([["Revenue", "100", "125"]]) is None


@pytest.mark.unit
def test_pdf_table_row_binds_values_to_exact_source_period_headers():
    rendered = _bind_financial_table_row(
        ["Metric", "Q1 FY2026", "Q1 FY2025"],
        ["Revenue", "$81.6 billion", "$44.1 billion"],
    )

    assert rendered == (
        "Metric: Revenue | Q1 FY2026: $81.6 billion | Q1 FY2025: $44.1 billion"
    )

    unit_header_rendered = _bind_financial_table_row(
        ["($ in millions, except percentages)", "Q2-2025", "Q2-2024"],
        ["Total automotive revenues", "16,661", "19,900"],
    )
    assert unit_header_rendered == (
        "Metric: Total automotive revenues | Q2-2025: 16,661 | Q2-2024: 19,900"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("header", "row"),
    [
        # Ragged rows can reflect merged cells or extraction-induced shifts.
        (["Metric", "Q1 FY2026", "Q1 FY2025"], ["Revenue", "81.6"]),
        # Do not assign an unlabeled numeric cell to an inferred period.
        (["Metric", "Q1 FY2026", "Q1 FY2025", ""], ["Revenue", "81.6", "44.1", "12"]),
        # Two figures collapsed into one cell do not prove column order.
        (["Metric", "Q1 FY2026", "Q1 FY2025"], ["Revenue", "81.6 44.1", ""]),
        # A single period plus an unrelated year is not a comparative map.
        (["Metric", "Q1 FY2026", "Notes"], ["Revenue", "81.6", "44.1"]),
    ],
)
def test_pdf_table_row_is_not_promoted_when_column_mapping_is_ambiguous(header, row):
    assert _bind_financial_table_row(header, row) is None


@pytest.mark.unit
def test_pdf_structured_table_rows_preserve_source_period_header(tmp_path: Path):
    path = tmp_path / "statement.pdf"
    rows = [
        ["Metric", "Q1 FY2026", "Q1 FY2025"],
        ["Revenue", "$81.6 billion", "$44.1 billion"],
        ["Net income", "$58.3 billion", "$18.8 billion"],
    ]
    with fitz.open() as document:
        page = document.new_page(width=600, height=800)
        left, top, cell_width, cell_height = 60, 100, 160, 36
        for row_index, row in enumerate(rows):
            y0 = top + row_index * cell_height
            y1 = y0 + cell_height
            page.draw_line((left, y0), (left + len(row) * cell_width, y0))
            page.draw_line((left, y1), (left + len(row) * cell_width, y1))
            for col_index, value in enumerate(row):
                x0 = left + col_index * cell_width
                x1 = x0 + cell_width
                page.draw_line((x0, y0), (x0, y1))
                page.draw_line((x1, y0), (x1, y1))
                page.insert_text((x0 + 6, y0 + 22), value, fontsize=10)
        document.save(path)

    chunks = load_document_chunks(path, chunk_size=4_000, overlap=0, ocr_enabled=False)
    table_chunks = [chunk for chunk in chunks if "Structured financial table row" in chunk.text]

    assert table_chunks
    assert any("Q1 FY2026" in chunk.text and "$81.6 billion" in chunk.text for chunk in table_chunks)
    assert any("Q1 FY2026: $81.6 billion" in chunk.text for chunk in table_chunks)
    assert any("Q1 FY2025: $44.1 billion" in chunk.text for chunk in table_chunks)
    assert any("PDF page 1, table 1, row" in (chunk.source_locator or "") for chunk in table_chunks)
    assert all(chunk.page == 1 for chunk in table_chunks)


@pytest.mark.unit
def test_apple_sample_quarantines_region_values_when_period_header_is_missing():
    source = Path(__file__).resolve().parents[1] / "demo" / "documents" / "Apple_sample.pdf"
    if not source.exists():
        pytest.skip("The public Apple sample filing is not included in this checkout")

    chunks = load_document_chunks(
        source,
        chunk_size=4_000,
        overlap=0,
        ocr_enabled=False,
    )
    flattened_region_rows = [
        chunk
        for chunk in chunks
        if chunk.page == 15
        and any(value in chunk.text for value in ("92,963", "38,283"))
    ]
    assert flattened_region_rows
    assert any("92,963" in chunk.text and "38,283" in chunk.text for chunk in flattened_region_rows)
    assert all(chunk.content_type == "unverified_table" for chunk in flattened_region_rows)

    # The corresponding later table still has explicit quarter and YTD
    # periods, so quarantine does not disable properly mapped table evidence.
    structured_rows = [
        chunk
        for chunk in chunks
        if chunk.page == 17
        and "Structured financial table row" in chunk.text
        and "Metric: Total net sales" in chunk.text
    ]
    assert structured_rows
    assert "Q2 FY2026 (three months ended March 28 2026)" in structured_rows[0].text
    assert "YTD Q2 FY2026 (six months ended March 28 2026)" in structured_rows[0].text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("disguised.xlsx", b"%PDF-1.4\n%%EOF"),
        ("report.docx", b"not a zip archive"),
        ("report.xls", b"legacy workbook"),
        ("report.csv", b"\xff\xfe"),
    ],
)
def test_upload_validation_fails_closed_for_bad_or_unsupported_formats(filename, content):
    with pytest.raises(DocumentProcessingError):
        validate_document_payload(filename, content)
