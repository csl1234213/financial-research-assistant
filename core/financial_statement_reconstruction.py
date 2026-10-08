"""Deterministic reconstruction of standard financial statements from PDF IR.

Only parser-native cells, their coordinates, and nearby page text are used.
This module deliberately does not inspect vector-store chunks or call an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Sequence

from core.financial_table_rows import FinancialTableRow


@dataclass(frozen=True, slots=True)
class FinancialColumn:
    index: int
    header: str
    period: str
    fiscal_year: int
    role: str
    x_center: float | None = None


@dataclass(frozen=True, slots=True)
class FinancialTableContext:
    document_id: str | None
    company: str | None
    statement_type: str
    scope: str
    title: str
    start_page: int
    end_page: int
    currency: str | None
    unit: str | None
    column_headers: tuple[str, ...]
    fiscal_periods: tuple[str, ...]
    confidence: float
    source_regions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconstructionResult:
    contexts: tuple[FinancialTableContext, ...]
    rows: tuple[FinancialTableRow, ...]


@dataclass(slots=True)
class _ActiveStatement:
    document_id: str | None
    filename: str
    statement_type: str
    scope: str
    title: str
    start_page: int
    end_page: int
    company: str | None = None
    currency: str | None = None
    unit: str | None = None
    headers: tuple[str, ...] = ()
    columns: tuple[FinancialColumn, ...] = ()
    note_column: int | None = None
    source_regions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    last_table_page: int = 0
    last_bbox: tuple[float, float, float, float] | None = None
    rows: list[FinancialTableRow] = field(default_factory=list)


_STATEMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("balance_sheet", re.compile(r"(?:合并|母公司)?资产负债表|balance\s+sheet", re.I)),
    ("income_statement", re.compile(r"(?:合并|母公司)?利润表|损益表|income\s+statement", re.I)),
    ("cash_flow_statement", re.compile(r"(?:合并|母公司)?现金流量表|cash\s+flow\s+statement", re.I)),
    ("equity_statement", re.compile(r"(?:合并|母公司)?(?:所有者|股东)权益变动表|statement\s+of\s+equity", re.I)),
)
_STOP_CONTEXT = re.compile(r"财务报表附注|重要会计政策|公司基本情况|审计报告", re.I)
_METADATA_HEADING = re.compile(r"编制单位|单位|金额单位|币种|currency", re.I)
_PAGE_NUMBER = re.compile(r"^\d+\s*/\s*\d+$")
_NOTE_HEADER = re.compile(r"附注|注释|note", re.I)
_UNIT_PATTERNS = (
    ("百万元", re.compile(r"(?:单位|金额单位)[：:]?\s*(?:人民币)?\s*百万元")),
    ("千元", re.compile(r"(?:单位|金额单位)[：:]?\s*(?:人民币)?\s*千元")),
    ("万元", re.compile(r"(?:单位|金额单位)[：:]?\s*(?:人民币)?\s*万元")),
    ("亿元", re.compile(r"(?:单位|金额单位)[：:]?\s*(?:人民币)?\s*亿元")),
    ("元", re.compile(r"(?:单位|金额单位)[：:]?\s*(?:人民币)?\s*元(?:\b|\s|$)")),
)
_NUMBER = re.compile(
    r"^\s*(?P<open>\()\s*(?P<paren>[\d,]+(?:\.\d+)?)\s*\)?\s*$"
    r"|^\s*(?P<plain>[+-]?[\d,]+(?:\.\d+)?)\s*$"
)
_DATE = re.compile(r"(?P<year>20\d{2})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日")
_ISO_DATE = re.compile(r"^(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})$")
_YEAR = re.compile(r"^(?:FY\s*)?(?P<year>20\d{2})\s*(?:年度|年)?$", re.I)


def reconstruct_financial_statements(
    pages: Sequence[object],
    *,
    filename: str,
    document_id: str | None = None,
) -> ReconstructionResult:
    """Recover verified atomic rows while respecting explicit layout boundaries."""

    active: _ActiveStatement | None = None
    contexts: list[FinancialTableContext] = []
    rows: list[FinancialTableRow] = []
    document_company: str | None = None

    def finish() -> None:
        nonlocal active
        if active is None:
            return
        if active.last_table_page:
            contexts.append(
                FinancialTableContext(
                    document_id=active.document_id,
                    company=active.company,
                    statement_type=active.statement_type,
                    scope=active.scope,
                    title=active.title,
                    start_page=active.start_page,
                    end_page=active.end_page,
                    currency=active.currency,
                    unit=active.unit,
                    column_headers=tuple(column.header for column in active.columns),
                    fiscal_periods=tuple(dict.fromkeys(row.period for row in active.rows)),
                    confidence=active.confidence,
                    source_regions=tuple(dict.fromkeys(active.source_regions)),
                )
            )
            rows.extend(active.rows)
        active = None

    for page in pages:
        page_number = int(getattr(page, "number"))
        text_regions = tuple(getattr(page, "text_regions", ()))
        candidates = tuple(getattr(page, "table_candidates", ()))
        blocks = tuple(getattr(page, "blocks", ()))
        document_company = _extract_company(
            "\n".join(str(getattr(region, "text", "")) for region in text_regions)
        ) or document_company
        events: list[tuple[float, str, object]] = []
        for region in text_regions:
            text = str(getattr(region, "text", "")).strip()
            bbox = getattr(region, "bbox", (0.0, 0.0, 0.0, 0.0))
            y = float(bbox[1]) if len(bbox) > 1 else 0.0
            detected = _detect_statement_title(text)
            if detected:
                events.append((y, "statement", (text, detected, region)))
            elif _STOP_CONTEXT.search(text):
                events.append((y, "stop", region))
        for block in blocks:
            text = str(getattr(block, "text", "")).strip()
            bbox = getattr(block, "bbox", None)
            if (
                not getattr(block, "is_heading", False)
                or not bbox
                or _detect_statement_title(text)
                or _STOP_CONTEXT.search(text)
                or _METADATA_HEADING.search(text)
                or _PAGE_NUMBER.fullmatch(text)
                or _bbox_inside_table(bbox, candidates)
            ):
                continue
            events.append((float(bbox[1]), "section", block))
        for candidate in candidates:
            bbox = getattr(candidate, "bbox", (0.0, 0.0, 0.0, 0.0))
            events.append((float(bbox[1]), "table", candidate))
        events.sort(key=lambda item: (item[0], 0 if item[1] != "table" else 1))

        for y, kind, payload in events:
            if kind == "stop":
                finish()
                continue
            if kind == "section":
                if active is not None and active.last_table_page:
                    finish()
                continue
            if kind == "statement":
                finish()
                _title_text, detected, region = payload  # type: ignore[misc]
                statement_type, scope, title = detected
                source_region = _region_locator(page_number, region)
                active = _ActiveStatement(
                    document_id=document_id,
                    filename=filename,
                    statement_type=statement_type,
                    scope=scope,
                    title=title,
                    start_page=page_number,
                    end_page=page_number,
                    company=document_company,
                    confidence=0.55,
                    source_regions=[source_region],
                )
                continue

            candidate = payload
            if active is None:
                continue
            if active.last_table_page and page_number - active.last_table_page > 1:
                finish()
                continue

            candidate_bbox = getattr(candidate, "bbox", None)
            raw_rows = tuple(getattr(candidate, "rows", ()))
            table_index = int(getattr(candidate, "table_index", 1))
            nearby_regions = _nearby_preceding_regions(text_regions, y)
            nearby_text = "\n".join(str(getattr(region, "text", "")) for region in nearby_regions)
            full_context_text = "\n".join(
                [active.title, nearby_text, *(str(getattr(item, "text", "")) for item in text_regions)]
            )

            if active.company is None:
                active.company = _extract_company(full_context_text)
            active.currency = _extract_currency(nearby_text) or active.currency
            active.unit = _extract_unit(nearby_text) or active.unit

            header_info = _find_header(raw_rows, active.statement_type, full_context_text)
            if header_info is not None:
                header_index, header = header_info
                bindings = _bind_columns(
                    header,
                    active.statement_type,
                    full_context_text,
                    table_rows=raw_rows,
                    header_index=header_index,
                )
                if bindings:
                    active.headers = tuple(_cell_text(cell) for cell in header.cells)
                    active.columns = bindings
                    active.note_column = next(
                        (index for index, value in enumerate(active.headers) if _NOTE_HEADER.search(value)),
                        None,
                    )
                    active.confidence = max(active.confidence, 0.9)
                    active.source_regions.append(_region_locator(page_number, candidate))
                else:
                    # An explicit but unresolved header is a hard fail-closed
                    # boundary; a previous table's columns must not leak in.
                    active.columns = ()
                    active.headers = ()
                    active.note_column = None
            elif active.columns and not _continuation_geometry_matches(active, candidate_bbox, raw_rows):
                # Do not bind rows from a different grid to the old columns.
                active.columns = ()

            if active.columns:
                active.end_page = page_number
                active.last_table_page = page_number
                active.last_bbox = candidate_bbox
                active.source_regions.append(_region_locator(page_number, candidate))
                for row_index, source_row in enumerate(raw_rows):
                    cells = tuple(getattr(source_row, "cells", ()))
                    if _is_repeated_header(cells, active.headers):
                        continue
                    row_label = _cell_text(cells[0]) if cells else ""
                    if not row_label or _is_section_label(cells):
                        continue
                    note_reference = (
                        _cell_text(cells[active.note_column])
                        if active.note_column is not None and active.note_column < len(cells)
                        else None
                    )
                    for column in active.columns:
                        column_index = _source_column_index(column, source_row)
                        if column_index is None or column_index >= len(cells):
                            continue
                        raw_value = _cell_text(cells[column_index])
                        parsed_value = _parse_decimal(raw_value)
                        if parsed_value is None:
                            continue
                        value_unit, value_currency = _row_unit_currency(
                            row_label, raw_value, active.unit, active.currency
                        )
                        cell_bbox = _cell_bbox(source_row, column_index)
                        locator = (
                            f"PDF page {page_number}, table {table_index}, "
                            f"row {row_index + 1}, column {column_index + 1}"
                        )
                        source_text = " | ".join(_cell_text(cell) for cell in cells)
                        financial_row = FinancialTableRow.assess(
                            document_id=active.document_id,
                            company=active.company,
                            statement_type=active.statement_type,
                            table_title=active.title,
                            scope=active.scope,
                            row_label=row_label,
                            canonical_metric=None,
                            column_label=column.header,
                            fiscal_year=column.fiscal_year,
                            period=column.period,
                            value=parsed_value,
                            raw_value=raw_value,
                            unit=value_unit,
                            currency=value_currency,
                            source=filename,
                            source_locator=locator,
                            page=page_number,
                            source_text=source_text,
                            column_binding_proven=True,
                            source_row_detected=True,
                            note_reference=note_reference or None,
                            source_region=_bbox_locator(page_number, cell_bbox or candidate_bbox),
                            column_role=column.role,
                        )
                        active.rows.append(financial_row)

        # Keep continuation state only when the next adjacent page presents a
        # same-width native grid; a page with no table closes this context.
        if active is not None and active.last_table_page and active.last_table_page < page_number:
            finish()

    finish()
    return ReconstructionResult(contexts=tuple(contexts), rows=tuple(rows))


def _detect_statement_title(text: str) -> tuple[str, str, str] | None:
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) > 100:
        return None
    matches = [(kind, pattern.search(cleaned)) for kind, pattern in _STATEMENT_PATTERNS]
    found = [(kind, match) for kind, match in matches if match]
    if len(found) != 1:
        return None
    statement_type, match = found[0]
    title_match = re.search(
        r"(?:合并|母公司)?(?:资产负债表|利润表|损益表|现金流量表|(?:所有者|股东)权益变动表)|"
        r"balance\s+sheet|income\s+statement|cash\s+flow\s+statement|statement\s+of\s+equity",
        cleaned,
        re.I,
    )
    if match is None or title_match is None:
        return None
    title = title_match.group(0)
    if "母公司" in title:
        scope = "parent"
    elif "合并" in title or re.search(r"consolidated", title, re.I):
        scope = "consolidated"
    else:
        scope = "unknown"
    return statement_type, scope, title


def _find_header(
    rows: Sequence[object], statement_type: str, context: str
) -> tuple[int, object] | None:
    for row_index, row in enumerate(rows):
        cells = tuple(getattr(row, "cells", ()))
        values = tuple(_cell_text(cell) for cell in cells)
        if not values or not re.search(r"项目|particulars|description", values[0], re.I):
            continue
        bindings = _bind_columns(
            row,
            statement_type,
            context,
            table_rows=rows,
            header_index=row_index,
        )
        if bindings:
            return row_index, row
        # Explicit period tokens without a bound map are ambiguous headers;
        # the caller clears any prior context rather than misusing it.
        if any(_looks_like_period_header(value) for value in values[1:]):
            return row_index, row
    return None


def _bind_columns(
    row: object,
    statement_type: str,
    context: str,
    *,
    table_rows: Sequence[object] = (),
    header_index: int = 0,
) -> tuple[FinancialColumn, ...]:
    values = tuple(_cell_text(cell) for cell in getattr(row, "cells", ()))
    explicit_dates = [
        (int(match.group("year")), int(match.group("month")), int(match.group("day")))
        for match in _DATE.finditer(context)
    ]
    period_cells: list[
        tuple[str, int, int, tuple[float, float, float, float] | None]
    ] = []
    header_rows = table_rows[header_index:] if table_rows else (row,)
    data_start = next(
        (
            index
            for index in range(header_index + 1, len(table_rows))
            if _row_has_numeric_value(getattr(table_rows[index], "cells", ()))
        ),
        len(table_rows),
    )
    header_rows = table_rows[header_index:data_start] if table_rows else (row,)
    if not header_rows:
        header_rows = (row,)

    for header_row in header_rows:
        for index, raw_cell in enumerate(getattr(header_row, "cells", ())):
            label = _cell_text(raw_cell)
            period = _parse_period(label)
            if period is None and label in {"期末余额", "期末数", "年末余额"} and explicit_dates:
                year, month, day = explicit_dates[0]
                period = (f"{year:04d}-{month:02d}-{day:02d}", year)
            if period is None and label in {"期初余额", "期初数", "年初余额"} and explicit_dates:
                year, month, day = explicit_dates[0]
                prior_year = year - 1
                period = (f"{prior_year:04d}-{month:02d}-{day:02d}", prior_year)
            if period is not None:
                period_cells.append((period[0], period[1], index, _cell_bbox(header_row, index)))

    if not period_cells:
        return ()
    data_rows = table_rows[data_start:] if table_rows else ()
    note_columns = {
        index
        for header_row in header_rows
        for index, raw_cell in enumerate(getattr(header_row, "cells", ()))
        if _NOTE_HEADER.search(_cell_text(raw_cell))
    }
    numeric_columns = sorted(
        {
            index
            for data_row in data_rows
            for index, raw_cell in enumerate(getattr(data_row, "cells", ()))
            if index > 0
            and index not in note_columns
            and _parse_decimal(_cell_text(raw_cell)) is not None
        }
    )
    if not numeric_columns:
        numeric_columns = sorted(
            {
                index
                for _period, _year, index, _bbox in period_cells
                if index > 0 and index not in note_columns
            }
        )

    columns: list[FinancialColumn] = []
    for index in numeric_columns:
        center = _data_column_center(data_rows, index)
        direct_period = next(
            ((period, year) for period, year, period_index, _bbox in period_cells if period_index == index),
            None,
        )
        selected_period = direct_period or next(
            (
                (period, year)
                for period, year, _period_index, bbox in period_cells
                if center is not None and bbox is not None and bbox[0] <= center <= bbox[2]
            ),
            None,
        )
        if selected_period is None:
            continue
        period, fiscal_year = selected_period
        semantics = _column_semantics(header_rows, index, center)
        label = " / ".join(semantics) or values[index] or period
        columns.append(FinancialColumn(index, label, period, fiscal_year, "", center))

    if not columns:
        return ()
    newest_year = max(column.fiscal_year for column in columns)
    if statement_type == "balance_sheet":
        def role(item: FinancialColumn) -> str:
            return "closing_balance" if item.fiscal_year == newest_year else "comparative_balance"
    else:
        def role(item: FinancialColumn) -> str:
            return "current_period" if item.fiscal_year == newest_year else "comparative_period"
    return tuple(
        FinancialColumn(
            item.index,
            item.header,
            item.period,
            item.fiscal_year,
            role(item),
            item.x_center,
        )
        for item in columns
    )


def _row_has_numeric_value(cells: Sequence[str | None]) -> bool:
    return any(_parse_decimal(_cell_text(value)) is not None for value in cells[1:])


def _data_column_center(rows: Sequence[object], index: int) -> float | None:
    for row in rows:
        bbox = _cell_bbox(row, index)
        if bbox is not None:
            return (bbox[0] + bbox[2]) / 2
    return None


def _column_semantics(
    header_rows: Sequence[object],
    column_index: int,
    center: float | None,
) -> tuple[str, ...]:
    labels: list[str] = []
    for header_row in header_rows:
        cells = tuple(getattr(header_row, "cells", ()))
        for index, raw_cell in enumerate(cells):
            label = _cell_text(raw_cell)
            if (
                not label
                or index == 0
                or _NOTE_HEADER.search(label)
                or _looks_like_period_header(label)
            ):
                continue
            bbox = _cell_bbox(header_row, index)
            if index == column_index or (
                center is not None and bbox is not None and bbox[0] <= center <= bbox[2]
            ):
                if label not in labels:
                    labels.append(label)
    return tuple(labels)


def _parse_period(label: str) -> tuple[str, int] | None:
    cleaned = re.sub(r"\s+", "", label)
    date_match = _DATE.fullmatch(cleaned)
    if date_match:
        year, month, day = (int(date_match.group(name)) for name in ("year", "month", "day"))
        if _valid_date(year, month, day):
            return f"{year:04d}-{month:02d}-{day:02d}", year
    iso_match = _ISO_DATE.fullmatch(cleaned)
    if iso_match:
        year, month, day = (int(iso_match.group(name)) for name in ("year", "month", "day"))
        if _valid_date(year, month, day):
            return cleaned, year
    year_match = _YEAR.fullmatch(cleaned)
    if year_match:
        year = int(year_match.group("year"))
        return f"FY{year}", year
    return None


def _looks_like_period_header(value: str) -> bool:
    return _parse_period(value) is not None or value in {
        "期末余额", "期末数", "年末余额", "期初余额", "期初数", "年初余额"
    }


def _valid_date(year: int, month: int, day: int) -> bool:
    from datetime import date

    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _continuation_geometry_matches(
    active: _ActiveStatement,
    bbox: tuple[float, float, float, float] | None,
    rows: Sequence[object],
) -> bool:
    if not active.columns or not rows:
        return False
    if active.last_bbox is None or bbox is None:
        return True
    previous_width = active.last_bbox[2] - active.last_bbox[0]
    current_width = bbox[2] - bbox[0]
    if previous_width <= 0 or current_width <= 0:
        return False
    if abs(previous_width - current_width) > max(previous_width, current_width) * 0.12:
        return False
    return all(
        column.x_center is None
        or any(
            (cell_bbox := _cell_bbox(row, index)) is not None
            and cell_bbox[0] <= column.x_center <= cell_bbox[2]
            for row in rows[:8]
            for index, value in enumerate(getattr(row, "cells", ()))
            if _cell_text(value)
        )
        for column in active.columns
    )


def _bbox_inside_table(bbox: Sequence[float], candidates: Sequence[object]) -> bool:
    """Treat text geometrically within a grid as cell/header content, not a section boundary."""

    if len(bbox) < 4:
        return False
    x0, y0, x1, y1 = (float(value) for value in bbox[:4])
    for candidate in candidates:
        table_bbox = getattr(candidate, "bbox", None)
        if table_bbox is None or len(table_bbox) < 4:
            continue
        tx0, ty0, tx1, ty1 = (float(value) for value in table_bbox[:4])
        intersects = x0 < tx1 and x1 > tx0 and y0 < ty1 and y1 > ty0
        if intersects:
            return True
    return False


def _effective_column_count(rows: Sequence[object]) -> int:
    """Ignore extractor-added trailing blank columns on continuation pages."""

    last_nonempty = -1
    for row in rows:
        for index, value in enumerate(getattr(row, "cells", ())):
            if _cell_text(value):
                last_nonempty = max(last_nonempty, index)
    return last_nonempty + 1


def _source_column_index(column: FinancialColumn, row: object) -> int | None:
    cells = tuple(getattr(row, "cells", ()))
    if column.x_center is None:
        return column.index if column.index < len(cells) else None
    matches = [
        index
        for index in range(len(cells))
        if (bbox := _cell_bbox(row, index)) is not None
        and bbox[0] <= column.x_center <= bbox[2]
    ]
    if len(matches) == 1:
        return matches[0]
    if column.index < len(cells) and _cell_bbox(row, column.index) is None:
        return column.index
    return None


def _extract_currency(text: str) -> str | None:
    if re.search(r"币种[：:]?\s*人民币|\bCNY\b|\bRMB\b", text, re.I):
        return "CNY"
    if re.search(r"币种[：:]?\s*(?:美元|USD)|\bUSD\b", text, re.I):
        return "USD"
    if re.search(r"币种[：:]?\s*(?:欧元|EUR)|\bEUR\b", text, re.I):
        return "EUR"
    return None


def _extract_unit(text: str) -> str | None:
    for unit, pattern in _UNIT_PATTERNS:
        if pattern.search(text):
            return unit
    if re.search(r"amounts?\s+in\s+millions", text, re.I):
        return "million"
    if re.search(r"amounts?\s+in\s+thousands", text, re.I):
        return "thousand"
    return None


def _extract_company(text: str) -> str | None:
    match = re.search(r"编制单位[：:]\s*([^\n]+)", text)
    if match:
        value = match.group(1).strip()
        return value if value else None
    return None


def _row_unit_currency(
    row_label: str,
    raw_value: str,
    context_unit: str | None,
    context_currency: str | None,
) -> tuple[str | None, str | None]:
    if "%" in raw_value:
        return "%", None
    if "元/股" in row_label:
        return "元/股", context_currency
    return context_unit, context_currency


def _parse_decimal(raw_value: str) -> Decimal | None:
    cleaned = raw_value.strip().replace("，", ",").replace("−", "-")
    if cleaned in {"", "—", "–", "-", "－"}:
        return None
    match = _NUMBER.fullmatch(cleaned)
    if match is None:
        return None
    numeric = match.group("paren") or match.group("plain")
    try:
        value = Decimal(numeric.replace(",", ""))
    except InvalidOperation:
        return None
    return -abs(value) if match.group("open") else value


def _nearby_preceding_regions(regions: Sequence[object], table_y: float) -> tuple[object, ...]:
    selected = []
    for region in regions:
        bbox = getattr(region, "bbox", None)
        if bbox is None or float(bbox[1]) > table_y:
            continue
        if table_y - float(bbox[3]) <= 180:
            selected.append(region)
    return tuple(sorted(selected, key=lambda item: float(getattr(item, "bbox")[1])))


def _is_repeated_header(cells: Sequence[str | None], headers: Sequence[str]) -> bool:
    values = tuple(_cell_text(cell) for cell in cells)
    return bool(values and values == headers)


def _is_section_label(cells: Sequence[str | None]) -> bool:
    return len(cells) > 1 and all(not _cell_text(cell) for cell in cells[1:])


def _cell_text(value: object | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _cell_bbox(row: object, index: int) -> tuple[float, float, float, float] | None:
    bboxes = tuple(getattr(row, "cell_bboxes", ()))
    if index >= len(bboxes) or bboxes[index] is None:
        return None
    return tuple(float(value) for value in bboxes[index])  # type: ignore[return-value]


def _region_locator(page_number: int, region: object) -> str:
    bbox = getattr(region, "bbox", getattr(region, "table_bbox", None))
    return _bbox_locator(page_number, bbox)


def _bbox_locator(page_number: int, bbox: object | None) -> str:
    if not bbox:
        return f"PDF page {page_number}; source region unavailable"
    coords = ",".join(f"{float(value):.1f}" for value in bbox)  # type: ignore[arg-type]
    return f"PDF page {page_number}; bbox=({coords})"
