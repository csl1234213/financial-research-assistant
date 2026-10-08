import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import app
from auth.jwt import create_access_token
from models.tenant import Tenant
from models.user import User
from observability.tracer import finish_trace, start_trace
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database(
    "test_monitoring_api.db"
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup_db():
    import billing.models  # noqa: F401
    import models.plan  # noqa: F401
    import models.subscription  # noqa: F401
    import models.tenant  # noqa: F401
    import models.usage  # noqa: F401
    import models.user  # noqa: F401
    import observability.models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_monitoring_api.db"):
        try:
            os.remove("test_monitoring_api.db")
        except (PermissionError, OSError):
            pass


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def tenant(db_session):
    t = Tenant(name="Monitoring Test", slug="monitoring-test")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def user(db_session, tenant):
    u = User(
        email="monitor@test.com",
        password_hash="hashed",
        tenant_id=tenant.id,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def auth_headers(tenant, user):
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


class TestMonitoringOverviewAPI:
    def test_overview_returns_structure(self, client, tenant, user, auth_headers):
        response = client.get("/api/v1/monitoring/overview", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_requests" in data
        assert "success_rate" in data
        assert "avg_latency_ms" in data
        assert "total_cost" in data
        assert "daily" in data

    def test_overview_with_period(self, client, tenant, user, auth_headers):
        response = client.get(
            "/api/v1/monitoring/overview?period=2026-07", headers=auth_headers
        )
        assert response.status_code == 200


class TestMonitoringMetricsAPI:
    def test_metrics_returns_data(self, client, tenant, user, auth_headers):
        response = client.get("/api/v1/monitoring/metrics", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_requests" in data
        assert "success_rate" in data
        assert "avg_latency_ms" in data


class TestMonitoringTracesAPI:
    def test_traces_returns_list(self, client, tenant, user, auth_headers, db_session):
        trace = start_trace(thread_id="test", tenant_id=tenant.id)
        finish_trace(trace, status="success", db=db_session)

        response = client.get("/api/v1/monitoring/traces", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "traces" in data
        assert len(data["traces"]) >= 1

    def test_traces_with_limit(self, client, tenant, user, auth_headers, db_session):
        for i in range(5):
            trace = start_trace(thread_id=f"t{i}", tenant_id=tenant.id)
            finish_trace(trace, status="success", db=db_session)

        response = client.get(
            "/api/v1/monitoring/traces?limit=3", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["traces"]) == 3

    def test_trace_detail(self, client, tenant, user, auth_headers, db_session):
        trace = start_trace(thread_id="detail-test", tenant_id=tenant.id)
        saved = finish_trace(trace, status="success", db=db_session)

        response = client.get(
            f"/api/v1/monitoring/traces/{saved.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["request_id"] == saved.request_id
        assert "spans" in data

    def test_trace_detail_not_found(self, client, tenant, user, auth_headers):
        response = client.get(
            "/api/v1/monitoring/traces/99999", headers=auth_headers
        )
        assert response.status_code == 404

    def test_trace_detail_tenant_isolation(self, client, tenant, user, auth_headers, db_session):
        other_tenant = Tenant(name="Other", slug="other")
        db_session.add(other_tenant)
        db_session.commit()

        trace = start_trace(thread_id="other", tenant_id=other_tenant.id)
        saved = finish_trace(trace, status="success", db=db_session)

        response = client.get(
            f"/api/v1/monitoring/traces/{saved.id}", headers=auth_headers
        )
        assert response.status_code == 404
