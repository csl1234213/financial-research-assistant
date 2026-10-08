import pytest
from sqlalchemy.orm import Session, sessionmaker

from models.tenant import Tenant
from models.user import User
from storage.database import Base
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_tenant.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_default_tenant(db: Session) -> Tenant:
    existing = db.query(Tenant).filter(Tenant.slug == "default").first()
    if existing is None:
        tenant = Tenant(name="Default Workspace", slug="default")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant
    return existing


class TestTenantModel:
    def test_create_tenant_successfully(self, db_session):
        tenant = Tenant(name="Test Corp", slug="test-corp")
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)

        assert tenant.id is not None
        assert tenant.name == "Test Corp"
        assert tenant.slug == "test-corp"
        assert tenant.created_at is not None

    def test_create_user_with_tenant(self, db_session):
        tenant = _ensure_default_tenant(db_session)

        user = User(
            email="tenant-user@example.com",
            password_hash="hashed_password",
            role="user",
            tenant_id=tenant.id,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        assert user.id is not None
        assert user.email == "tenant-user@example.com"
        assert user.tenant_id == tenant.id

    def test_user_tenant_relationship_works(self, db_session):
        tenant = _ensure_default_tenant(db_session)

        user = User(
            email="rel-user@example.com",
            password_hash="hashed_password",
            role="user",
            tenant_id=tenant.id,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        assert user.tenant is not None
        assert user.tenant.id == tenant.id
        assert user.tenant.name == "Default Workspace"

        db_session.refresh(tenant)
        assert len(tenant.users) == 1
        assert tenant.users[0].email == "rel-user@example.com"

    def test_default_tenant_initialization_is_idempotent(self, db_session):
        first = _ensure_default_tenant(db_session)
        assert first.slug == "default"

        second = _ensure_default_tenant(db_session)
        assert second.id == first.id

        third = _ensure_default_tenant(db_session)
        assert third.id == first.id

        count = db_session.query(Tenant).filter(Tenant.slug == "default").count()
        assert count == 1
