import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from api.app import app
from models.tenant import Tenant
from models.user import User
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_tenant_api.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        existing = db.query(Tenant).filter(Tenant.slug == "default").first()
        if existing is None:
            db.add(Tenant(name="Default Workspace", slug="default"))
            db.commit()
    finally:
        db.close()

    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


REGISTER_URL = "/api/v1/auth/register"
TENANT_ME_URL = "/api/v1/tenant/me"
AUTH_ME_URL = "/api/v1/auth/me"


def _register_and_get_token(client: TestClient, email: str = "test@example.com") -> str:
    resp = client.post(REGISTER_URL, json={"email": email, "password": "secure123"})
    assert resp.status_code == 201
    return resp.json()["token"]


class TestTenantMe:
    def test_no_token_returns_401(self, client):
        response = client.get(TENANT_ME_URL)
        assert response.status_code == 401

    def test_valid_token_returns_tenant(self, client):
        token = _register_and_get_token(client)
        response = client.get(TENANT_ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "default"
        assert data["name"] == "Default Workspace"
        assert "id" in data
        assert "created_at" in data

    def test_auth_me_contains_tenant(self, client):
        token = _register_and_get_token(client, "auth-me-tenant@example.com")
        response = client.get(AUTH_ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["tenant"] is not None
        assert data["tenant"]["slug"] == "default"

    def test_missing_tenant_returns_403(self, db_session):
        tenant = Tenant(name="Orphan", slug="orphan")
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)

        user = User(
            email="orphan@example.com",
            password_hash="hashed",
            role="user",
            tenant_id=tenant.id,
        )
        db_session.add(user)
        db_session.commit()

        db_session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        db_session.commit()

        from auth.jwt import create_access_token

        token = create_access_token(data={"sub": str(user.id)})

        from fastapi.testclient import TestClient as TC

        app.dependency_overrides[get_db] = override_get_db
        with TC(app) as c:
            response = c.get(TENANT_ME_URL, headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 403
        app.dependency_overrides.clear()
