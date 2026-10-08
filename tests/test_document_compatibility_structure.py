"""Real PDF geometry through PyMuPDF; fault injection changes output, not status."""

from dataclasses import replace

import fitz
import pytest

from document_compatibility.adapters import extract_inventory
from document_compatibility.engine import audit_document, build_chunks, inspect_pdf, serialize_blocks
from document_compatibility.models import DocumentState, FailureClass
from document_compatibility.policy import DEFAULT_POLICY, POLICIES


def merged_pdf(path, *, mode="legal", issuer="Example", context=True, amount="100"):
    with fitz.open() as pdf:
        page = pdf.new_page(width=520, height=400)
        page.insert_text(
            (30, 40), f"{issuer} " + ("Consolidated financial schedule" if context else "Financial schedule")
        )
        if context:
            page.insert_text((30, 70), "USD in millions")
        xs, ys = [30, 210, 330, 450], [120, 150, 180, 210, 240, 270]
        for yi, y in enumerate(ys):
            for col in range(3):
                if yi == 1 and col == 0:  # Vertically merged label header.
                    continue
                if mode == "vertical" and yi == 4 and col == 1:
                    continue
                page.draw_line((xs[col], y), (xs[col + 1], y))
        for xi, x in enumerate(xs):
            for row in range(5):
                if xi in (1, 2) and row == 2:  # Legal full-width category label.
                    continue
                if xi == 2 and row == 0:  # Legal parent heading.
                    continue
                if xi == 2 and row == 3 and mode == "horizontal":
                    continue
                page.draw_line((x, ys[row]), (x, ys[row + 1]))
        entries = [
            (35, 140, "Metric"),
            (215, 140, "Reported amounts"),
            (215, 170, "2025"),
            (335, 170, "2024"),
            (35, 200, "Operating assets"),
            (35, 230, "Assets"),
            (215, 230, amount),
            (35, 260, "Inventory"),
            (335, 260, "15"),
        ]
        if mode != "horizontal":
            entries.append((335, 230, "90"))
        if mode != "vertical":
            entries.append((215, 260, "20"))
        for x, y, text in entries:
            page.insert_text(
                (x, y), text, fontsize=10, fontname="china-s" if any(ord(c) > 255 for c in text) else "helv"
            )
        pdf.save(path)


def multicolumn_pdf(path):
    with fitz.open() as pdf:
        page = pdf.new_page(width=700, height=800)
        for x, y, marker in [
            (40, 100, "LEFTFIRST"),
            (380, 120, "RIGHTFIRST"),
            (40, 270, "LEFTSECOND"),
            (380, 290, "RIGHTSECOND"),
        ]:
            text = (
                f"{marker} describes the operating strategy and business environment. "
                "Management explains its research plans and the operational assumptions for this business."
            )
            assert page.insert_textbox(fitz.Rect(x, y, x + 270, y + 110), text, fontsize=11) > 0
        pdf.save(path)


def run_structural_case(name, tmp_path, policy=DEFAULT_POLICY):
    path = tmp_path / f"{name}.pdf"
    if name.startswith("real-multicolumn"):
        multicolumn_pdf(path)
        inventory = extract_inventory(path, policy)
        if name.endswith("interleaved"):
            inventory = replace(
                inventory,
                canonical_blocks=tuple(sorted(inventory.canonical_blocks, key=lambda b: b.bbox[1] if b.bbox else 0)),
            )
    else:
        mode = name.removeprefix("real-merged-") if name.startswith("real-merged-") else "legal"
        merged_pdf(path, mode=mode)
        inventory = extract_inventory(path, policy)
        if name.startswith("real-context-"):
            kind = FailureClass(name.removeprefix("real-context-").upper() + "_CONTEXT_LOSS")
            source_ids = {r.source_id for r in inventory.context_requirements if r.failure_class == kind}
            inventory = replace(
                inventory,
                canonical_blocks=tuple(
                    replace(b, context_source_ids=tuple(s for s in b.context_source_ids if s not in source_ids))
                    for b in inventory.canonical_blocks
                ),
            )
    return audit_document(inventory, policy=policy)


@pytest.mark.parametrize("mode", ["legal", "horizontal", "vertical"])
@pytest.mark.parametrize("issuer", ["Alpha", "Beta"])
def test_real_merged_cells_preserve_geometry_and_quarantine_amount_ambiguity(tmp_path, mode, issuer):
    path = tmp_path / "merged.pdf"
    merged_pdf(path, mode=mode, issuer=issuer)
    inventory, report = inspect_pdf(path)
    cells = [cell for b in report.blocks for cell in b.table_cells]
    assert any(c.row_span > 1 for c in cells)
    assert any(c.column_span > 1 for c in cells)
    detected = {f.failure_class for f in report.failures}
    assert "COMPLEX_TABLE_REPORT" in report.profile.format_families
    if mode == "legal":
        assert report.state == DocumentState.READY, report.failures
        assert FailureClass.MERGED_CELL_AMBIGUITY not in detected
    else:
        assert report.state == DocumentState.QUARANTINED
        assert FailureClass.MERGED_CELL_AMBIGUITY in detected
        assert report.pages[0].table_status == "FAIL"
        assert any(dict(f.features).get("bbox") for f in report.failures)
    # Geometry is retained, not an inferred duplicated financial amount.
    assert sum(c.text == "100" for c in cells) == 1
    assert not inventory.parsed_document.financial_table_rows


def test_real_multicolumn_order_and_interleaved_output_detection(tmp_path):
    good = run_structural_case("real-multicolumn-ordered", tmp_path)
    assert good.state == DocumentState.READY, good.failures
    assert "MULTICOLUMN_REPORT" in good.profile.format_families
    text = "\n".join(b.text for b in good.blocks)
    offsets = [text.index(t) for t in ("LEFTFIRST", "LEFTSECOND", "RIGHTFIRST", "RIGHTSECOND")]
    assert offsets == sorted(offsets)
    bad = run_structural_case("real-multicolumn-interleaved", tmp_path)
    assert bad.state == DocumentState.QUARANTINED
    assert FailureClass.MULTICOLUMN_READING_ORDER_ERROR in {f.failure_class for f in bad.failures}
    assert bad.pages[0].reading_order_status == "FAIL"


@pytest.mark.parametrize("kind", ["period", "unit", "scope"])
def test_real_source_context_must_remain_bound_to_its_table(tmp_path, kind):
    report = run_structural_case(f"real-context-{kind}", tmp_path)
    assert report.state == DocumentState.QUARANTINED
    assert FailureClass(kind.upper() + "_CONTEXT_LOSS") in {f.failure_class for f in report.failures}


def test_absent_source_context_is_not_reported_as_parser_loss(tmp_path):
    path = tmp_path / "missing-source-context.pdf"
    merged_pdf(path, context=False)
    inventory, report = inspect_pdf(path)
    assert report.state == DocumentState.READY, report.failures
    assert not any(
        r.failure_class in (FailureClass.UNIT_CONTEXT_LOSS, FailureClass.SCOPE_CONTEXT_LOSS)
        for r in inventory.context_requirements
    )


def test_context_is_serialized_and_carried_into_chunks(tmp_path):
    path = tmp_path / "context.pdf"
    merged_pdf(path)
    inventory = extract_inventory(path, DEFAULT_POLICY)
    table = next(b for b in inventory.canonical_blocks if b.table_cells)
    assert {r.failure_class for r in inventory.context_requirements} == {
        FailureClass.PERIOD_CONTEXT_LOSS,
        FailureClass.UNIT_CONTEXT_LOSS,
        FailureClass.SCOPE_CONTEXT_LOSS,
    }
    output = serialize_blocks(inventory.canonical_blocks)
    assert "USD in millions" in output[table.block_id]
    assert "Consolidated" in output[table.block_id]
    chunks, discards = build_chunks(inventory.canonical_blocks)
    broken = tuple(replace(c, text=table.text) if table.block_id in c.source_block_ids else c for c in chunks)
    report = audit_document(inventory, chunks=broken, discards=discards)
    assert FailureClass.CHUNK_BLOCK_LOSS in {f.failure_class for f in report.failures}


def test_v3_is_versioned_and_does_not_rewrite_old_policy(tmp_path):
    assert DEFAULT_POLICY.version == "financial-pdf-v4"
    assert DEFAULT_POLICY.prove_native_merged_regions
    assert not POLICIES["financial-pdf-v3"].prove_native_merged_regions
    assert not POLICIES["financial-pdf-v2"].audit_geometry_context
    old = run_structural_case("real-multicolumn-interleaved", tmp_path, POLICIES["financial-pdf-v2"])
    new = run_structural_case("real-multicolumn-interleaved", tmp_path)
    assert old.state == DocumentState.READY
    assert new.state == DocumentState.QUARANTINED


def test_chunk_reordering_cannot_bypass_multicolumn_guard(tmp_path):
    path = tmp_path / "columns.pdf"
    multicolumn_pdf(path)
    inventory = extract_inventory(path, DEFAULT_POLICY)
    chunks, discards = build_chunks(inventory.canonical_blocks)
    assert audit_document(inventory, chunks=chunks).state == DocumentState.READY
    report = audit_document(inventory, chunks=tuple(reversed(chunks)), discards=discards)
    assert report.state == DocumentState.QUARANTINED
    assert FailureClass.MULTICOLUMN_READING_ORDER_ERROR in {f.failure_class for f in report.failures}


def contextual_tables_pdf(path, *, continuation=False, chinese=False):
    with fitz.open() as pdf:
        page = pdf.new_page(width=500, height=800)
        for index in range(2):
            offset = 0 if continuation else index * 340
            if continuation and index:
                page = pdf.new_page(width=500, height=800)
            if chinese:
                title = "合并资产负债表" if index == 0 else "母公司资产负债表"
                unit = "单位：人民币万元" if index == 0 else "单位：人民币元"
                font = "china-s"
            else:
                title = "Consolidated Financial Schedule" if index == 0 else "Parent company Financial Schedule"
                unit = "USD in millions" if index == 0 else "USD in thousands"
                font = "helv"
            if continuation and index:
                title = "Consolidated Financial Schedule (continued)"
            page.insert_text((30, offset + 40), title, fontname=font)
            if not (continuation and index):
                page.insert_text((30, offset + 65), unit, fontname=font)
            xs, ys = [30, 210, 330, 450], [offset + y for y in (100, 130, 160, 190)]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            rows = [["Metric", "2025", "2024"], ["Assets", "100", "90"], ["Cash", "50", "40"]]
            if continuation and index:
                rows = [["Equipment", "30", "20"], ["Inventory", "10", "8"], ["Receivables", "10", "12"]]
            for r, values in enumerate(rows):
                for c, value in enumerate(values):
                    page.insert_text((xs[c] + 5, ys[r] + 20), value)
        pdf.save(path)


@pytest.mark.parametrize("chinese", [False, True])
def test_context_is_bound_per_table_not_by_page_presence(tmp_path, chinese):
    path = tmp_path / "two-tables.pdf"
    contextual_tables_pdf(path, chinese=chinese)
    inventory, good = inspect_pdf(path)
    assert good.state == DocumentState.READY, good.failures
    tables = [b for b in inventory.canonical_blocks if b.table_cells]
    assert len(tables) == 2
    assert ("人民币万元" if chinese else "millions") in tables[0].context_text
    assert ("人民币元" if chinese else "thousands") in tables[1].context_text
    assert ("人民币万元" if chinese else "millions") not in tables[1].context_text
    replaced = replace(tables[1], context_text=tables[0].context_text, context_source_ids=tables[0].context_source_ids)
    report = audit_document(
        replace(
            inventory,
            canonical_blocks=tuple(
                replaced if b.block_id == replaced.block_id else b for b in inventory.canonical_blocks
            ),
        )
    )
    detected = {f.failure_class for f in report.failures}
    assert FailureClass.UNIT_CONTEXT_LOSS in detected
    assert FailureClass.SCOPE_CONTEXT_LOSS in detected


def test_continuation_retains_unit_scope_and_period_source_binding(tmp_path):
    path = tmp_path / "continuation.pdf"
    contextual_tables_pdf(path, continuation=True)
    inventory, report = inspect_pdf(path)
    assert report.state == DocumentState.READY, report.failures
    continued = next(b for b in report.blocks if b.continuation)
    assert "USD in millions" in continued.context_text
    assert "2025" in continued.table_header
    assert continued.provenance
    assert any("USD in millions" in c.text and "Equipment" in c.text for c in report.chunks)
    broken = replace(continued, context_text="", context_source_ids=())
    failed = audit_document(
        replace(
            inventory, canonical_blocks=tuple(broken if b.block_id == broken.block_id else b for b in report.blocks)
        )
    )
    assert FailureClass.UNIT_CONTEXT_LOSS in {f.failure_class for f in failed.failures}


@pytest.mark.parametrize("amount", ["$100", "USD 100.50", "(100.25)", "１，２３４.５０"])
def test_formatted_merged_amounts_are_not_silently_treated_as_labels(tmp_path, amount):
    path = tmp_path / "formatted-amount.pdf"
    merged_pdf(path, mode="horizontal", amount=amount)
    _, report = inspect_pdf(path)
    assert report.state == DocumentState.QUARANTINED
    assert FailureClass.MERGED_CELL_AMBIGUITY in {f.failure_class for f in report.failures}
