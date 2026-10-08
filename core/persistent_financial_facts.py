"""Tenant-scoped SQL persistence for canonical, source-backed financial facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable, Protocol, runtime_checkable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.fact_ledger import FinancialFact, canonical_company
from core.financial_facts import FinancialFactRepository
from models.document import Document
from models.financial_fact import (
    FinancialFactConflictRecord,
    FinancialFactIngestionRun,
    FinancialFactRecord,
)


@dataclass(frozen=True, slots=True)
class PersistedConflict:
    run_id: str
    fact_id: str
    identity: tuple[str, ...]
    existing_value: Decimal | None
    incoming_value: Decimal | None
    existing_provenance: dict[str, Any] | None
    incoming_provenance: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    run_id: str
    status: str
    document_id: str
    document_version: str
    facts_eligible: int
    facts_inserted: int
    facts_unchanged: int
    facts_conflicted: int
    final_row_count: int


class FactLookupStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class FinancialFactLookupResult:
    status: FactLookupStatus
    facts: tuple[FinancialFact, ...] = ()
    conflicts: tuple[Any, ...] = ()


@runtime_checkable
class FinancialFactRepositoryProtocol(Protocol):
    """Common storage contract; callers do not branch on backend type."""

    def save_batch(self, facts: Iterable[FinancialFact], *, document_id: str, **metadata: Any) -> Any: ...

    def find(self, **filters: Any) -> tuple[FinancialFact, ...]: ...

    def find_by_metric(self, **filters: Any) -> tuple[FinancialFact, ...]: ...

    def find_by_document(
        self, *, document_id: str, document_version: str | None = None
    ) -> tuple[FinancialFact, ...]: ...

    def find_latest(self, *, company: str, metric: str, scope: str | None = None) -> FinancialFact | None: ...

    def find_unique(self, **filters: Any) -> FinancialFactLookupResult: ...

    def find_conflicts(self, *, document_id: str | None = None) -> tuple[Any, ...]: ...

    def count_by_document(self, *, document_id: str, document_version: str | None = None) -> int: ...


class InMemoryFinancialFactRepository:
    """Adapter exposing P1.5's in-memory store through the stable repository API."""

    def __init__(self, repository: FinancialFactRepository | None = None) -> None:
        self.repository = repository or FinancialFactRepository()

    def save_batch(self, facts: Iterable[FinancialFact], *, document_id: str, **metadata: Any) -> IngestionResult:
        incoming = tuple(facts)
        if not incoming:
            raise ValueError("refusing an empty financial fact ingestion batch")
        if any(str(fact.document_id) != str(document_id) for fact in incoming):
            raise ValueError("all facts must belong to the requested document")
        before = {fact.fact_id for fact in self.repository.facts}
        old_conflicts = len(self.repository.conflicts)
        self.repository.upsert(incoming)
        if len(self.repository.conflicts) > old_conflicts:
            raise FactConflictError("in-memory repository detected a conflicting P1.5 identity")
        after = {fact.fact_id for fact in self.repository.facts}
        inserted = len(after - before)
        unchanged = len(incoming) - inserted
        return IngestionResult(
            run_id="in-memory",
            status="SUCCESS",
            document_id=str(document_id),
            document_version=str(document_id),
            facts_eligible=len(incoming),
            facts_inserted=inserted,
            facts_unchanged=unchanged,
            facts_conflicted=0,
            final_row_count=self.count_by_document(document_id=document_id),
        )

    def find(self, **filters: Any) -> tuple[FinancialFact, ...]:
        return self.repository.find(**filters)

    def find_by_metric(
        self, *, metric: str, fiscal_year: int | str | None = None, scope: str | None = None
    ) -> tuple[FinancialFact, ...]:
        return tuple(
            fact
            for fact in self.repository.facts
            if fact.metric_id == metric
            and (fiscal_year is None or fact.fiscal_year == str(fiscal_year))
            and (scope is None or fact.scope == scope.upper())
        )

    def find_by_document(self, *, document_id: str, document_version: str | None = None) -> tuple[FinancialFact, ...]:
        return tuple(fact for fact in self.repository.facts if fact.document_id == str(document_id))

    def find_latest(self, *, company: str, metric: str, scope: str | None = None) -> FinancialFact | None:
        matches = self.repository.find(company=company, metric=metric, scope=scope, latest=True)
        if len(matches) > 1:
            raise AmbiguousFinancialFactError("latest fiscal year has multiple matching facts")
        return matches[0] if matches else None

    def find_unique(self, **filters: Any) -> FinancialFactLookupResult:
        facts = self.repository.find(**filters)
        company = canonical_company(filters.get("company", ""))
        metric = filters.get("metric")
        scope = filters.get("scope")
        fiscal_year = filters.get("fiscal_year")
        conflicts = tuple(
            conflict
            for conflict in self.find_conflicts(document_id=filters.get("document_id"))
            if conflict.identity[1] == company
            and conflict.identity[3] == metric
            and (scope is None or conflict.identity[5] == scope.upper())
            and (fiscal_year is None or str(fiscal_year) in conflict.identity[6])
        )
        if conflicts:
            return FinancialFactLookupResult(FactLookupStatus.CONFLICT, facts, conflicts)
        if not facts:
            return FinancialFactLookupResult(FactLookupStatus.NOT_FOUND)
        if len(facts) > 1:
            return FinancialFactLookupResult(FactLookupStatus.AMBIGUOUS, facts)
        return FinancialFactLookupResult(FactLookupStatus.FOUND, facts)

    def find_conflicts(self, *, document_id: str | None = None) -> tuple[Any, ...]:
        conflicts = self.repository.conflicts
        if document_id is None:
            return conflicts
        return tuple(
            conflict for conflict in conflicts if all(fact.document_id == str(document_id) for fact in conflict.facts)
        )

    def count_by_document(self, *, document_id: str, document_version: str | None = None) -> int:
        return len(self.find_by_document(document_id=document_id, document_version=document_version))


class FactConflictError(RuntimeError):
    """Raised when a stable P1.5 identity is presented with a different value."""


class AmbiguousFinancialFactError(RuntimeError):
    """Raised rather than arbitrarily selecting one matching fact or version."""


def _fact_provenance(fact: FinancialFact) -> dict[str, Any]:
    return {
        "document_id": fact.document_id,
        "document": fact.document,
        "page": fact.page,
        "section": fact.section,
        "table_id": fact.table_id,
        "row_id": fact.row_id,
        "source_locator": fact.source_locator,
        "source_text": fact.source_text,
        "original_label": fact.original_label,
        "raw_value": fact.raw_value,
    }


def _record_from_fact(
    fact: FinancialFact,
    *,
    numeric_document_id: int,
    tenant_id: int,
    document_version: str,
    run_id: str,
) -> FinancialFactRecord:
    identity = fact.structured_identity
    if not identity:
        raise ValueError("SQL repository accepts only P1.5 structured FinancialFacts")
    if not fact.fact_id:
        raise ValueError("fact_id is required")
    return FinancialFactRecord(
        fact_id=fact.fact_id,
        document_id=numeric_document_id,
        document_version=document_version,
        tenant_id=tenant_id,
        company_id=fact.company_id or fact.company,
        company_name=fact.company_name or fact.company,
        accounting_standard=fact.accounting_standard,
        canonical_metric=fact.metric_id,
        metric_label=fact.metric_label,
        original_label=fact.original_label,
        normalized_label=fact.normalized_label,
        statement_type=fact.statement_type,
        scope=fact.scope,
        fiscal_year=fact.fiscal_year,
        fiscal_quarter=fact.fiscal_quarter,
        period_type=fact.period_type,
        period_start=fact.period_start,
        period_end=fact.period_end,
        document_reporting_period=fact.document_reporting_period,
        fact_period=fact.fact_period,
        table_row_period=fact.table_row_period,
        table_column_period=fact.table_column_period,
        statement_period=fact.statement_period,
        value=fact.value,
        normalized_value=fact.normalized_value,
        raw_value=fact.raw_value,
        currency=fact.currency,
        unit=fact.unit,
        source_unit=fact.source_unit,
        page=fact.page,
        section=fact.section,
        table_id=fact.table_id,
        row_id=fact.row_id,
        chunk_id=fact.chunk_id,
        document=fact.document,
        source_locator=fact.source_locator,
        source_text=fact.source_text,
        evidence_text=fact.evidence_text,
        mapping_status=fact.mapping_status,
        mapping_rule=fact.mapping_rule,
        row_verification_status=fact.row_verification_status,
        source_kind=fact.source_kind,
        created_from=fact.created_from,
        derivation=fact.derivation,
        growth_basis=fact.growth_basis,
        display_unit=fact.display_unit,
        confidence=fact.confidence,
        dimension=fact.dimension,
        category=fact.category,
        structured_identity=list(identity),
        ingestion_run_id=run_id,
    )


def _to_fact(record: FinancialFactRecord) -> FinancialFact:
    # Reconstitute the P1.5 object as a value, not an ORM-bound row.
    return FinancialFact(
        fact_id=record.fact_id,
        company=record.company_id,
        metric_id=record.canonical_metric,
        metric_label=record.metric_label,
        value=Decimal(record.value),
        normalized_value=Decimal(record.normalized_value),
        unit=record.unit,
        currency=record.currency,
        fiscal_year=record.fiscal_year,
        fiscal_quarter=record.fiscal_quarter,
        period_start=record.period_start,
        period_end=record.period_end,
        period_type=record.period_type,
        document_reporting_period=record.document_reporting_period,
        fact_period=record.fact_period,
        table_row_period=record.table_row_period,
        table_column_period=record.table_column_period,
        document=record.document,
        page=record.page,
        section=record.section,
        chunk_id=record.chunk_id,
        evidence_text=record.evidence_text,
        confidence=float(record.confidence),
        derivation=record.derivation,
        growth_basis=record.growth_basis,
        display_unit=record.display_unit,
        document_id=str(record.document_id),
        dimension=record.dimension,
        category=record.category,
        company_id=record.company_id,
        company_name=record.company_name,
        accounting_standard=record.accounting_standard,
        original_label=record.original_label,
        normalized_label=record.normalized_label,
        statement_type=record.statement_type,
        scope=record.scope,
        raw_value=record.raw_value,
        source_unit=record.source_unit,
        mapping_status=record.mapping_status,
        mapping_rule=record.mapping_rule,
        row_verification_status=record.row_verification_status,
        source_kind=record.source_kind,
        created_from=record.created_from,
        table_id=record.table_id,
        row_id=record.row_id,
        source_locator=record.source_locator,
        source_text=record.source_text,
        statement_period=record.statement_period,
        structured_identity=tuple(record.structured_identity),
    )


class SQLFinancialFactRepository:
    """A single-tenant facade over the shared SQLAlchemy session/database."""

    def __init__(self, session: Session, *, tenant_id: int) -> None:
        if tenant_id <= 0:
            raise ValueError("tenant_id must be an explicit positive tenant scope")
        self.session = session
        self.tenant_id = tenant_id

    def save_batch(
        self,
        facts: Iterable[FinancialFact],
        *,
        document_id: str,
        fail_after_insert: int | None = None,
        rows_seen: int | None = None,
        rows_verified: int | None = None,
        rows_mapped: int | None = None,
        facts_rejected: int = 0,
    ) -> IngestionResult:
        incoming = tuple(facts)
        try:
            numeric_document_id = int(document_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("document_id must reference an existing relational documents.id") from exc
        if not incoming:
            raise ValueError("refusing an empty financial fact ingestion batch")
        rows_seen = len(incoming) if rows_seen is None else rows_seen
        rows_verified = len(incoming) if rows_verified is None else rows_verified
        rows_mapped = len(incoming) if rows_mapped is None else rows_mapped
        if min(rows_seen, rows_verified, rows_mapped, facts_rejected) < 0:
            raise ValueError("ingestion row counters cannot be negative")
        if rows_verified > rows_seen or rows_mapped > rows_verified or len(incoming) > rows_mapped:
            raise ValueError("ingestion row counters are inconsistent with the eligible fact batch")
        if fail_after_insert is not None and fail_after_insert < 1:
            raise ValueError("fail_after_insert must be a positive count")
        if any(str(fact.document_id) != str(numeric_document_id) for fact in incoming):
            raise ValueError("all facts must belong to the requested document version")
        for fact in incoming:
            identity = fact.structured_identity
            if identity is None or len(identity) != 9:
                raise ValueError("SQL repository accepts only complete P1.5 structured FinancialFacts")
            company_id = fact.company_id or fact.company
            expected_dimensions = (
                str(numeric_document_id),
                company_id,
                fact.accounting_standard,
                fact.metric_id,
                fact.section,
                fact.scope,
                None,
                (fact.currency or "").upper(),
                fact.unit,
            )
            actual_dimensions = (*identity[:6], None, identity[7], identity[8])
            if actual_dimensions != expected_dimensions:
                raise ValueError("fact fields do not match the authoritative P1.5 structured identity")

        document = self.session.scalar(
            select(Document).where(
                Document.id == numeric_document_id,
                Document.tenant_id == self.tenant_id,
            )
        )
        if document is None:
            self.session.rollback()
            raise LookupError("document not found in this tenant")
        if not document.content_sha256 or len(document.content_sha256) != 64:
            self.session.rollback()
            raise ValueError("document content_sha256 is required as immutable version identity")
        document_version = document.content_sha256.casefold()
        self.session.commit()

        run_id = str(uuid4())
        run = FinancialFactIngestionRun(
            run_id=run_id,
            tenant_id=self.tenant_id,
            document_id=numeric_document_id,
            document_version=document_version,
            status="RUNNING",
            rows_seen=rows_seen,
            rows_verified=rows_verified,
            rows_mapped=rows_mapped,
            facts_eligible=len(incoming),
            facts_rejected=facts_rejected,
        )
        self.session.add(run)
        self.session.commit()

        inserted = unchanged = 0
        conflicts: list[tuple[FinancialFactRecord | None, FinancialFact]] = []
        try:
            with self.session.begin():
                run = self.session.scalar(
                    select(FinancialFactIngestionRun).where(FinancialFactIngestionRun.run_id == run_id)
                )
                assert run is not None
                by_id: dict[str, FinancialFactRecord] = {}
                for fact in incoming:
                    existing = by_id.get(fact.fact_id) or self.session.scalar(
                        select(FinancialFactRecord).where(
                            FinancialFactRecord.tenant_id == self.tenant_id,
                            FinancialFactRecord.document_id == numeric_document_id,
                            FinancialFactRecord.fact_id == fact.fact_id,
                        )
                    )
                    if existing is not None:
                        existing_identity = tuple(existing.structured_identity)
                        if (
                            existing_identity != fact.structured_identity
                            or existing.normalized_value != fact.normalized_value
                        ):
                            conflicts.append((existing, fact))
                            raise FactConflictError(f"same P1.5 identity has conflicting value: {fact.fact_id}")
                        unchanged += 1
                        continue
                    record = _record_from_fact(
                        fact,
                        numeric_document_id=numeric_document_id,
                        tenant_id=self.tenant_id,
                        document_version=document_version,
                        run_id=run_id,
                    )
                    self.session.add(record)
                    by_id[fact.fact_id] = record
                    inserted += 1
                    if fail_after_insert == inserted:
                        self.session.flush()
                        raise RuntimeError("injected mid-ingestion failure")
                self.session.flush()
                run.status = "SUCCESS"
                run.facts_inserted = inserted
                run.facts_unchanged = unchanged
                run.facts_conflicted = 0
                run.completed_at = datetime.now(timezone.utc)
            count = self.count_by_document(document_id=document_id, document_version=document_version)
            return IngestionResult(
                run_id,
                "SUCCESS",
                str(numeric_document_id),
                document_version,
                len(incoming),
                inserted,
                unchanged,
                0,
                count,
            )
        except Exception as exc:
            self.session.rollback()
            conflict_count = len(conflicts)
            with self.session.begin():
                run = self.session.scalar(
                    select(FinancialFactIngestionRun).where(FinancialFactIngestionRun.run_id == run_id)
                )
                assert run is not None
                run.status = "FAILED"
                run.facts_inserted = 0
                run.facts_unchanged = 0
                run.facts_conflicted = conflict_count
                run.error_summary = f"{type(exc).__name__}: {exc}"[:2000]
                run.completed_at = datetime.now(timezone.utc)
                for existing, incoming_fact in conflicts:
                    self.session.add(
                        FinancialFactConflictRecord(
                            run_id=run_id,
                            tenant_id=self.tenant_id,
                            document_id=numeric_document_id,
                            document_version=document_version,
                            fact_id=incoming_fact.fact_id,
                            identity=list(incoming_fact.structured_identity or ()),
                            existing_value=existing.normalized_value if existing else None,
                            incoming_value=incoming_fact.normalized_value,
                            existing_provenance=(
                                {
                                    "document": existing.document,
                                    "company_id": existing.company_id,
                                    "canonical_metric": existing.canonical_metric,
                                    "scope": existing.scope,
                                    "fiscal_year": existing.fiscal_year,
                                    "period_start": existing.period_start,
                                    "period_end": existing.period_end,
                                    "raw_value": existing.raw_value,
                                    "page": existing.page,
                                    "table_id": existing.table_id,
                                    "row_id": existing.row_id,
                                    "source_locator": existing.source_locator,
                                    "source_text": existing.source_text,
                                }
                                if existing
                                else None
                            ),
                            incoming_provenance=_fact_provenance(incoming_fact),
                        )
                    )
            raise

    def find(
        self,
        *,
        company: str,
        metric: str,
        fiscal_year: int | str | None = None,
        period_type: str | None = None,
        scope: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        document_id: str | None = None,
        document_version: str | None = None,
        accounting_standard: str | None = None,
        latest: bool = False,
    ) -> tuple[FinancialFact, ...]:
        if fiscal_year is not None and latest:
            raise ValueError("choose explicit fiscal_year or latest, not both")
        statement = select(FinancialFactRecord).where(
            FinancialFactRecord.tenant_id == self.tenant_id,
            FinancialFactRecord.canonical_metric == metric,
        )
        company_id = canonical_company(company)
        statement = statement.where(
            (FinancialFactRecord.company_id == company_id) | (FinancialFactRecord.company_name.ilike(company))
        )
        if fiscal_year is not None:
            statement = statement.where(FinancialFactRecord.fiscal_year == str(fiscal_year))
        if period_type is not None:
            statement = statement.where(FinancialFactRecord.period_type == period_type.upper())
        if scope is not None:
            statement = statement.where(FinancialFactRecord.scope == scope.upper())
        if period_start is not None:
            statement = statement.where(FinancialFactRecord.period_start == period_start)
        if period_end is not None:
            statement = statement.where(FinancialFactRecord.period_end == period_end)
        if document_id is not None:
            statement = statement.where(FinancialFactRecord.document_id == int(document_id))
        if document_version is not None:
            statement = statement.where(FinancialFactRecord.document_version == document_version.casefold())
        if accounting_standard is not None:
            statement = statement.where(FinancialFactRecord.accounting_standard == accounting_standard.upper())
        records = list(
            self.session.scalars(
                statement.order_by(
                    FinancialFactRecord.fiscal_year,
                    FinancialFactRecord.period_start,
                    FinancialFactRecord.period_end,
                    FinancialFactRecord.document_id,
                    FinancialFactRecord.scope,
                    FinancialFactRecord.fact_id,
                )
            )
        )
        facts = tuple(_to_fact(record) for record in records)
        if latest and facts:
            years = [int(fact.fiscal_year) for fact in facts if fact.fiscal_year and fact.fiscal_year.isdigit()]
            if years:
                newest = str(max(years))
                facts = tuple(fact for fact in facts if fact.fiscal_year == newest)
        return facts

    def find_by_metric(
        self, *, metric: str, fiscal_year: int | str | None = None, scope: str | None = None
    ) -> tuple[FinancialFact, ...]:
        statement = select(FinancialFactRecord).where(
            FinancialFactRecord.tenant_id == self.tenant_id,
            FinancialFactRecord.canonical_metric == metric,
        )
        if fiscal_year is not None:
            statement = statement.where(FinancialFactRecord.fiscal_year == str(fiscal_year))
        if scope is not None:
            statement = statement.where(FinancialFactRecord.scope == scope.upper())
        return tuple(
            _to_fact(item)
            for item in self.session.scalars(
                statement.order_by(
                    FinancialFactRecord.fiscal_year, FinancialFactRecord.document_id, FinancialFactRecord.fact_id
                )
            )
        )

    def find_by_document(self, *, document_id: str, document_version: str | None = None) -> tuple[FinancialFact, ...]:
        statement = select(FinancialFactRecord).where(
            FinancialFactRecord.tenant_id == self.tenant_id,
            FinancialFactRecord.document_id == int(document_id),
        )
        if document_version is not None:
            statement = statement.where(FinancialFactRecord.document_version == document_version.casefold())
        return tuple(
            _to_fact(item)
            for item in self.session.scalars(
                statement.order_by(FinancialFactRecord.canonical_metric, FinancialFactRecord.fact_id)
            )
        )

    def find_latest(self, *, company: str, metric: str, scope: str | None = None) -> FinancialFact | None:
        candidates = self.find(company=company, metric=metric, scope=scope, latest=True)
        if not candidates:
            return None
        if len(candidates) != 1:
            raise AmbiguousFinancialFactError(
                "latest fiscal year has multiple matching scopes/documents/versions; specify a document or scope"
            )
        return candidates[0]

    def find_unique(
        self,
        *,
        company: str,
        metric: str,
        fiscal_year: int | str | None = None,
        period_type: str | None = None,
        scope: str | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        document_id: str | None = None,
        document_version: str | None = None,
        accounting_standard: str | None = None,
    ) -> FinancialFactLookupResult:
        facts = self.find(
            company=company,
            metric=metric,
            fiscal_year=fiscal_year,
            period_type=period_type,
            scope=scope,
            period_start=period_start,
            period_end=period_end,
            document_id=document_id,
            document_version=document_version,
            accounting_standard=accounting_standard,
        )
        conflicts = tuple(
            conflict
            for conflict in self.find_conflicts(document_id=document_id)
            if conflict.identity[1] == canonical_company(company)
            and conflict.identity[3] == metric
            and (scope is None or conflict.identity[5] == scope.upper())
            and (fiscal_year is None or str(fiscal_year) in conflict.identity[6])
            and (
                period_type is None
                or conflict.identity[6].upper().startswith(f"{period_type.upper()}:")
            )
            and (document_version is None or conflict.document_version == document_version.casefold())
            and (period_start is None or period_start in conflict.identity[6])
            and (period_end is None or period_end in conflict.identity[6])
        )
        if conflicts:
            return FinancialFactLookupResult(FactLookupStatus.CONFLICT, facts, conflicts)
        if not facts:
            return FinancialFactLookupResult(FactLookupStatus.NOT_FOUND)
        if len(facts) > 1:
            return FinancialFactLookupResult(FactLookupStatus.AMBIGUOUS, facts)
        return FinancialFactLookupResult(FactLookupStatus.FOUND, facts)

    def find_conflicts(self, *, document_id: str | None = None) -> tuple[PersistedConflict, ...]:
        statement = select(FinancialFactConflictRecord).where(FinancialFactConflictRecord.tenant_id == self.tenant_id)
        if document_id is not None:
            statement = statement.where(FinancialFactConflictRecord.document_id == int(document_id))
        return tuple(
            PersistedConflict(
                row.run_id,
                row.fact_id,
                tuple(row.identity),
                row.existing_value,
                row.incoming_value,
                row.existing_provenance,
                row.incoming_provenance,
            )
            for row in self.session.scalars(statement.order_by(FinancialFactConflictRecord.id))
        )

    def count_by_document(self, *, document_id: str, document_version: str | None = None) -> int:
        statement = select(FinancialFactRecord).where(
            FinancialFactRecord.tenant_id == self.tenant_id,
            FinancialFactRecord.document_id == int(document_id),
        )
        if document_version is not None:
            statement = statement.where(FinancialFactRecord.document_version == document_version.casefold())
        return len(self.session.scalars(statement).all())
