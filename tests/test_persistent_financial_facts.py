from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session

from core.financial_facts import (
    FinancialDocumentContext,
    accounting_equation_audit,
    cash_flow_sanity_audit,
    financial_facts_from_rows,
)
from core.financial_table_rows import VerificationStatus
from core.persistent_financial_facts import (
    AmbiguousFinancialFactError,
    FactConflictError,
    FactLookupStatus,
    FinancialFactRepositoryProtocol,
    InMemoryFinancialFactRepository,
    SQLFinancialFactRepository,
)
from document_loader import parse_pdf
from models.document import Document
from models.financial_fact import FinancialFactIngestionRun
from models.tenant import Tenant
from storage.database import _import_models
from storage.types import ExactFinancialDecimal

FIXTURE = Path(__file__).parent / "fixtures" / "moutai-standard-statements-2025.pdf"
CONTEXT = FinancialDocumentContext(
    company_id="moutai",
    company_name="贵州茅台酒股份有限公司",
    accounting_standard="CAS",
    accounting_standard_source="2025 annual report, accounting policy, PDF page 53",
    fiscal_year_start="2025-01-01",
    fiscal_year_end="2025-12-31",
    fiscal_calendar_source="2025 annual report, fiscal year policy, PDF page 72",
)


@pytest.fixture(scope="module")
def parsed_rows():
    return parse_pdf(FIXTURE, ocr_enabled=False, document_id="moutai-fixture-2025").financial_table_rows


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    _import_models()
    root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{(tmp_path / 'financial-facts.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    with Session(engine, expire_on_commit=False) as session:
        tenant = Tenant(name="Shadow tenant", slug=f"shadow-{tmp_path.name}")
        session.add(tenant)
        session.flush()
        yield session, tenant.id
    engine.dispose()


def _seed_document(session: Session, tenant_id: int, *, content: bytes | None = None) -> Document:
    payload = content if content is not None else FIXTURE.read_bytes()
    document = Document(
        tenant_id=tenant_id,
        filename="moutai-2025.pdf",
        company="贵州茅台",
        report_type="Annual Report",
        period="FY2025",
        status="indexed",
        content_sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
    )
    session.add(document)
    session.commit()
    return document


def _facts_for_document(rows, document_id: int):
    rebound = (replace(row, document_id=str(document_id)) for row in rows)
    return financial_facts_from_rows(rebound, context=CONTEXT)


def _ingestion_counters(rows, facts):
    verified = sum(row.verification_status == VerificationStatus.VERIFIED for row in rows)
    return {
        "rows_seen": verified,
        "rows_verified": verified,
        "rows_mapped": len(facts),
        "facts_rejected": verified - len(facts),
    }


def test_real_moutai_shadow_ingestion_is_idempotent_and_preserves_round_trip(db_session, parsed_rows):
    session, tenant_id = db_session
    document = _seed_document(session, tenant_id)
    facts = _facts_for_document(parsed_rows, document.id)
    repo = SQLFinancialFactRepository(session, tenant_id=tenant_id)

    counters = _ingestion_counters(parsed_rows, facts)
    first = repo.save_batch(facts, document_id=str(document.id), **counters)
    second = repo.save_batch(facts, document_id=str(document.id), **counters)

    assert len(facts) == 98
    assert first.facts_inserted == 98
    assert first.facts_unchanged == 0
    assert first.final_row_count == 98
    first_run = session.scalar(
        select(FinancialFactIngestionRun).where(FinancialFactIngestionRun.run_id == first.run_id)
    )
    assert (first_run.rows_seen, first_run.rows_verified, first_run.rows_mapped) == (595, 595, 98)
    assert first_run.facts_rejected == 497
    assert second.facts_inserted == 0
    assert second.facts_unchanged == 98
    assert second.final_row_count == 98
    assert repo.count_by_document(document_id=str(document.id)) == 98

    actual = repo.find_by_document(document_id=str(document.id))
    assert len(actual) == len(facts)
    original_by_id = {fact.fact_id: fact for fact in facts}
    actual_by_id = {fact.fact_id: fact for fact in actual}
    assert set(original_by_id) == set(actual_by_id)
    for fact_id, original in original_by_id.items():
        persisted = actual_by_id[fact_id]
        assert persisted == original
        assert persisted.value.as_tuple() == original.value.as_tuple()
        assert persisted.normalized_value.as_tuple() == original.normalized_value.as_tuple()

    # Display a readable sample as an assertion target and test the relational
    # index path with exact company/metric/year/scope constraints.
    total_assets = repo.find(
        company="贵州茅台",
        metric="total_assets",
        fiscal_year=2025,
        scope="CONSOLIDATED",
        document_id=str(document.id),
    )
    assert len(total_assets) == 1
    assert total_assets[0].value == Decimal("303834844021.44")
    assert (
        repo.find_unique(
            company="贵州茅台",
            metric="total_assets",
            fiscal_year=2025,
            scope="CONSOLIDATED",
            document_id=str(document.id),
        ).status
        == FactLookupStatus.FOUND
    )
    assert repo.find_unique(company="unknown issuer", metric="total_assets").status == FactLookupStatus.NOT_FOUND
    assert (
        repo.find_unique(
            company="贵州茅台", metric="total_assets", fiscal_year=2025, document_id=str(document.id)
        ).status
        == FactLookupStatus.AMBIGUOUS
    )
    required = {
        "cash_and_bank_balances",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "fixed_assets",
        "construction_in_progress",
        "revenue",
        "net_income",
        "attributable_net_income",
        "operating_cash_flow",
    }
    round_tripped_metrics = {fact.metric_id for fact in actual}
    assert required <= round_tripped_metrics
    assert all(len(fact.structured_identity or ()) == 9 for fact in actual)
    assert all(fact.page and fact.source_locator and fact.source_text for fact in actual)
    assert all(fact.mapping_status in {"EXACT", "SUPPORTED"} for fact in actual)
    assert isinstance(repo, FinancialFactRepositoryProtocol)
    assert isinstance(InMemoryFinancialFactRepository(), FinancialFactRepositoryProtocol)
    assets_observations = repo.find_by_metric(metric="total_assets")
    assert {fact.scope for fact in assets_observations} >= {"CONSOLIDATED", "PARENT_COMPANY"}
    assert {fact.period_end for fact in assets_observations if fact.fiscal_year == "2025"} == {"2025-12-31"}

    equation = accounting_equation_audit(actual)
    cash_flow = cash_flow_sanity_audit(actual)
    assert len(equation) == 4
    assert all(item["status"] == "PASS" for item in equation)
    assert len(cash_flow) == 4
    assert all(item["status"] == "PASS" for item in cash_flow)


def test_document_hash_versions_coexist_without_overwriting(db_session, parsed_rows):
    session, tenant_id = db_session
    original = _seed_document(session, tenant_id, content=b"version-a")
    revised = _seed_document(session, tenant_id, content=b"version-b")
    original_facts = _facts_for_document(parsed_rows, original.id)
    revised_facts = _facts_for_document(parsed_rows, revised.id)
    repo = SQLFinancialFactRepository(session, tenant_id=tenant_id)

    repo.save_batch(original_facts, document_id=str(original.id))
    repo.save_batch(revised_facts, document_id=str(revised.id))

    assert repo.count_by_document(document_id=str(original.id)) == 98
    assert repo.count_by_document(document_id=str(revised.id)) == 98
    assert repo.count_by_document(document_id=str(original.id), document_version=original.content_sha256) == 98
    assert repo.count_by_document(document_id=str(revised.id), document_version=revised.content_sha256) == 98
    with pytest.raises(AmbiguousFinancialFactError):
        repo.find_latest(company="贵州茅台", metric="total_assets", scope="CONSOLIDATED")


def test_conflicting_value_is_audited_and_never_overwritten(db_session, parsed_rows):
    session, tenant_id = db_session
    document = _seed_document(session, tenant_id)
    facts = _facts_for_document(parsed_rows, document.id)
    repo = SQLFinancialFactRepository(session, tenant_id=tenant_id)
    repo.save_batch(facts, document_id=str(document.id))
    original = next(fact for fact in facts if fact.metric_id == "total_assets")
    conflicting = replace(
        original, value=original.value + Decimal("1"), normalized_value=original.normalized_value + Decimal("1")
    )

    with pytest.raises(FactConflictError):
        repo.save_batch((conflicting,), document_id=str(document.id))

    persisted = repo.find_by_document(document_id=str(document.id))
    assert len(persisted) == 98
    assert next(fact for fact in persisted if fact.fact_id == original.fact_id).value == original.value
    conflicts = repo.find_conflicts(document_id=str(document.id))
    assert len(conflicts) == 1
    assert conflicts[0].existing_value == original.normalized_value
    assert conflicts[0].incoming_value == conflicting.normalized_value
    assert conflicts[0].incoming_provenance["page"] == original.page
    conflict_lookup = repo.find_unique(
        company="贵州茅台",
        metric="total_assets",
        fiscal_year=2025,
        scope="CONSOLIDATED",
        document_id=str(document.id),
    )
    assert conflict_lookup.status == FactLookupStatus.CONFLICT


def test_mid_batch_failure_rolls_back_all_facts_and_keeps_failed_run(db_session, parsed_rows):
    session, tenant_id = db_session
    document = _seed_document(session, tenant_id)
    facts = _facts_for_document(parsed_rows, document.id)
    repo = SQLFinancialFactRepository(session, tenant_id=tenant_id)

    with pytest.raises(RuntimeError, match="injected mid-ingestion"):
        repo.save_batch(facts, document_id=str(document.id), fail_after_insert=47)

    assert repo.count_by_document(document_id=str(document.id)) == 0
    failed_runs = session.scalars(
        select(FinancialFactIngestionRun).where(
            FinancialFactIngestionRun.document_id == document.id,
            FinancialFactIngestionRun.tenant_id == tenant_id,
        )
    ).all()
    assert len(failed_runs) == 1
    assert failed_runs[0].status == "FAILED"
    assert failed_runs[0].facts_inserted == 0
    assert "injected mid-ingestion failure" in failed_runs[0].error_summary


def test_repository_is_tenant_scoped_and_refuses_foreign_document(db_session, parsed_rows):
    session, tenant_id = db_session
    other_tenant = Tenant(name="Other tenant", slug=f"other-{tenant_id}")
    session.add(other_tenant)
    session.commit()
    foreign_document = _seed_document(session, other_tenant.id)
    facts = _facts_for_document(parsed_rows, foreign_document.id)
    repo = SQLFinancialFactRepository(session, tenant_id=tenant_id)
    with pytest.raises(LookupError, match="this tenant"):
        repo.save_batch(facts, document_id=str(foreign_document.id))
    assert repo.count_by_document(document_id=str(foreign_document.id)) == 0


def test_migration_creates_fact_tables_and_round_trips_downgrade(tmp_path: Path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "financial-fact-migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert {
            "financial_facts",
            "financial_fact_ingestion_runs",
            "financial_fact_conflicts",
        } <= set(inspect(engine).get_table_names())
        numeric = {column["name"]: column["type"] for column in inspect(engine).get_columns("financial_facts")}
        assert str(numeric["value"]) == "VARCHAR(80)"
        assert str(numeric["normalized_value"]) == "VARCHAR(80)"
    finally:
        engine.dispose()
    command.downgrade(config, "20260729_08")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO tenants (name, slug) VALUES ('legacy tenant', 'legacy-p1-6')"))
            tenant_id = connection.execute(text("SELECT id FROM tenants WHERE slug='legacy-p1-6'")).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO documents (filename, company, report_type, period, status, tenant_id) "
                    "VALUES ('legacy.pdf', 'Moutai', 'Annual Report', 'FY2025', 'indexed', :tenant_id)"
                ),
                {"tenant_id": tenant_id},
            )
    finally:
        engine.dispose()
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM documents")).scalar_one() == 1
    finally:
        engine.dispose()
    graph = ScriptDirectory.from_config(config)
    # FinancialFact remains an immutable ancestor, not permanently the latest head.
    assert graph.get_revision("20260928_09").down_revision == "20260729_08"
    assert graph.get_heads() == ["20261002_10"]


def test_financial_decimal_type_preserves_exact_values_and_uses_postgres_numeric():
    from sqlalchemy.dialects import postgresql, sqlite

    decimal_type = ExactFinancialDecimal()
    sqlite_impl = decimal_type.load_dialect_impl(sqlite.dialect())
    postgres_impl = decimal_type.load_dialect_impl(postgresql.dialect())
    assert str(sqlite_impl) == "VARCHAR(80)"
    assert str(postgres_impl) == "NUMERIC(38, 12)"
    original = Decimal("99999999999999999999999999.123456789012")
    stored = decimal_type.process_bind_param(original, sqlite.dialect())
    assert decimal_type.process_result_value(stored, sqlite.dialect()) == original
    with pytest.raises(ValueError, match="scale of 12"):
        decimal_type.process_bind_param(Decimal("1.0000000000001"), sqlite.dialect())
