import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import os

import pytest
from sqlalchemy.orm import sessionmaker

from billing.plans import get_plan_limits
from billing.service import check_quota
from models.document import Document
from models.plan import Plan
from models.subscription import TenantSubscription
from models.tenant import Tenant
from models.usage import UsageRecord
from storage.database import Base
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_quota.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def _setup_db():
    import billing.models  # noqa: F401
    import models.plan  # noqa: F401
    import models.subscription  # noqa: F401
    import models.tenant  # noqa: F401
    import models.usage  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("test_quota.db"):
        try:
            os.remove("test_quota.db")
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
def tenant(db_session):
    t = Tenant(name="Quota Test Co", slug="quota-test")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def free_plan(db_session):
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
def pro_plan(db_session):
    plan = Plan(
        name="Pro",
        slug="pro",
        max_documents=100,
        max_chats_per_day=500,
        max_embeddings=10000,
        price=29.99,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


@pytest.fixture
def enterprise_plan(db_session):
    plan = Plan(
        name="Enterprise",
        slug="enterprise",
        max_documents=1000,
        max_chats_per_day=5000,
        max_embeddings=100000,
        price=99.99,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


class TestQuotaFree:
    def test_free_plan_allows_within_limit(self, db_session, tenant, free_plan):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=free_plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        allowed, msg = check_quota(db_session, tenant.id, "agent_chat")
        assert allowed is True

    def test_free_plan_blocks_when_exceeded(self, db_session, tenant, free_plan):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=free_plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

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

        allowed, msg = check_quota(db_session, tenant.id, "agent_chat")
        assert allowed is False
        assert "exceeded" in msg.lower()

    def test_free_plan_document_quota(self, db_session, tenant, free_plan):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=free_plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        limits = get_plan_limits("free")
        for _ in range(limits.max_documents):
            db_session.add(Document(tenant_id=tenant.id, filename=f"{_}.pdf"))
            record = UsageRecord(
                tenant_id=tenant.id,
                event_type="document_upload",
                resource_type="document",
                quantity=1,
            )
            db_session.add(record)
        db_session.commit()

        allowed, msg = check_quota(db_session, tenant.id, "document")
        assert allowed is False

        from services.plan_service import can_upload, get_document_quota

        assert can_upload(db_session, tenant.id) is False
        document = db_session.query(Document).filter_by(tenant_id=tenant.id).first()
        db_session.delete(document)
        db_session.commit()
        assert can_upload(db_session, tenant.id) is True
        assert check_quota(db_session, tenant.id, "document")[0] is True
        assert get_document_quota(db_session, tenant.id) == {
            "used": 9, "limit": 10, "remaining": 1, "bypassed": False,
        }
        assert db_session.query(UsageRecord).filter_by(
            tenant_id=tenant.id, event_type="document_upload",
        ).count() == 10


class TestQuotaPro:
    def test_evaluation_bypass_allows_document_quota_for_listed_tenant(
        self, db_session, tenant, free_plan, monkeypatch,
    ):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=free_plan.id,
            status="active",
        )
        db_session.add(sub)
        for index in range(free_plan.max_documents):
            db_session.add(Document(tenant_id=tenant.id, filename=f"evaluation-{index}.pdf"))
        db_session.commit()

        monkeypatch.setenv("EVALUATION_BYPASS_PLAN_LIMITS", "true")
        monkeypatch.setenv("EVALUATION_BYPASS_TENANT_IDS", str(tenant.id))

        from services.plan_service import can_upload

        assert can_upload(db_session, tenant.id) is True
        assert check_quota(db_session, tenant.id, "document")[0] is True

    def test_pro_plan_allows_more(self, db_session, tenant, pro_plan):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=pro_plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        allowed, msg = check_quota(db_session, tenant.id, "agent_chat")
        assert allowed is True


class TestQuotaEnterprise:
    def test_enterprise_unlimited(self, db_session, tenant, enterprise_plan):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=enterprise_plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        limits = get_plan_limits("free")
        for _ in range(limits.agent_chats_per_month * 10):
            record = UsageRecord(
                tenant_id=tenant.id,
                event_type="chat_request",
                resource_type="chat",
                quantity=1,
            )
            db_session.add(record)
        db_session.commit()

        allowed, msg = check_quota(db_session, tenant.id, "agent_chat")
        assert allowed is True


class TestQuotaTenantIsolation:
    def test_quota_is_per_tenant(self, db_session, tenant, free_plan):
        sub = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=free_plan.id,
            status="active",
        )
        db_session.add(sub)
        db_session.commit()

        other = Tenant(name="Other Co", slug="other-co")
        db_session.add(other)
        db_session.commit()

        sub2 = TenantSubscription(
            tenant_id=other.id,
            plan_id=free_plan.id,
            status="active",
        )
        db_session.add(sub2)
        db_session.commit()

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

        allowed1, _ = check_quota(db_session, tenant.id, "agent_chat")
        allowed2, _ = check_quota(db_session, other.id, "agent_chat")

        assert allowed1 is False
        assert allowed2 is True
