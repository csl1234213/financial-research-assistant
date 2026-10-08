"""Typed, fail-closed schema for source-backed financial table rows.

This module intentionally does not infer table meaning from a model. A row is
eligible for deterministic numeric grounding only when the parser and source
metadata prove every required identity and the row-to-column binding.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Iterable


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"


_CANONICAL_METRICS = frozenset(
    {
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "attributable_net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "cash",
        "cash_and_cash_equivalents",
        "accounts_receivable",
        "inventory",
        "fixed_assets",
        "construction_in_progress",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "r_and_d",
        "capital_expenditure",
    }
)
_STATEMENT_TYPES = frozenset(
    {
        "balance_sheet",
        "income_statement",
        "cash_flow_statement",
        "equity_statement",
    }
)


@dataclass(frozen=True, slots=True)
class FinancialTableRow:
    document_id: str | None
    company: str | None
    statement_type: str | None
    table_title: str | None
    scope: str | None
    row_label: str | None
    canonical_metric: str | None
    column_label: str | None
    fiscal_year: int | None
    period: str | None
    value: Decimal | None
    raw_value: str | None
    unit: str | None
    currency: str | None
    source: str | None
    source_locator: str | None
    page: int | None
    source_text: str
    verification_status: VerificationStatus
    verification_reasons: tuple[str, ...] = ()
    column_binding_proven: bool = False
    note_reference: str | None = None
    source_region: str | None = None
    column_role: str | None = None

    def __post_init__(self) -> None:
        if self.page is not None and self.page < 1:
            raise ValueError("page must be a one-based positive PDF page")
        if self.value is not None and not isinstance(self.value, Decimal):
            object.__setattr__(self, "value", Decimal(str(self.value)))
        if self.currency:
            object.__setattr__(self, "currency", self.currency.upper())
        if self.verification_status == VerificationStatus.VERIFIED:
            missing = _verified_row_missing_fields(self)
            if missing or self.verification_reasons or not self.column_binding_proven:
                raise ValueError(
                    "VERIFIED rows require complete source dimensions and a proven "
                    f"row-to-column binding; missing={missing}"
                )

    @property
    def eligible_for_deterministic_fact(self) -> bool:
        """Only fully verified rows may support a deterministic numeric fact."""

        return self.verification_status == VerificationStatus.VERIFIED

    def to_metadata(self) -> dict[str, str | int | bool]:
        """Return Chroma-compatible scalar metadata without losing provenance."""

        values = asdict(self)
        values["value"] = str(self.value) if self.value is not None else ""
        values["verification_status"] = self.verification_status.value
        values["verification_reasons"] = json.dumps(
            list(self.verification_reasons), ensure_ascii=False
        )
        for field_name in (
            "document_id",
            "company",
            "statement_type",
            "table_title",
            "scope",
            "row_label",
            "canonical_metric",
            "column_label",
            "period",
            "raw_value",
            "unit",
            "currency",
            "source",
            "source_locator",
            "source_text",
            "note_reference",
            "source_region",
            "column_role",
        ):
            if values[field_name] is None:
                values[field_name] = ""
        return values

    @classmethod
    def assess(
        cls,
        *,
        document_id: str | None,
        company: str | None,
        statement_type: str | None,
        table_title: str | None,
        scope: str | None,
        row_label: str | None,
        canonical_metric: str | None,
        column_label: str | None,
        fiscal_year: int | None,
        period: str | None,
        value: Decimal | str | int | None,
        raw_value: str | None,
        unit: str | None,
        currency: str | None,
        source: str | None,
        source_locator: str | None,
        page: int | None,
        source_text: str,
        column_binding_proven: bool,
        source_row_detected: bool = True,
        note_reference: str | None = None,
        source_region: str | None = None,
        column_role: str | None = None,
    ) -> "FinancialTableRow":
        """Assess a candidate conservatively; never upgrade ambiguous rows."""

        parsed_value = _decimal_or_none(value)
        reasons = list(
            _verified_row_missing_fields_values(
                document_id=document_id,
                company=company,
                statement_type=statement_type,
                table_title=table_title,
                scope=scope,
                row_label=row_label,
                canonical_metric=canonical_metric,
                column_label=column_label,
                fiscal_year=fiscal_year,
                period=period,
                value=parsed_value,
                raw_value=raw_value,
                unit=unit,
                currency=currency,
                source=source,
                source_locator=source_locator,
                page=page,
                source_text=source_text,
                note_reference=note_reference,
                source_region=source_region,
            )
        )
        if not column_binding_proven:
            reasons.append("row_column_binding_not_proven")
        if not source_row_detected:
            reasons.append("source_row_not_detected")

        if (
            not source_row_detected
            or parsed_value is None
            or not source_text.strip()
            or not column_binding_proven
        ):
            status = VerificationStatus.UNVERIFIED
        elif reasons:
            status = VerificationStatus.PARTIAL
        else:
            status = VerificationStatus.VERIFIED

        return cls(
            document_id=document_id,
            company=company,
            statement_type=statement_type,
            table_title=table_title,
            scope=scope,
            row_label=row_label,
            canonical_metric=canonical_metric,
            column_label=column_label,
            fiscal_year=fiscal_year,
            period=period,
            value=parsed_value,
            raw_value=raw_value,
            unit=unit,
            currency=currency,
            source=source,
            source_locator=source_locator,
            page=page,
            source_text=source_text,
            verification_status=status,
            verification_reasons=tuple(dict.fromkeys(reasons)),
            column_binding_proven=column_binding_proven,
            note_reference=note_reference,
            source_region=source_region,
            column_role=column_role,
        )


_STRUCTURED_ROW = re.compile(
    r"Financial table row\s*[—-]\s*Metric:\s*(?P<label>[^|\n]+)"
    r"(?P<cells>(?:\|[^|\n]+)+)",
    re.IGNORECASE,
)
_PERIOD_LABEL = re.compile(
    r"^(?:FY\s*)?(?P<year>20\d{2})(?:\s*年度|\s*年(?:度)?(?:\s*\d{1,2}月\d{1,2}日)?|$)"
    r"|^(?P<iso_year>20\d{2})-(?P<iso_month>0[1-9]|1[0-2])-(?P<iso_day>0[1-9]|[12]\d|3[01])$"
    r"|^Q[1-4][ -]?(?P<quarter_year>20\d{2})$",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?P<negative>\()?(?P<number>-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\)?"
)


def financial_table_rows_from_chunk(
    *,
    content: str,
    content_type: str,
    document_id: str,
    company: str,
    section: str,
    table_context: str,
    page: int,
    source: str,
    source_locator: str = "",
) -> tuple[FinancialTableRow, ...]:
    """Create typed candidates only from parser-verified row representations.

    Raw ``unverified_table`` text is deliberately not split into guessed rows.
    It remains available as quarantined text for retrieval/context only.
    """

    if content_type.casefold() != "table":
        return ()
    candidates: list[FinancialTableRow] = []
    context = "\n".join((section, table_context))
    statement_type = _statement_type(context)
    scope = _statement_scope(context)
    currency = _currency(context)
    unit = _unit(context)
    title = table_context.strip() or None

    for match in _STRUCTURED_ROW.finditer(content):
        row_label = match.group("label").strip()
        for cell in match.group("cells").split("|"):
            if ":" not in cell:
                continue
            column_label, raw_value = (part.strip() for part in cell.split(":", 1))
            period_match = _PERIOD_LABEL.fullmatch(column_label)
            if period_match is None:
                continue
            year = int(
                period_match.group("year")
                or period_match.group("quarter_year")
                or period_match.group("iso_year")
            )
            period = column_label.strip()
            value = _decimal_from_source_number(raw_value)
            canonical_metric = _exact_canonical_metric(row_label)
            source_text = match.group(0)
            candidates.append(
                FinancialTableRow.assess(
                    document_id=document_id,
                    company=company,
                    statement_type=statement_type,
                    table_title=title,
                    scope=scope,
                    row_label=row_label,
                    canonical_metric=canonical_metric,
                    column_label=column_label,
                    fiscal_year=year,
                    period=period,
                    value=value,
                    raw_value=raw_value,
                    unit=unit,
                    currency=currency,
                    source=source,
                    source_locator=source_locator or None,
                    page=page,
                    source_text=source_text,
                    column_binding_proven=True,
                    column_role="period_value",
                )
            )
    return tuple(candidates)


def financial_table_rows_json(rows: Iterable[FinancialTableRow]) -> str:
    """Serialize row candidates as a scalar string suitable for Chroma."""

    return json.dumps(
        [row.to_metadata() for row in rows],
        ensure_ascii=False,
        sort_keys=True,
    )


def _verified_row_missing_fields(row: FinancialTableRow) -> list[str]:
    return _verified_row_missing_fields_values(
        document_id=row.document_id,
        company=row.company,
        statement_type=row.statement_type,
        table_title=row.table_title,
        scope=row.scope,
        row_label=row.row_label,
        canonical_metric=row.canonical_metric,
        column_label=row.column_label,
        fiscal_year=row.fiscal_year,
        period=row.period,
        value=row.value,
        raw_value=row.raw_value,
        unit=row.unit,
        currency=row.currency,
        source=row.source,
        source_locator=row.source_locator,
        page=row.page,
        source_text=row.source_text,
    )


def _verified_row_missing_fields_values(**values: Any) -> list[str]:
    missing = [
        name
        for name in (
            "document_id",
            "company",
            "statement_type",
            "table_title",
            "scope",
            "row_label",
            "column_label",
            "period",
            "raw_value",
            "unit",
            "currency",
            "source",
            "page",
            "source_text",
        )
        if values.get(name) is None or not str(values.get(name)).strip()
    ]
    if values.get("fiscal_year") is None:
        missing.append("fiscal_year")
    if values.get("value") is None:
        missing.append("value")
    if values.get("statement_type") not in _STATEMENT_TYPES:
        missing.append("statement_type_not_recognized")
    scope = str(values.get("scope") or "").casefold()
    if scope not in {"consolidated", "parent"} and not scope.startswith("segment:"):
        missing.append("scope_not_resolved")
    currency = str(values.get("currency") or "")
    if currency and not re.fullmatch(r"[A-Za-z]{3}", currency):
        missing.append("currency_not_iso_4217")
    period = str(values.get("period") or "")
    period_match = _PERIOD_LABEL.fullmatch(period)
    if period and period_match is None:
        missing.append("period_not_explicitly_mapped")
    elif period_match is not None:
        expected_year = int(
            period_match.group("year")
            or period_match.group("quarter_year")
            or period_match.group("iso_year")
        )
        if values.get("fiscal_year") != expected_year:
            missing.append("fiscal_year_period_mismatch")
    return missing


def _decimal_or_none(value: Decimal | str | int | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_from_source_number(text: str) -> Decimal | None:
    value = text.strip()
    if value in {"", "—", "–", "-", "N/A", "不适用"}:
        return None
    match = _NUMBER.search(value)
    if not match:
        return None
    number = match.group("number").replace(",", "")
    try:
        parsed = Decimal(number)
    except InvalidOperation:
        return None
    if match.group("negative"):
        parsed = -abs(parsed)
    return parsed


def _exact_canonical_metric(label: str) -> str | None:
    """Accept only an already-canonical label; aliases belong to P1.4."""

    normalized = re.sub(r"[\s-]+", "_", label.strip().casefold())
    return normalized if normalized in _CANONICAL_METRICS else None


def _statement_type(context: str) -> str | None:
    matches = {
        "balance_sheet": r"资产负债表|balance\s+sheet",
        "income_statement": r"利润表|损益表|income\s+statement|statement\s+of\s+operations",
        "cash_flow_statement": r"现金流量表|cash\s+flow\s+statement",
        "equity_statement": r"所有者权益变动表|股东权益变动表|statement\s+of\s+equity",
    }
    found = [name for name, pattern in matches.items() if re.search(pattern, context, re.I)]
    return found[0] if len(found) == 1 else None


def _statement_scope(context: str) -> str | None:
    has_consolidated = bool(
        re.search(r"合并(?:财务报表|资产负债表|利润表|现金流量表)?|consolidated", context, re.I)
    )
    has_parent = bool(
        re.search(
            r"母公司(?:财务报表|资产负债表|利润表|现金流量表)?|parent(?:\s+company)?",
            context,
            re.I,
        )
    )
    if has_consolidated == has_parent:
        return None
    return "consolidated" if has_consolidated else "parent"


def _currency(context: str) -> str | None:
    if re.search(r"人民币|\bCNY\b|\bRMB\b", context, re.I):
        return "CNY"
    if re.search(r"\bUSD\b|\bUS\$", context, re.I):
        return "USD"
    if re.search(r"\bEUR\b|€", context, re.I):
        return "EUR"
    # Yen/Yuan glyphs are ambiguous without an explicit currency label.
    return None


def _unit(context: str) -> str | None:
    for unit in ("百万元", "千元", "万元", "亿元", "元", "billion", "million", "thousand"):
        if re.search(re.escape(unit), context, re.I):
            return unit
    return None
