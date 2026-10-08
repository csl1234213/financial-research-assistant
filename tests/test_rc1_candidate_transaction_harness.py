"""Real request/worker commit visibility in the existing disposable PG fixture."""

from fastapi.testclient import TestClient

from api.main import app
from auth.password import hash_password
from models.user import User
from services.llm_settings_service import get_runtime_llm_settings, upsert_provider_setting
from storage.database import get_db
from tests.formal_ingestion_test_harness import formal  # noqa: F401


def test_request_worker_cross_session_visibility(formal, record_property):  # noqa: F811
    _, _, factory = formal
    with factory() as db, db.begin():
        user = db.get(User, 2)
        user.email = "harness@example.com"
        user.password_hash = hash_password("Harness-Isolated-Password")

    request_sessions = []

    def request_db():
        with factory() as db:
            request_sessions.append(db)
            yield db

    app.dependency_overrides[get_db] = request_db
    try:
        client = TestClient(app)
        login = client.post("/api/v1/auth/login", json={"email": "harness@example.com",
            "password": "Harness-Isolated-Password"})
        assert login.status_code == 200
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        # Request A invokes the production route/service, including real commit.
        written = client.put("/api/v1/settings/llm/deepseek", json={
            "model": "deepseek-v4-flash", "api_key": "isolated-harness-no-network"})
        assert written.status_code == 200, written.text
        assert written.json()["model"] == "deepseek-v4-flash"
        # Request B is independent and must see A's committed write.
        read = client.get("/api/v1/settings/llm")
        assert read.status_code == 200
        assert next(row for row in read.json()["providers"] if row["provider"] == "deepseek")[
            "model"] == "deepseek-v4-flash"
        assert len(request_sessions) >= 3
        assert len({id(session) for session in request_sessions}) == len(request_sessions)
        # A worker-like Session sees the same committed setting, then commits
        # its update through the same production transaction-owning service.
        with factory() as worker:
            assert all(worker is not session for session in request_sessions)
            settings = get_runtime_llm_settings(worker, tenant_id=1, user_id=2)
            assert settings.provider_models["deepseek"] == "deepseek-v4-flash"
            upsert_provider_setting(worker, tenant_id=1, user_id=2, provider="deepseek",
                model="deepseek-v4-pro", api_key=None)
        after_worker = client.get("/api/v1/settings/llm")
        assert next(row for row in after_worker.json()["providers"] if row["provider"] == "deepseek")[
            "model"] == "deepseek-v4-pro"
        # A rolled-back independent write cannot contaminate later Sessions.
        with factory() as rolled_back:
            rolled_back.get(User, 2).email = "uncommitted@example.com"
            rolled_back.flush()
            rolled_back.rollback()
        with factory() as observer:
            assert observer.get(User, 2).email == "harness@example.com"
        record_property("HARNESS_TRANSACTION_BOUNDARY", "PASS")
        record_property("CROSS_SESSION_VISIBILITY", "PASS")
        record_property("PRODUCTION_COMMIT_SEMANTICS_PRESERVED", True)
        record_property("NESTED_TRANSACTION_ERROR", 0)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_fresh_schema_not_contaminated_by_previous_case(formal):  # noqa: F811
    _, _, factory = formal
    with factory() as db:
        settings = get_runtime_llm_settings(db, tenant_id=1, user_id=2)
        assert settings.provider_configs == {}
        assert db.get(User, 2).email == "formal@example.test"
