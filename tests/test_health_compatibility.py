from fastapi.testclient import TestClient

import api.routers.health as health_module
from api.app import app


def test_root_health_compatibility_alias_is_deterministic(monkeypatch):
    monkeypatch.setattr(health_module, "_check_database", lambda: "ok")
    monkeypatch.setattr(health_module, "_check_redis", lambda: "ok")
    monkeypatch.setattr(health_module, "_check_chroma", lambda: "ok")
    monkeypatch.setattr(health_module, "_check_runtime", lambda: "ok")
    monkeypatch.setattr(health_module, "_check_embedding_model", lambda: "loaded")
    monkeypatch.setattr(
        health_module,
        "get_checkpoint_backend_status",
        lambda: {"backend": "postgres", "status": "ok"},
    )
    monkeypatch.setattr(health_module, "get_document_count", lambda: 0)

    response = TestClient(app).get("/health")
    payload = response.json()

    assert response.status_code == 200
    assert payload["api"] == "ok"
    assert isinstance(payload["version"], str)
    assert payload["version"]
