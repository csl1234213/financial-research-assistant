"""Source-backed geometry and context checks, not financial semantic inference."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from .models import ContextRequirement, FailureClass, FailureSignature, TableCellGeometry

CONTEXT_PATTERNS = {
    FailureClass.PERIOD_CONTEXT_LOSS: re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)"),
    FailureClass.UNIT_CONTEXT_LOSS: re.compile(
        r"单位\s*[:：]|(?:人民币|美元|港元|欧元)\s*(?:元|万元|百万元|亿元)?|"
        r"\b(?:in\s+(?:thousands|millions|billions)|CNY|RMB|USD|EUR|HKD)\b",
        re.I,
    ),
    FailureClass.SCOPE_CONTEXT_LOSS: re.compile(
        r"合并|母公司|\b(?:consolidated|parent\s+(?:company|only)|separate\s+financial)\b", re.I
    ),
}


def inline_source_order(spans):
    """Sort physical lines, then x within each line, including superscripts.

    A line anchor never grows: chaining partially overlapping neighboring lines
    would merge paragraphs and hide genuine order failures.
    """
    lines = []
    for span in sorted(spans, key=lambda item: (item.bbox[1], item.bbox[0])):
        height = span.bbox[3] - span.bbox[1]
        line = next((items for anchor, items in lines
                     if min(anchor.bbox[3], span.bbox[3]) - max(anchor.bbox[1], span.bbox[1])
                     >= 0.7 * min(anchor.bbox[3] - anchor.bbox[1], height)
                     and height > 0 and anchor.bbox[3] > anchor.bbox[1]), None)
        if line is None:
            lines.append((span, [span]))
        else:
            line.append(span)
    return tuple(span for _, line in lines for span in sorted(line, key=lambda item: item.bbox[0]))


def cell_geometry(table, source_spans=()):
    """Keep merged extents rather than copying a value into empty grid slots."""
    boxes = [box for row in table.rows for box in row.cell_bboxes if box]
    xs = sorted({round(x, 2) for box in boxes for x in (box[0], box[2])})
    ys = sorted({round(y, 2) for box in boxes for y in (box[1], box[3])})
    cells = []
    for row_index, row in enumerate(table.rows):
        for column_index, (text, box) in enumerate(zip(row.cells, row.cell_bboxes)):
            if box is None:
                continue
            cells.append(
                TableCellGeometry(
                    row_index,
                    column_index,
                    text or "",
                    box,
                    1 + sum(box[1] + 1 < y < box[3] - 1 for y in ys),
                    1 + sum(box[0] + 1 < x < box[2] - 1 for x in xs),
                )
            )
    proven = []
    for cell in cells:
        # A native merged region is one value, not values copied into every
        # grid slot. Bind only exact contained native text with unique ownership.
        selected = tuple(span for span in source_spans
            if span.page == table.page and span.valid and span.text.strip()
            and cell.bbox[0] - 1 <= span.bbox[0]
            and cell.bbox[1] - 1 <= span.bbox[1]
            and span.bbox[2] <= cell.bbox[2] + 1
            and span.bbox[3] <= cell.bbox[3] + 1)
        def normalize(value):
            return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))
        source_text = "".join(span.text for span in sorted(selected, key=lambda span: (span.bbox[1], span.bbox[0])))
        overlaps = any(other is not cell
            and min(cell.bbox[2], other.bbox[2]) - max(cell.bbox[0], other.bbox[0]) > 1
            and min(cell.bbox[3], other.bbox[3]) - max(cell.bbox[1], other.bbox[1]) > 1
            for other in cells)
        bound = bool(selected and not overlaps and normalize(source_text) == normalize(cell.text))
        proven.append(replace(cell, source_ids=tuple(span.span_id for span in selected) if bound else (),
                              source_binding_proven=bound))
    return tuple(proven)


def merged_numeric_failures(table, cells, header_index, verified_rows):
    """Merged labels/headings are legal; a merged amount needs a proven binding."""
    failures = []
    for cell in cells:
        if cell.row_span == cell.column_span == 1:
            continue
        value_text = unicodedata.normalize("NFKC", cell.text).strip().replace("−", "-")
        if not re.fullmatch(
            r"(?:USD|RMB|CNY|[$¥€£])?\s*\(?[-+]?\s*\d[\d,\s]*(?:\.\d+)?\)?\s*(?:%|元|万元|亿元)?",
            value_text,
            re.I,
        ):
            continue
        if header_index is not None and cell.row <= header_index and re.fullmatch(r"(?:19|20)\d{2}", value_text):
            continue  # A period heading is not an amount; other amounts are never exempt.
        financial_table = any(row.source_locator.startswith(
            f"PDF page {table.page}, table {table.table_index},") for row in verified_rows)
        if cell.source_binding_proven and cell.source_ids and header_index is None and not financial_table:
            # Physical source fidelity only. No FinancialTableRow status,
            # metric identity, amount duplication or semantic promotion changes.
            continue
        locator = f"PDF page {table.page}, table {table.table_index}, row {cell.row + 1}, column {cell.column + 1}"
        # P1.3's explicit cell binding is stronger than a grid-width heuristic.
        proven = any(
            row.source_locator == locator
            and row.verification_status.value == "VERIFIED"
            and row.column_binding_proven
            and row.raw_value == cell.text.strip()
            for row in verified_rows
        )
        if proven:
            continue
        failures.append(
            FailureSignature(
                FailureClass.MERGED_CELL_AMBIGUITY,
                table.page,
                features=(
                    ("table", str(table.table_index)),
                    ("row", str(cell.row + 1)),
                    ("column", str(cell.column + 1)),
                    ("bbox", str(cell.bbox)),
                    ("row_span", str(cell.row_span)),
                    ("column_span", str(cell.column_span)),
                    ("raw_value", cell.text),
                    ("binding_requirement", "MERGED_EXTENT_TO_EXPLICIT_ROW_AND_COLUMN_CONTEXT"),
                ),
                critical=True,
            )
        )
    return tuple(failures)


def context_requirements(block_id, table, spans, header_bottom, previous_bottom):
    """Bind only nearby source context to this table, never document-global text."""
    requirements = []
    for span in spans:
        if span.page != table.page:
            continue
        x0, y0, x1, y1 = span.bbox
        above = max(previous_bottom, table.bbox[1] - 150) <= y0 and y1 <= table.bbox[1] + 2
        header = header_bottom is not None and table.bbox[1] <= y0 < header_bottom
        if not (above or header) or x1 < table.bbox[0] or x0 > table.bbox[2]:
            continue
        for failure, pattern in CONTEXT_PATTERNS.items():
            # Years in body cells are not report-period context.
            if pattern.search(span.text):
                requirements.append(ContextRequirement(block_id, table.page, failure, span.span_id, span.text))
    return tuple(requirements)


def inherited_context_requirements(blocks, requirements, normalized):
    """A continuation can inherit only from an adjacent, geometrically matched grid."""
    result = list(requirements)
    for block in sorted(blocks, key=lambda b: b.page):
        if not block.continuation or block.table_header:
            continue
        previous = next((b for b in blocks if adjacent_table(b, block, normalized)), None)
        if previous is None:
            continue
        explicit_kinds = {r.failure_class for r in result if r.block_id == block.block_id}
        result.extend(
            replace(r, block_id=block.block_id, page=block.page)
            for r in tuple(result)
            if r.block_id == previous.block_id and r.failure_class not in explicit_kinds
        )
    return tuple(result)


def adjacent_table(previous, current, normalized):
    return bool(
        previous.page + 1 == current.page
        and previous.table_header
        and normalized(previous.table_header) in normalized(previous.text)
        and previous.section
        and previous.section == current.section
        and len(previous.table_columns) == len(current.table_columns) >= 2
        and all(abs(a - b) <= 2 for a, b in zip(previous.table_columns, current.table_columns))
    )


def detect_structure(inventory, blocks, normalized):
    failures = []
    block_map = {b.block_id: b for b in blocks}
    for required in inventory.context_requirements:
        block = block_map.get(required.block_id)
        if block is None or (
            required.source_id not in block.context_source_ids
            or normalized(required.text) not in normalized(block.context_text)
        ):
            failures.append(
                FailureSignature(
                    required.failure_class,
                    required.page,
                    (required.source_id,),
                    (required.block_id,),
                    (("reason", "source context not bound to its table"),),
                    critical=True,
                )
            )
    failures.extend(reading_order_failures(inventory, blocks, normalized))
    return tuple(failures)


def reading_order_failures(inventory, blocks, normalized):
    failures = []
    sources = {s.span_id: s for s in inventory.native_spans}
    for constraint in inventory.reading_order_constraints:
        ordered_blocks = [b for b in blocks if b.page == constraint.page]
        positions = []
        cursor = (-1, 0)
        for sid in constraint.source_ids:
            span = sources[sid]
            source_text = normalized(span.text)
            matches = [
                (index, match.start())
                for index, block in enumerate(ordered_blocks)
                if sid in block.source_ids and source_text
                for match in re.finditer(re.escape(source_text), normalized(block.text))
            ]
            if not matches:
                continue  # Completeness guard separately detects absent content.
            # Repeated footnote markers must not all bind to the first textual
            # occurrence. Match successive source spans to non-overlapping
            # occurrences; if no forward occurrence exists, retain the backward
            # position so real reordering is still reported rather than skipped.
            position = min((match for match in matches if match >= cursor), default=min(matches))
            positions.append(position)
            cursor = (position[0], position[1] + len(source_text))
        if positions != sorted(positions):
            failures.append(
                FailureSignature(
                    FailureClass.MULTICOLUMN_READING_ORDER_ERROR,
                    constraint.page,
                    constraint.source_ids,
                    features=(("reason", "canonical sequence violates source column order"),),
                    critical=True,
                )
            )
    return tuple(failures)
