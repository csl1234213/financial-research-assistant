import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from api.app import app
from models.tenant import Tenant
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_auth.db")
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
LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"


class TestAuthRegister:
    def test_register_success(self, client):
        response = client.post(REGISTER_URL, json={"email": "test@example.com", "password": "secure123"})
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "test@example.com"
        assert "token" in data
        assert "id" in data

    def test_register_duplicate_email(self, client):
        client.post(REGISTER_URL, json={"email": "dup@example.com", "password": "secure123"})
        response = client.post(REGISTER_URL, json={"email": "dup@example.com", "password": "secure123"})
        assert response.status_code == 409

    def test_register_short_password(self, client):
        response = client.post(REGISTER_URL, json={"email": "short@example.com", "password": "12345"})
        assert response.status_code == 422

    def test_register_invalid_email(self, client):
        response = client.post(REGISTER_URL, json={"email": "not-an-email", "password": "secure123"})
        assert response.status_code == 422


class TestAuthLogin:
    def test_login_success(self, client):
        client.post(REGISTER_URL, json={"email": "login@example.com", "password": "secure123"})
        response = client.post(LOGIN_URL, json={"email": "login@example.com", "password": "secure123"})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        client.post(REGISTER_URL, json={"email": "wrong@example.com", "password": "secure123"})
        response = client.post(LOGIN_URL, json={"email": "wrong@example.com", "password": "wrongpass"})
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        response = client.post(LOGIN_URL, json={"email": "nobody@example.com", "password": "secure123"})
        assert response.status_code == 401


class TestAuthMe:
    def test_me_success(self, client):
        register_resp = client.post(REGISTER_URL, json={"email": "me@example.com", "password": "secure123"})
        token = register_resp.json()["token"]
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "me@example.com"
        assert data["role"] == "user"

    def test_me_contains_tenant(self, client):
        register_resp = client.post(REGISTER_URL, json={"email": "me-tenant@example.com", "password": "secure123"})
        token = register_resp.json()["token"]
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["tenant"] is not None
        assert data["tenant"]["slug"] == "default"
        assert data["tenant"]["name"] == "Default Workspace"

    def test_me_no_token(self, client):
        response = client.get(ME_URL)
        assert response.status_code == 401

    def test_me_invalid_token(self, client):
        response = client.get(ME_URL, headers={"Authorization": "Bearer invalid.token.here"})
        assert response.status_code == 401

    def test_me_expired_token(self, client):
        expired_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOjEsImV4cCI6MTcwMDAwMDAwMH0."
            "abc123"
        )
        response = client.get(ME_URL, headers={"Authorization": f"Bearer {expired_token}"})
        assert response.status_code == 401


class TestAuthUnauthorized:
    def test_no_auth_header(self, client):
        response = client.get(ME_URL)
        assert response.status_code == 401

    def test_malformed_token(self, client):
        response = client.get(ME_URL, headers={"Authorization": "NotBearer token"})
        assert response.status_code == 401

    def test_empty_token(self, client):
        response = client.get(ME_URL, headers={"Authorization": "Bearer "})
        assert response.status_code == 401
