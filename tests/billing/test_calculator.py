import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from sqlalchemy.orm import sessionmaker

from billing.calculator import calculate_cost
from billing.models import BillingRecord
from billing.plans import (
    get_plan_limits,
    get_plan_price,
    is_enterprise,
)
from storage.database import Base
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_billing.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def _setup_db():
    import billing.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestCalculator:
    def test_basic_cost_calculation(self):
        result = calculate_cost(
            token_usage={"input_tokens": 1000, "output_tokens": 500},
            tool_calls=2,
        )
        assert result["input_tokens"] == 1000
        assert result["output_tokens"] == 500
        assert result["total_tokens"] == 1500
        assert result["input_cost"] == 0.0015
        assert result["output_cost"] == 0.003
        assert result["tool_cost"] == 0.002
        assert result["total_cost"] == 0.0065
        assert result["currency"] == "USD"

    def test_zero_usage(self):
        result = calculate_cost()
        assert result["total_cost"] == 0.0
        assert result["total_tokens"] == 0

    def test_large_token_usage(self):
        result = calculate_cost(
            token_usage={"input_tokens": 100000, "output_tokens": 50000},
            tool_calls=10,
        )
        assert result["input_cost"] == 0.15
        assert result["output_cost"] == 0.3
        assert result["tool_cost"] == 0.01
        assert result["total_cost"] == 0.46

    def test_token_usage_with_total(self):
        result = calculate_cost(
            token_usage={"input_tokens": 500, "output_tokens": 300, "total_tokens": 800},
        )
        assert result["total_tokens"] == 800

    def test_token_usage_without_total(self):
        result = calculate_cost(
            token_usage={"input_tokens": 500, "output_tokens": 300},
        )
        assert result["total_tokens"] == 800


class TestPlans:
    def test_free_plan_limits(self):
        limits = get_plan_limits("free")
        assert limits.agent_chats_per_month == 50
        assert limits.max_tokens_per_request == 4096
        assert limits.max_documents == 10
        assert limits.priority_support is False
        assert limits.custom_tools is False

    def test_pro_plan_limits(self):
        limits = get_plan_limits("pro")
        assert limits.agent_chats_per_month == 2000
        assert limits.max_tokens_per_request == 16384
        assert limits.max_documents == 100
        assert limits.priority_support is True

    def test_enterprise_plan_limits(self):
        limits = get_plan_limits("enterprise")
        assert limits.agent_chats_per_month == -1
        assert limits.max_tokens_per_request == 32768
        assert limits.custom_tools is True

    def test_enterprise_detection(self):
        assert is_enterprise("enterprise") is True
        assert is_enterprise("pro") is False
        assert is_enterprise("free") is False

    def test_plan_price(self):
        assert get_plan_price("free") == 0.0
        assert get_plan_price("pro") == 29.99
        assert get_plan_price("enterprise") == 99.99

    def test_unknown_plan_falls_back_to_free(self):
        limits = get_plan_limits("nonexistent")
        assert limits.agent_chats_per_month == 50
        assert get_plan_price("nonexistent") == 0.0


class TestBillingRecord:
    def test_create_billing_record(self, db_session):
        record = BillingRecord(
            tenant_id=1,
            user_id=1,
            resource_type="chat",
            quantity=1,
            unit_price=0.005,
            amount=0.005,
            currency="USD",
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        assert record.id is not None
        assert record.tenant_id == 1
        assert record.amount == 0.005
        assert record.currency == "USD"
        assert record.created_at is not None

    def test_billing_record_defaults(self, db_session):
        record = BillingRecord(
            tenant_id=2,
            resource_type="chat",
            quantity=1,
            unit_price=0.0,
            amount=0.0,
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        assert record.currency == "USD"
        assert record.quantity == 1
