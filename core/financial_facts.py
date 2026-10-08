"""Strict structured financial facts built from verified statement rows.

This layer deliberately reuses :class:`core.fact_ledger.FinancialFact` and
``FactLedger``. It adds no production persistence and performs no semantic or
numeric inference beyond explicit registry rules and exact unit conversion.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Iterable, Mapping

from core.fact_ledger import FactLedger, FinancialFact, canonical_company
from core.financial_metric_registry import (
    FINANCIAL_METRIC_REGISTRY,
    MetricMappingStatus,
    MetricNormalization,
    normalize_financial_table_row,
)
from core.financial_table_rows import FinancialTableRow, VerificationStatus


class EligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class FinancialDocumentContext:
    """Explicit document facts; values must be supported by source metadata."""

    company_id: str | None = None
    company_name: str | None = None
    accounting_standard: str = "UNKNOWN"
    accounting_standard_source: str | None = None
    fiscal_year_start: str | None = None
    fiscal_year_end: str | None = None
    fiscal_calendar_source: str | None = None

    def __post_init__(self) -> None:
        standard = self.accounting_standard.upper()
        if standard not in {"CAS", "US_GAAP", "IFRS", "UNKNOWN"}:
            raise ValueError(f"unsupported accounting standard: {standard}")
        object.__setattr__(self, "accounting_standard", standard)
        if standard != "UNKNOWN" and not self.accounting_standard_source:
            raise ValueError("accounting standard requires auditable source evidence")
        if bool(self.fiscal_year_start) != bool(self.fiscal_year_end):
            raise ValueError("fiscal calendar requires both start and end dates")
        if self.fiscal_year_start and not self.fiscal_calendar_source:
            raise ValueError("fiscal calendar dates require auditable source evidence")


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    status: EligibilityStatus
    reasons: tuple[str, ...]
    normalization: MetricNormalization


class FinancialFactEligibilityGate:
    """Fail-closed eligibility rules for a reported, source-backed fact."""

    def assess(
        self,
        row: FinancialTableRow,
        *,
        normalization: MetricNormalization | None = None,
        context: FinancialDocumentContext | None = None,
    ) -> EligibilityDecision:
        mapped = normalization or normalize_financial_table_row(row)
        reasons: list[str] = []
        if row.verification_status != VerificationStatus.VERIFIED:
            reasons.append("ROW_NOT_VERIFIED")
        if mapped.mapping_status not in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}:
            reasons.append(f"METRIC_{mapped.mapping_status.value}")
        if not mapped.canonical_metric:
            reasons.append("CANONICAL_METRIC_MISSING")
        definition = FINANCIAL_METRIC_REGISTRY.get(mapped.canonical_metric or "")
        if definition and row.statement_type not in definition.statement_types:
            reasons.append("STATEMENT_TYPE_MISMATCH")
        if not row.period:
            reasons.append("PERIOD_MISSING")
        elif mapped.canonical_metric:
            fiscal_year, period_start, period_end, period_type = _period_fields(
                row, metric=mapped.canonical_metric, context=context or FinancialDocumentContext()
            )
            if not fiscal_year or not period_type or not period_end:
                reasons.append("PERIOD_NOT_EXPLICITLY_CLASSIFIABLE")
            if period_type == "DURATION" and not period_start:
                reasons.append("DURATION_START_MISSING")
        if row.value is None:
            reasons.append("VALUE_MISSING")
        if not row.unit:
            reasons.append("UNIT_MISSING")
        if not row.currency:
            reasons.append("CURRENCY_MISSING")
        elif row.unit:
            try:
                _base_unit(row.unit, row.currency)
            except ValueError:
                reasons.append("UNIT_NOT_NORMALIZABLE")
        if not row.scope or row.scope.casefold() not in {"consolidated", "parent", "parent_company"}:
            reasons.append("SCOPE_MISSING_OR_UNKNOWN")
        if not row.statement_type:
            reasons.append("STATEMENT_TYPE_MISSING")
        if not row.page or not row.source_locator or not row.source_text.strip():
            reasons.append("SOURCE_PROVENANCE_INCOMPLETE")
        if not row.document_id or not row.company:
            reasons.append("DOCUMENT_OR_COMPANY_MISSING")
        if context is not None and context.company_id:
            if context.company_name:
                if _normalized_company_name(row.company) != _normalized_company_name(context.company_name):
                    reasons.append("COMPANY_CONTEXT_MISMATCH")
            elif canonical_company(row.company or "") != context.company_id:
                reasons.append("COMPANY_CONTEXT_MISMATCH")
        return EligibilityDecision(
            EligibilityStatus.REJECTED if reasons else EligibilityStatus.ELIGIBLE,
            tuple(dict.fromkeys(reasons)),
            mapped,
        )


_UNIT_MULTIPLIERS: Mapping[str, Decimal] = {
    "元": Decimal("1"),
    "人民币元": Decimal("1"),
    "千元": Decimal("1000"),
    "万元": Decimal("10000"),
    "百万元": Decimal("1000000"),
    "亿元": Decimal("100000000"),
    "yuan": Decimal("1"),
    "cny_yuan": Decimal("1"),
    "thousand yuan": Decimal("1000"),
    "thousand cny": Decimal("1000"),
    "million yuan": Decimal("1000000"),
    "million cny": Decimal("1000000"),
    "billion yuan": Decimal("1000000000"),
    "billion cny": Decimal("1000000000"),
    "usd": Decimal("1"),
    "us dollar": Decimal("1"),
    "thousand usd": Decimal("1000"),
    "million usd": Decimal("1000000"),
    "billion usd": Decimal("1000000000"),
}


def _base_unit(unit: str, currency: str) -> tuple[str, Decimal]:
    key = re.sub(r"\s+", " ", unit.strip().casefold())
    multiplier = _UNIT_MULTIPLIERS.get(key)
    if multiplier is None:
        raise ValueError(f"unsupported monetary source unit: {unit!r}")
    return f"{currency.upper()}_YUAN" if currency.upper() == "CNY" else f"{currency.upper()}_UNIT", multiplier


def _period_fields(
    row: FinancialTableRow,
    *,
    metric: str,
    context: FinancialDocumentContext,
) -> tuple[str, str | None, str | None, str | None]:
    definition = FINANCIAL_METRIC_REGISTRY.get(metric)
    semantics = definition.period_semantics if definition else "unknown"
    period = str(row.period or "").strip()
    iso = re.fullmatch(r"(20\d{2})-(\d{2})-(\d{2})", period)
    if iso:
        if semantics == "point_in_time":
            return str(row.fiscal_year or int(iso.group(1))), None, period, "INSTANT"
        if semantics == "duration" and context.fiscal_year_start and context.fiscal_year_end:
            year = str(row.fiscal_year or int(iso.group(1)))
            return (
                year,
                re.sub(r"^\d{4}", year, context.fiscal_year_start),
                re.sub(r"^\d{4}", year, context.fiscal_year_end),
                "DURATION",
            )
        return str(row.fiscal_year or int(iso.group(1))), None, None, ""
    year_match = re.fullmatch(r"(?:FY\s*)?(20\d{2})(?:年度|年)?", period, re.I)
    if not year_match:
        return str(row.fiscal_year) if row.fiscal_year else "", None, None, ""
    year = int(year_match.group(1))
    if semantics == "point_in_time":
        if not context.fiscal_year_start or not context.fiscal_year_end:
            return str(year), None, None, ""
        label = (row.row_label or "").casefold()
        if "期初" in label or "beginning" in label:
            instant = re.sub(r"^\d{4}", str(year), context.fiscal_year_start)
            return str(year), instant, instant, "INSTANT"
        instant = re.sub(r"^\d{4}", str(year), context.fiscal_year_end)
        return str(year), instant, instant, "INSTANT"
    if semantics != "duration":
        return str(year), None, None, ""
    start, end = context.fiscal_year_start, context.fiscal_year_end
    if start and end:
        start = re.sub(r"^\d{4}", str(year), start)
        end = re.sub(r"^\d{4}", str(year), end)
    return str(year), start, end, "DURATION"


def _stable_fact_id(identity: tuple[str, ...]) -> str:
    digest = hashlib.sha256("\x1f".join(identity).encode("utf-8")).hexdigest()[:24]
    return f"ff_{digest}"


def _scope(scope: str | None) -> str:
    value = (scope or "").casefold()
    return "CONSOLIDATED" if value == "consolidated" else "PARENT_COMPANY"


def _normalized_company_name(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").casefold())


def _company_matches(query: str, fact: FinancialFact) -> bool:
    query_key = canonical_company(query)
    if query_key == fact.company_id or query_key == fact.company:
        return True
    query_name = _normalized_company_name(query)
    fact_name = _normalized_company_name(fact.company_name)
    # Generic short-name matching avoids coupling ontology to issuer aliases.
    return len(query_name) >= 3 and bool(fact_name) and (query_name in fact_name or fact_name in query_name)


class FinancialFactFactory:
    def __init__(self, gate: FinancialFactEligibilityGate | None = None) -> None:
        self.gate = gate or FinancialFactEligibilityGate()

    def create(
        self,
        row: FinancialTableRow,
        *,
        context: FinancialDocumentContext | None = None,
        normalization: MetricNormalization | None = None,
    ) -> FinancialFact:
        context = context or FinancialDocumentContext()
        decision = self.gate.assess(row, normalization=normalization, context=context)
        if decision.status != EligibilityStatus.ELIGIBLE:
            raise ValueError("row is not eligible: " + ", ".join(decision.reasons))
        mapped = decision.normalization
        assert mapped.canonical_metric and row.value is not None and row.unit and row.currency
        unit, multiplier = _base_unit(row.unit, row.currency)
        value = row.value * multiplier
        fiscal_year, period_start, period_end, period_type = _period_fields(
            row, metric=mapped.canonical_metric, context=context
        )
        if not period_type:
            raise ValueError("row period cannot be classified using explicit period semantics")
        scope = _scope(row.scope)
        company_name = context.company_name or row.company or ""
        company_id = context.company_id or canonical_company(company_name)
        document_id = row.document_id or ""
        period_key = f"{period_type}:{period_start or ''}:{period_end or row.period or ''}"
        identity = (
            document_id,
            company_id,
            context.accounting_standard,
            mapped.canonical_metric,
            row.statement_type or "",
            scope,
            period_key,
            row.currency.upper(),
            unit,
        )
        table_id_match = re.search(r"table\s+(\d+)", row.source_locator or "", re.I)
        row_id_match = re.search(r"row\s+(\d+)", row.source_locator or "", re.I)
        fact_id = _stable_fact_id(identity)
        label = mapped.normalized_label
        return FinancialFact(
            fact_id=fact_id,
            company=company_id,
            metric_id=mapped.canonical_metric,
            metric_label=label,
            value=value,
            normalized_value=value,
            unit=unit,
            currency=row.currency.upper(),
            fiscal_year=fiscal_year,
            fiscal_quarter=None,
            period_start=period_start,
            period_end=period_end,
            period_type=period_type,
            document_reporting_period=row.period,
            fact_period=row.period,
            table_row_period=row.period,
            table_column_period=row.column_label,
            document=row.source or row.document_id or "",
            page=row.page,
            section=row.statement_type,
            chunk_id=row.source_locator or fact_id,
            evidence_text=row.source_text,
            confidence=1.0,
            document_id=document_id,
            dimension=scope,
            category=FINANCIAL_METRIC_REGISTRY.get(mapped.canonical_metric).category
            if FINANCIAL_METRIC_REGISTRY.get(mapped.canonical_metric)
            else None,
            company_id=company_id,
            company_name=company_name,
            accounting_standard=context.accounting_standard,
            original_label=mapped.original_label,
            normalized_label=mapped.normalized_label,
            statement_type=row.statement_type,
            scope=scope,
            raw_value=row.raw_value,
            source_unit=row.unit,
            mapping_status=mapped.mapping_status.value,
            mapping_rule=mapped.mapping_rule,
            row_verification_status=row.verification_status.value,
            source_kind="FINANCIAL_STATEMENT",
            created_from="financial_table_row",
            table_id=f"{document_id}:page:{row.page}:table:{table_id_match.group(1) if table_id_match else 'unknown'}",
            row_id=row_id_match.group(1) if row_id_match else None,
            source_locator=row.source_locator,
            source_text=row.source_text,
            statement_period=row.period,
            structured_identity=identity,
        )


@dataclass(frozen=True, slots=True)
class FactConflict:
    identity: tuple[str, ...]
    facts: tuple[FinancialFact, ...]


class FinancialFactRepository:
    """Deterministic, in-memory repository; never persists to production."""

    def __init__(self, facts: Iterable[FinancialFact] = ()) -> None:
        self._facts: dict[tuple[str, ...], FinancialFact] = {}
        self._conflicts: dict[tuple[str, ...], list[FinancialFact]] = {}
        self._duplicate_sources: dict[tuple[str, ...], list[FinancialFact]] = {}
        self.duplicates = 0
        self.upsert(facts)

    @property
    def conflicts(self) -> tuple[FactConflict, ...]:
        return tuple(FactConflict(key, tuple(values)) for key, values in self._conflicts.items())

    @property
    def facts(self) -> tuple[FinancialFact, ...]:
        return tuple(fact for key, fact in self._facts.items() if key not in self._conflicts)

    @property
    def duplicate_sources(self) -> Mapping[tuple[str, ...], tuple[FinancialFact, ...]]:
        """Keep overlapping chunk/source provenance available after deduplication."""
        return {key: tuple(items) for key, items in self._duplicate_sources.items()}

    def upsert(self, facts: Iterable[FinancialFact]) -> None:
        for fact in facts:
            identity = fact.structured_identity
            if identity is None:
                raise ValueError("repository accepts only structured FinancialFacts")
            if identity in self._conflicts:
                if all(item.normalized_value != fact.normalized_value for item in self._conflicts[identity]):
                    self._conflicts[identity].append(fact)
                else:
                    self.duplicates += 1
                    self._duplicate_sources.setdefault(identity, []).append(fact)
                continue
            existing = self._facts.get(identity)
            if existing is None:
                self._facts[identity] = fact
            elif existing.normalized_value == fact.normalized_value:
                self.duplicates += 1
                self._duplicate_sources.setdefault(identity, [existing]).append(fact)
            else:
                self._conflicts[identity] = [existing, fact]
                del self._facts[identity]

    def find(
        self,
        *,
        company: str,
        metric: str,
        fiscal_year: int | str | None = None,
        scope: str | None = "CONSOLIDATED",
        document_id: str | None = None,
        accounting_standard: str | None = None,
        latest: bool = False,
    ) -> tuple[FinancialFact, ...]:
        if fiscal_year is not None and latest:
            raise ValueError("choose explicit fiscal_year or latest, not both")
        wanted_scope = _scope(scope) if scope else None
        if scope and scope.upper() in {"CONSOLIDATED", "PARENT_COMPANY"}:
            wanted_scope = scope.upper()
        candidates = [
            fact
            for fact in self.facts
            if _company_matches(company, fact)
            and fact.metric_id == metric
            and (wanted_scope is None or fact.scope == wanted_scope)
            and (document_id is None or fact.document_id == document_id)
            and (accounting_standard is None or fact.accounting_standard == accounting_standard.upper())
            and (fiscal_year is None or fact.fiscal_year == str(fiscal_year))
        ]
        if latest and candidates:
            year = max(
                (int(fact.fiscal_year) for fact in candidates if fact.fiscal_year and fact.fiscal_year.isdigit()),
                default=None,
            )
            if year is not None:
                candidates = [fact for fact in candidates if fact.fiscal_year == str(year)]
        return tuple(sorted(candidates, key=lambda fact: (fact.period_type, fact.period_end or "", fact.page or 0)))

    def find_latest(self, *, company: str, metric: str, scope: str | None = "CONSOLIDATED") -> FinancialFact | None:
        found = self.find(company=company, metric=metric, scope=scope, latest=True)
        return found[-1] if found else None

    def to_fact_ledger(self) -> FactLedger:
        return FactLedger.from_financial_facts(self.facts)


@dataclass(frozen=True, slots=True)
class FinancialFactRetrieval:
    facts: tuple[FinancialFact, ...]
    selected_scope: str | None
    selection_reason: str
    conflicts: tuple[FactConflict, ...] = ()


class StructuredFinancialFactRetrieval:
    def __init__(self, repository: FinancialFactRepository, *, preferred_scope: str = "CONSOLIDATED") -> None:
        if preferred_scope not in {"CONSOLIDATED", "PARENT_COMPANY"}:
            raise ValueError("unsupported preferred scope")
        self.repository = repository
        self.preferred_scope = preferred_scope

    def get_financial_fact(
        self,
        *,
        company: str,
        metric: str,
        fiscal_year: int | str | None = None,
        scope: str | None = None,
        document_id: str | None = None,
        accounting_standard: str | None = None,
        latest: bool = False,
    ) -> FinancialFactRetrieval:
        chosen_scope = scope or self.preferred_scope
        facts = self.repository.find(
            company=company,
            metric=metric,
            fiscal_year=fiscal_year,
            scope=chosen_scope,
            document_id=document_id,
            accounting_standard=accounting_standard,
            latest=latest,
        )
        wanted_year = str(fiscal_year) if fiscal_year is not None else None
        conflicts = tuple(
            conflict
            for conflict in self.repository.conflicts
            if any(_company_matches(company, fact) for fact in conflict.facts)
            and conflict.identity[3] == metric
            and conflict.identity[5] == chosen_scope
            and (wanted_year is None or wanted_year in conflict.identity[6])
        )
        reason = "explicit_scope" if scope else f"preferred_scope:{chosen_scope}"
        if latest:
            reason += ";latest_from_stored_fiscal_year"
        return FinancialFactRetrieval(facts, chosen_scope, reason, conflicts)


def accounting_equation_audit(
    facts: Iterable[FinancialFact], *, tolerance: Decimal = Decimal("0.01")
) -> tuple[dict[str, object], ...]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, FinancialFact]] = {}
    for fact in facts:
        if fact.metric_id not in {"total_assets", "total_liabilities", "total_equity"}:
            continue
        key = (
            fact.company_id or fact.company,
            fact.document_id or "",
            fact.scope or "",
            fact.fiscal_year or "",
            fact.accounting_standard,
        )
        grouped.setdefault(key, {})[fact.metric_id] = fact
    results = []
    for identity, group in grouped.items():
        if set(group) != {"total_assets", "total_liabilities", "total_equity"}:
            continue
        assets, liabilities, equity = (group[name] for name in ("total_assets", "total_liabilities", "total_equity"))
        difference = assets.normalized_value - liabilities.normalized_value - equity.normalized_value
        results.append(
            {
                "identity": identity,
                "difference": difference,
                "tolerance": tolerance,
                "status": "PASS" if abs(difference) <= tolerance else "AUDIT_WARNING",
                "source_pages": (assets.page, liabilities.page, equity.page),
            }
        )
    return tuple(results)


def cash_flow_sanity_audit(
    facts: Iterable[FinancialFact], *, tolerance: Decimal = Decimal("0.01")
) -> tuple[dict[str, object], ...]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, FinancialFact]] = {}
    names = {
        "cash_and_cash_equivalents_beginning",
        "cash_and_cash_equivalents_net_increase",
        "cash_and_cash_equivalents_ending",
    }
    for fact in facts:
        if fact.metric_id not in names:
            continue
        key = (
            fact.company_id or fact.company,
            fact.document_id or "",
            fact.scope or "",
            fact.fiscal_year or "",
            fact.accounting_standard,
        )
        grouped.setdefault(key, {})[fact.metric_id] = fact
    results = []
    for identity, group in grouped.items():
        if set(group) != names:
            continue
        begin, increase, ending = (
            group[name]
            for name in (
                "cash_and_cash_equivalents_beginning",
                "cash_and_cash_equivalents_net_increase",
                "cash_and_cash_equivalents_ending",
            )
        )
        difference = begin.normalized_value + increase.normalized_value - ending.normalized_value
        results.append(
            {
                "identity": identity,
                "difference": difference,
                "tolerance": tolerance,
                "status": "PASS" if abs(difference) <= tolerance else "AUDIT_WARNING",
                "source_pages": (begin.page, increase.page, ending.page),
                "formula": "beginning + reported net increase = ending",
            }
        )
    return tuple(results)


def financial_facts_from_rows(
    rows: Iterable[FinancialTableRow],
    *,
    context: FinancialDocumentContext | None = None,
) -> tuple[FinancialFact, ...]:
    factory = FinancialFactFactory()
    facts = []
    for row in rows:
        decision = factory.gate.assess(row, context=context)
        if decision.status == EligibilityStatus.ELIGIBLE:
            facts.append(factory.create(row, context=context, normalization=decision.normalization))
    return tuple(facts)


def rows_from_json(payload: str) -> tuple[FinancialTableRow, ...]:
    """Rehydrate typed Chroma metadata without upgrading its trust status."""
    from core.financial_table_rows import VerificationStatus

    raw_rows = json.loads(payload)
    if not isinstance(raw_rows, list):
        raise ValueError("financial_table_rows_json must be an array")
    output = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        fields = {key: raw.get(key) for key in FinancialTableRow.__dataclass_fields__ if key in raw}
        if "value" in fields:
            fields["value"] = Decimal(str(fields["value"])) if fields["value"] not in (None, "") else None
        fields["verification_status"] = VerificationStatus(str(raw.get("verification_status", "UNVERIFIED")))
        reasons = raw.get("verification_reasons", ())
        if isinstance(reasons, str):
            try:
                reasons = json.loads(reasons)
            except json.JSONDecodeError:
                reasons = (reasons,) if reasons else ()
        fields["verification_reasons"] = tuple(reasons or ())
        for key in ("fiscal_year", "page"):
            if fields.get(key) not in (None, ""):
                fields[key] = int(fields[key])
            else:
                fields[key] = None
        fields["column_binding_proven"] = bool(raw.get("column_binding_proven", False))
        fields["source_text"] = str(raw.get("source_text", ""))
        output.append(FinancialTableRow(**fields))
    return tuple(output)
