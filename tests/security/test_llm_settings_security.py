import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agent.planning.task_enums import TaskType as PlannedTaskType
from api.app import app
from auth.jwt import create_access_token
from models.llm_provider_setting import LLMProviderSetting
from models.tenant import Tenant
from models.user import User
from services.llm_settings_service import (
    SUPPORTED_LLM_PROVIDERS,
    CredentialEncryptionError,
    _decrypt_api_key,
    _encrypt_api_key,
    get_runtime_llm_settings,
)
from storage.database import Base, _import_models, get_db

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def database():
    _import_models()
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def principals():
    with TestingSessionLocal() as db:
        tenant_a = Tenant(name="Settings Tenant A", slug="settings-tenant-a")
        tenant_b = Tenant(name="Settings Tenant B", slug="settings-tenant-b")
        db.add_all([tenant_a, tenant_b])
        db.flush()

        user_a = User(
            email="settings-a@example.com",
            password_hash="not-used",
            tenant_id=tenant_a.id,
        )
        user_a_peer = User(
            email="settings-a-peer@example.com",
            password_hash="not-used",
            tenant_id=tenant_a.id,
        )
        user_b = User(
            email="settings-b@example.com",
            password_hash="not-used",
            tenant_id=tenant_b.id,
        )
        db.add_all([user_a, user_a_peer, user_b])
        db.commit()
        return {
            "tenant_a": tenant_a.id,
            "tenant_b": tenant_b.id,
            "user_a": user_a.id,
            "user_a_peer": user_a_peer.id,
            "user_b": user_b.id,
        }


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def _provider(payload: dict, provider: str) -> dict:
    return next(
        item
        for item in payload["providers"]
        if item["provider"] == provider
    )


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/api/v1/settings/llm", None),
        (
            "put",
            "/api/v1/settings/llm/deepseek",
            {"api_key": "anonymous-secret"},
        ),
        ("delete", "/api/v1/settings/llm/deepseek", None),
        (
            "put",
            "/api/v1/settings/llm/default",
            {"provider": "deepseek"},
        ),
    ],
)
def test_llm_settings_endpoints_require_authentication(
    client,
    method,
    path,
    json_body,
):
    response = client.request(method, path, json=json_body)

    assert response.status_code == 401


def test_put_encrypts_key_and_get_never_returns_secret_or_ciphertext(
    client,
    principals,
    caplog,
):
    api_key = "sk-live-settings-secret-A1B2"
    headers = _auth_headers(principals["user_a"])
    caplog.set_level(logging.DEBUG)

    saved = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
        json={"api_key": api_key, "model": "deepseek-v4-flash"},
    )

    assert saved.status_code == 200
    assert saved.headers["cache-control"] == "no-store"
    assert saved.json()["configured"] is True
    assert saved.json()["key_hint"] == "••••A1B2"
    assert "api_key" not in saved.json()
    assert "encrypted_api_key" not in saved.json()
    assert api_key not in saved.text

    with TestingSessionLocal() as db:
        row = db.query(LLMProviderSetting).one()
        ciphertext = row.encrypted_api_key
        assert ciphertext != api_key
        assert api_key not in ciphertext

        runtime_settings = get_runtime_llm_settings(
            db,
            tenant_id=principals["tenant_a"],
            user_id=principals["user_a"],
        )
        assert runtime_settings.provider_configs["deepseek"]["api_key"] == api_key

    fetched = client.get("/api/v1/settings/llm", headers=headers)

    assert fetched.status_code == 200
    assert fetched.headers["cache-control"] == "no-store"
    assert _provider(fetched.json(), "deepseek")["configured"] is True
    assert api_key not in fetched.text
    assert ciphertext not in fetched.text
    assert api_key not in caplog.text
    assert ciphertext not in caplog.text


def test_settings_are_isolated_between_users_and_tenants(
    client,
    principals,
):
    owner_headers = _auth_headers(principals["user_a"])
    peer_headers = _auth_headers(principals["user_a_peer"])
    other_tenant_headers = _auth_headers(principals["user_b"])
    api_key = "sk-owner-only-9876"

    saved = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=owner_headers,
        json={"api_key": api_key},
    )
    assert saved.status_code == 200

    for isolated_headers in (peer_headers, other_tenant_headers):
        fetched = client.get(
            "/api/v1/settings/llm",
            headers=isolated_headers,
        )
        assert fetched.status_code == 200
        assert _provider(fetched.json(), "deepseek")["configured"] is False
        assert api_key not in fetched.text

        cleared = client.delete(
            "/api/v1/settings/llm/deepseek",
            headers=isolated_headers,
        )
        assert cleared.status_code == 200
        assert cleared.json()["configured"] is False

    owner_fetched = client.get(
        "/api/v1/settings/llm",
        headers=owner_headers,
    )
    assert _provider(owner_fetched.json(), "deepseek")["configured"] is True

    with TestingSessionLocal() as db:
        rows = db.query(LLMProviderSetting).all()
        assert len(rows) == 1
        assert rows[0].tenant_id == principals["tenant_a"]
        assert rows[0].user_id == principals["user_a"]


def test_provider_and_model_allowlist_is_enforced(client, principals):
    headers = _auth_headers(principals["user_a"])

    fetched = client.get("/api/v1/settings/llm", headers=headers)
    assert fetched.status_code == 200
    assert {
        item["provider"]
        for item in fetched.json()["providers"]
    } == set(SUPPORTED_LLM_PROVIDERS)

    unsupported_provider = client.put(
        "/api/v1/settings/llm/unsupported",
        headers=headers,
        json={"api_key": "sk-not-supported"},
    )
    unsupported_model = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
        json={
            "api_key": "sk-valid-shape",
            "model": "not-a-deepseek-model",
        },
    )

    assert unsupported_provider.status_code == 404
    assert unsupported_provider.json()["detail"] == "Unsupported LLM provider"
    assert unsupported_model.status_code == 422
    assert unsupported_model.json()["detail"] == (
        "Unsupported model for LLM provider"
    )
    with TestingSessionLocal() as db:
        assert db.query(LLMProviderSetting).count() == 0


def test_ollama_can_be_configured_without_key_and_runtime_uses_local_endpoint(
    client,
    principals,
):
    headers = _auth_headers(principals["user_a"])
    endpoint = "http://host.docker.internal:11434/"
    response = client.put(
        "/api/v1/settings/llm/ollama",
        headers=headers,
        json={"model": "qwen3.8:latest", "base_url": endpoint},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["is_default"] is True
    assert body["key_hint"] is None
    assert body["model"] == "qwen3.8:latest"
    assert body["base_url"] == "http://host.docker.internal:11434"
    assert "api_key" not in body

    with TestingSessionLocal() as db:
        setting = db.query(LLMProviderSetting).one()
        assert setting.encrypted_api_key is None
        assert setting.key_hint is None
        runtime_settings = get_runtime_llm_settings(
            db,
            tenant_id=principals["tenant_a"],
            user_id=principals["user_a"],
        )
    assert runtime_settings.default_provider == "ollama"
    assert runtime_settings.provider_models["ollama"] == "qwen3.8:latest"
    assert runtime_settings.provider_configs["ollama"] == {
        "api_key": "",
        "base_url": "http://host.docker.internal:11434",
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com:11434",
        "http://169.254.169.254/latest/meta-data",
        "http://host.docker.internal:11434/admin",
        "http://user:password@ollama:11434",
        "https://localhost:11434",
    ],
)
def test_ollama_rejects_nonlocal_or_ambiguous_endpoints(
    client,
    principals,
    endpoint,
):
    response = client.put(
        "/api/v1/settings/llm/ollama",
        headers=_auth_headers(principals["user_a"]),
        json={"model": "qwen3.8:latest", "base_url": endpoint},
    )

    assert response.status_code == 422
    with TestingSessionLocal() as db:
        assert db.query(LLMProviderSetting).count() == 0


def test_missing_encryption_key_returns_secret_free_503(
    client,
    principals,
    monkeypatch,
    caplog,
):
    monkeypatch.delenv("LLM_CREDENTIAL_ENCRYPTION_KEYS", raising=False)
    monkeypatch.delenv("LLM_CREDENTIAL_KEY_FILE", raising=False)
    api_key = "sk-must-not-escape-503-1234"
    caplog.set_level(logging.DEBUG)

    response = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=_auth_headers(principals["user_a"]),
        json={"api_key": api_key},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "LLM credential storage is not configured"
    }
    assert api_key not in response.text
    assert api_key not in caplog.text
    with TestingSessionLocal() as db:
        assert db.query(LLMProviderSetting).count() == 0


def test_model_only_update_preserves_encrypted_key(client, principals):
    headers = _auth_headers(principals["user_a"])
    api_key = "sk-model-only-secret-7788"
    first = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
        json={"api_key": api_key, "model": "deepseek-v4-flash"},
    )
    assert first.status_code == 200

    with TestingSessionLocal() as db:
        before = db.query(LLMProviderSetting).one()
        original_ciphertext = before.encrypted_api_key
        original_revision = before.revision

    updated = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
        json={"model": "deepseek-v4-pro"},
    )

    assert updated.status_code == 200
    assert updated.json()["model"] == "deepseek-v4-pro"
    assert updated.json()["key_hint"] == "••••7788"
    assert api_key not in updated.text
    with TestingSessionLocal() as db:
        after = db.query(LLMProviderSetting).one()
        assert after.encrypted_api_key == original_ciphertext
        assert after.revision != original_revision
        assert _decrypt_api_key(after.encrypted_api_key) == api_key


def test_default_provider_selection_is_user_scoped_and_key_free(
    client,
    principals,
):
    owner_headers = _auth_headers(principals["user_a"])
    peer_headers = _auth_headers(principals["user_a_peer"])
    deepseek_key = "sk-default-deepseek-1234"
    openai_key = "sk-default-openai-5678"

    deepseek = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=owner_headers,
        json={"api_key": deepseek_key},
    )
    openai = client.put(
        "/api/v1/settings/llm/openai",
        headers=owner_headers,
        json={"api_key": openai_key, "model": "gpt-5.5"},
    )
    assert deepseek.json()["is_default"] is True
    assert openai.json()["is_default"] is False

    selected = client.put(
        "/api/v1/settings/llm/default",
        headers=owner_headers,
        json={"provider": "openai"},
    )
    assert selected.status_code == 200
    assert selected.json()["default_provider"] == "openai"
    assert _provider(selected.json(), "openai")["is_default"] is True
    assert _provider(selected.json(), "deepseek")["is_default"] is False
    assert deepseek_key not in selected.text
    assert openai_key not in selected.text

    with TestingSessionLocal() as db:
        runtime_settings = get_runtime_llm_settings(
            db,
            tenant_id=principals["tenant_a"],
            user_id=principals["user_a"],
        )
        assert runtime_settings.default_provider == "openai"
        from llm.router import (
            CapabilityRoutingPolicy,
            ModelRouter,
            RoutingContext,
            RoutingPolicy,
            TaskType,
        )

        request_router = ModelRouter(
            policy=RoutingPolicy(
                CapabilityRoutingPolicy(
                    default_provider=runtime_settings.default_provider,
                    provider_models=runtime_settings.provider_models,
                )
            ),
            provider_configs=runtime_settings.provider_configs,
            available_providers=list(runtime_settings.provider_configs),
        )
        for task_type in (
            TaskType.CHAT,
            TaskType.DOCUMENT_QA,
            PlannedTaskType.FINANCIAL_ANALYSIS,
        ):
            routed = request_router.route(RoutingContext(task=task_type))
            assert routed["routing"].provider == "openai"
            assert routed["routing"].model == "gpt-5.5"
            assert routed["provider"].provider_name == "openai"

    peer_selection = client.put(
        "/api/v1/settings/llm/default",
        headers=peer_headers,
        json={"provider": "openai"},
    )
    assert peer_selection.status_code == 422


def test_deleting_default_promotes_a_configured_replacement(client, principals):
    headers = _auth_headers(principals["user_a"])
    client.put(
        "/api/v1/settings/llm/openai",
        headers=headers,
        json={"api_key": "sk-delete-openai-1234"},
    )
    client.put(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
        json={"api_key": "sk-delete-deepseek-5678"},
    )

    cleared = client.delete(
        "/api/v1/settings/llm/openai",
        headers=headers,
    )
    fetched = client.get("/api/v1/settings/llm", headers=headers)

    assert cleared.status_code == 200
    assert fetched.json()["default_provider"] == "deepseek"
    assert _provider(fetched.json(), "deepseek")["is_default"] is True


def test_short_api_key_is_rejected_without_echoing_secret(
    client,
    principals,
):
    short_secret = "abc1234"

    response = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=_auth_headers(principals["user_a"]),
        json={"api_key": short_secret},
    )

    assert response.status_code == 422
    assert short_secret not in response.text
    with TestingSessionLocal() as db:
        assert db.query(LLMProviderSetting).count() == 0


def test_update_keeps_one_row_changes_revision_and_delete_clears_it(
    client,
    principals,
):
    headers = _auth_headers(principals["user_a"])
    first_key = "sk-first-value-1111"
    second_key = "sk-second-value-2222"

    first_response = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
        json={"api_key": first_key, "model": "deepseek-v4-flash"},
    )
    assert first_response.status_code == 200

    with TestingSessionLocal() as db:
        first_row = db.query(LLMProviderSetting).one()
        first_id = first_row.id
        first_revision = first_row.revision
        first_ciphertext = first_row.encrypted_api_key

    second_response = client.put(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
        json={"api_key": second_key, "model": "deepseek-v4-pro"},
    )
    assert second_response.status_code == 200
    assert second_response.json()["key_hint"] == "••••2222"
    assert second_key not in second_response.text

    with TestingSessionLocal() as db:
        rows = db.query(LLMProviderSetting).all()
        assert len(rows) == 1
        updated = rows[0]
        assert updated.id == first_id
        assert updated.revision != first_revision
        assert updated.encrypted_api_key != first_ciphertext
        assert updated.model == "deepseek-v4-pro"

        runtime_settings = get_runtime_llm_settings(
            db,
            tenant_id=principals["tenant_a"],
            user_id=principals["user_a"],
        )
        assert (
            runtime_settings.provider_configs["deepseek"]["api_key"]
            == second_key
        )

    cleared = client.delete(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.headers["cache-control"] == "no-store"
    assert cleared.json()["configured"] is False

    repeated = client.delete(
        "/api/v1/settings/llm/deepseek",
        headers=headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["configured"] is False
    with TestingSessionLocal() as db:
        assert db.query(LLMProviderSetting).count() == 0


def test_multifernet_rotation_decrypts_old_tokens_and_uses_new_primary(
    monkeypatch,
):
    old_key = "rotation-old-key-material"
    new_key = "rotation-new-key-material"
    api_key = "sk-rotation-secret-3456"

    monkeypatch.setenv("LLM_CREDENTIAL_ENCRYPTION_KEYS", old_key)
    old_ciphertext = _encrypt_api_key(api_key)

    monkeypatch.setenv(
        "LLM_CREDENTIAL_ENCRYPTION_KEYS",
        f"{new_key},{old_key}",
    )
    assert _decrypt_api_key(old_ciphertext) == api_key
    new_ciphertext = _encrypt_api_key(api_key)

    monkeypatch.setenv("LLM_CREDENTIAL_ENCRYPTION_KEYS", new_key)
    assert _decrypt_api_key(new_ciphertext) == api_key

    monkeypatch.setenv("LLM_CREDENTIAL_ENCRYPTION_KEYS", old_key)
    with pytest.raises(
        CredentialEncryptionError,
        match="could not be decrypted",
    ):
        _decrypt_api_key(new_ciphertext)
