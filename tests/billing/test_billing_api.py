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
from billing.models import BillingRecord
from models.plan import Plan
from models.subscription import TenantSubscription
from models.tenant import Tenant
from models.user import User
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_billing_api.db")
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

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_billing_api.db"):
        try:
            os.remove("test_billing_api.db")
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
    t = Tenant(name="Billing API Test", slug="billing-api-test")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def user(db_session, tenant):
    u = User(
        email="billing@test.com",
        password_hash="hashed",
        tenant_id=tenant.id,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def plan(db_session):
    plan = Plan(
        name="Free",
        slug="free",
        max_documents=10,
        max_chats_per_day=50,
        max_embeddings=1000,
        price=0.0,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


@pytest.fixture
def auth_headers(tenant, user):
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


class TestBillingUsageAPI:
    def test_get_usage_returns_structure(self, client, tenant, user, plan, db_session, auth_headers):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        record = BillingRecord(
            tenant_id=tenant.id,
            user_id=user.id,
            resource_type="chat",
            quantity=1,
            unit_price=0.005,
            amount=0.005,
            currency="USD",
        )
        db_session.add(record)
        db_session.commit()

        response = client.get("/api/v1/billing/usage", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "period" in data
        assert "total_requests" in data
        assert "total_tokens" in data
        assert "total_cost" in data
        assert "top_tools" in data

    def test_get_usage_with_specific_period(self, client, tenant, user, plan, db_session, auth_headers):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        response = client.get(
            "/api/v1/billing/usage?period=2026-01", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["period"] == "2026-01"


class TestBillingPlanAPI:
    def test_get_plan_returns_plan_info(self, client, tenant, user, plan, db_session, auth_headers):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        response = client.get("/api/v1/billing/plan", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "plan" in data
        assert "limits" in data
        assert data["plan"] == "free"

    def test_list_plans_returns_all_plans(self, client, auth_headers):
        response = client.get("/api/v1/billing/plans", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "plans" in data
        assert len(data["plans"]) == 3
        slugs = [p["slug"] for p in data["plans"]]
        assert "free" in slugs
        assert "pro" in slugs
        assert "enterprise" in slugs


class TestBillingIntegration:
    def test_free_plan_quota_exceeded(self, client, tenant, user, plan, db_session, auth_headers):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        from billing.plans import get_plan_limits
        from models.usage import UsageRecord

        limits = get_plan_limits("free")
        for _ in range(limits.agent_chats_per_month):
            record = UsageRecord(
                tenant_id=tenant.id,
                event_type="chat_request",
                resource_type="chat",
                quantity=1,
            )
            db_session.add(record)
        db_session.commit()

        from billing.service import check_quota

        allowed, msg = check_quota(db_session, tenant.id, "agent_chat")
        assert allowed is False
        assert "exceeded" in msg.lower()
