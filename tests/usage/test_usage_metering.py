import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from api.app import app
from core.usage_events import ResourceType, UsageEvent
from models.tenant import Tenant
from models.usage import UsageRecord
from models.user import User
from services.usage_service import (
    get_usage_summary,
    record_batch_usage,
    record_usage,
)
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_usage_metering.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

VALID_ONE_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
    b"startxref\n190\n"
    b"%%EOF"
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists(TEST_DATABASE_URL.replace("sqlite:///", "")):
        try:
            os.remove(TEST_DATABASE_URL.replace("sqlite:///", ""))
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
    t = Tenant(name="Usage Test Co", slug="usage-test")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def tenant_b(db_session):
    t = Tenant(name="Other Tenant", slug="other-tenant")
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def user(db_session, tenant):
    u = User(
        email="usage@test.com",
        password_hash="hashed",
        tenant_id=tenant.id,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


class TestUsageModel:

    def test_create_usage_record(self, db_session, tenant, user):
        record = UsageRecord(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=1,
        )
        record.meta = {"filename": "test.pdf", "document_id": 1}
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        assert record.id is not None
        assert record.tenant_id == tenant.id
        assert record.user_id == user.id
        assert record.event_type == UsageEvent.DOCUMENT_UPLOAD
        assert record.resource_type == ResourceType.DOCUMENT
        assert record.quantity == 1
        assert record.meta == {"filename": "test.pdf", "document_id": 1}
        assert record.created_at is not None

    def test_tenant_relationship(self, db_session, tenant, user):
        record = UsageRecord(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.CHAT_REQUEST,
            resource_type=ResourceType.CHAT,
            quantity=1,
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        assert record.tenant is not None
        assert record.tenant.id == tenant.id

    def test_user_relationship(self, db_session, tenant, user):
        record = UsageRecord(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.CHAT_REQUEST,
            resource_type=ResourceType.CHAT,
            quantity=1,
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        assert record.user is not None
        assert record.user.id == user.id

    def test_metadata_default(self, db_session, tenant):
        record = UsageRecord(
            tenant_id=tenant.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=1,
        )
        db_session.add(record)
        db_session.commit()

        assert record.meta == {}

    def test_metadata_serialization(self, db_session, tenant):
        record = UsageRecord(
            tenant_id=tenant.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=1,
        )
        complex_meta = {"tags": ["urgent", "finance"], "size": 1024}
        record.meta = complex_meta
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        assert record.meta == complex_meta
        assert isinstance(record._meta, str)
        assert json.loads(record._meta) == complex_meta


class TestUsageService:

    def test_record_usage(self, db_session, tenant, user):
        record = record_usage(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=1,
            metadata={"filename": "test.pdf"},
            db=db_session,
        )

        assert record is not None
        assert record.id is not None
        assert record.tenant_id == tenant.id
        assert record.event_type == UsageEvent.DOCUMENT_UPLOAD

    def test_tenant_id_required(self):
        with pytest.raises(ValueError, match="tenant_id is required"):
            record_usage(
                tenant_id=None,
                event_type=UsageEvent.DOCUMENT_UPLOAD,
                resource_type=ResourceType.DOCUMENT,
                quantity=1,
            )

    def test_batch_insert(self, db_session, tenant, user):
        events = [
            {
                "tenant_id": tenant.id,
                "user_id": user.id,
                "event_type": UsageEvent.DOCUMENT_UPLOAD,
                "resource_type": ResourceType.DOCUMENT,
                "quantity": 1,
                "metadata": {"file": "a.pdf"},
            },
            {
                "tenant_id": tenant.id,
                "user_id": user.id,
                "event_type": UsageEvent.DOCUMENT_UPLOAD,
                "resource_type": ResourceType.DOCUMENT,
                "quantity": 1,
                "metadata": {"file": "b.pdf"},
            },
            {
                "tenant_id": tenant.id,
                "user_id": user.id,
                "event_type": UsageEvent.CHAT_REQUEST,
                "resource_type": ResourceType.CHAT,
                "quantity": 1,
                "metadata": {"endpoint": "/chat"},
            },
        ]

        count = record_batch_usage(events, db=db_session)
        assert count == 3

        total = db_session.query(func.count(UsageRecord.id)).filter(
            UsageRecord.tenant_id == tenant.id
        ).scalar()
        assert total == 3

    def test_batch_skips_missing_tenant_id(self, db_session, tenant):
        events = [
            {
                "tenant_id": tenant.id,
                "event_type": UsageEvent.DOCUMENT_UPLOAD,
                "resource_type": ResourceType.DOCUMENT,
                "quantity": 1,
            },
            {
                "tenant_id": None,
                "event_type": UsageEvent.CHAT_REQUEST,
                "resource_type": ResourceType.CHAT,
                "quantity": 1,
            },
        ]

        count = record_batch_usage(events, db=db_session)
        assert count == 1

    def test_get_usage_summary(self, db_session, tenant, user):
        record_usage(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=2,
            db=db_session,
        )
        record_usage(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.CHAT_REQUEST,
            resource_type=ResourceType.CHAT,
            quantity=3,
            db=db_session,
        )

        summary = get_usage_summary(tenant_id=tenant.id, db=db_session)
        assert summary["tenant_id"] == tenant.id
        events = {e["event_type"]: e for e in summary["events"]}

        assert UsageEvent.DOCUMENT_UPLOAD in events
        assert events[UsageEvent.DOCUMENT_UPLOAD]["count"] == 1
        assert events[UsageEvent.DOCUMENT_UPLOAD]["total_quantity"] == 2

        assert UsageEvent.CHAT_REQUEST in events
        assert events[UsageEvent.CHAT_REQUEST]["count"] == 1
        assert events[UsageEvent.CHAT_REQUEST]["total_quantity"] == 3


class TestTenantIsolation:

    def test_tenant_a_cannot_see_tenant_b_usage(self, db_session, tenant, tenant_b, user):
        record_usage(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=5,
            db=db_session,
        )

        record_usage(
            tenant_id=tenant_b.id,
            event_type=UsageEvent.CHAT_REQUEST,
            resource_type=ResourceType.CHAT,
            quantity=10,
            db=db_session,
        )

        summary_a = get_usage_summary(tenant_id=tenant.id, db=db_session)
        events_a = {e["event_type"]: e for e in summary_a["events"]}
        assert UsageEvent.DOCUMENT_UPLOAD in events_a
        assert UsageEvent.CHAT_REQUEST not in events_a

        summary_b = get_usage_summary(tenant_id=tenant_b.id, db=db_session)
        events_b = {e["event_type"]: e for e in summary_b["events"]}
        assert UsageEvent.CHAT_REQUEST in events_b
        assert UsageEvent.DOCUMENT_UPLOAD not in events_b

    def test_usage_records_filtered_by_tenant(self, db_session, tenant, tenant_b, user):
        record_usage(
            tenant_id=tenant.id,
            user_id=user.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=2,
            db=db_session,
        )
        record_usage(
            tenant_id=tenant_b.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=3,
            db=db_session,
        )

        count_a = db_session.query(func.count(UsageRecord.id)).filter(
            UsageRecord.tenant_id == tenant.id
        ).scalar()
        assert count_a == 1

        count_b = db_session.query(func.count(UsageRecord.id)).filter(
            UsageRecord.tenant_id == tenant_b.id
        ).scalar()
        assert count_b == 1

        total = db_session.query(func.count(UsageRecord.id)).scalar()
        assert total == 2


class TestUsageAPI:

    @pytest.fixture
    def auth_headers(self, tenant, user):
        from auth.jwt import create_access_token
        token = create_access_token(data={"sub": str(user.id)})
        return {"Authorization": f"Bearer {token}"}

    def test_authenticated_usage_endpoint(self, client, tenant, db_session, auth_headers):
        record_usage(
            tenant_id=tenant.id,
            event_type=UsageEvent.DOCUMENT_UPLOAD,
            resource_type=ResourceType.DOCUMENT,
            quantity=1,
            db=db_session,
        )

        response = client.get("/api/v1/usage/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == tenant.id
        assert len(data["events"]) >= 1

    def test_unauthenticated_returns_401(self, client):
        response = client.get("/api/v1/usage/me")
        assert response.status_code == 401


class TestUsageIntegration:

    @pytest.fixture
    def auth_headers(self, tenant, user):
        from auth.jwt import create_access_token
        token = create_access_token(data={"sub": str(user.id)})
        return {"Authorization": f"Bearer {token}"}

    def test_upload_creates_usage(self, client, tenant, db_session, auth_headers):
        import io
        pdf_file = io.BytesIO(VALID_ONE_PAGE_PDF)

        response = client.post(
            "/api/v1/upload",
            files={"file": ("test_usage.pdf", pdf_file, "application/pdf")},
            headers=auth_headers,
        )
        assert response.status_code == 200

        records = db_session.query(UsageRecord).filter(
            UsageRecord.tenant_id == tenant.id,
            UsageRecord.event_type == UsageEvent.DOCUMENT_UPLOAD,
        ).all()
        assert len(records) >= 1
        assert records[0].resource_type == ResourceType.DOCUMENT
        meta = records[0].meta
        assert meta.get("filename") == "test_usage.pdf"

    def test_chat_creates_usage(self, client, tenant, db_session, auth_headers):
        from unittest.mock import patch

        from api.services.chat_service import ChatService

        mock_response = {
            "report": "Mock response",
            "citations": [],
            "reasoning": {
                "intent": "DIRECT_CHAT",
                "companies": [],
                "research_mode": "default",
                "evidence_count": 0,
            },
            "plan": {},
            "execution_time": 0.1,
        }
        with patch.object(ChatService, "chat", return_value=mock_response):
            response = client.post(
                "/api/v1/chat",
                json={"question": "Hello", "company": "TestCorp"},
                headers=auth_headers,
            )
        assert response.status_code == 200

        records = db_session.query(UsageRecord).filter(
            UsageRecord.tenant_id == tenant.id,
            UsageRecord.event_type == UsageEvent.CHAT_REQUEST,
        ).all()
        assert len(records) >= 1
        assert records[0].resource_type == ResourceType.CHAT
        meta = records[0].meta
        assert meta.get("endpoint") == "/api/v1/chat"
