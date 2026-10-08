import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import api.routers.health as health_module
from api.app import app

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_has_status(self):
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded")

    def test_health_has_version(self):
        response = client.get("/health")
        data = response.json()
        assert "version" in data

    def test_health_has_database_status(self):
        response = client.get("/health")
        data = response.json()
        assert "database" in data
        assert data["database"] in ("ok", "unavailable", "disabled")

    def test_health_has_redis_status(self):
        response = client.get("/health")
        data = response.json()
        assert "redis" in data
        assert data["redis"] in ("ok", "disabled", "unavailable")
        assert data["runtime"] in ("ok", "unavailable")
        assert data["chroma"] in ("ok", "unknown", "unavailable")
        assert data["embedding_model"] in (
            "loaded",
            "not_loaded",
            "error",
            "unknown",
        )
        assert data["checkpointing"]["backend"] in {"memory", "postgres"}
        assert data["checkpointing"]["status"] in {
            "ephemeral",
            "not_checked",
            "ok",
            "fallback",
        }

    def test_health_api_v1_path(self):
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_root_endpoint(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "version" in data

    def test_local_chroma_state_is_unknown_without_opening_the_store(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("CHROMA_HOST", "")

        def unexpected_probe(*_args, **_kwargs):
            raise AssertionError("local health check must not open Chroma")

        monkeypatch.setattr(health_module, "urlopen", unexpected_probe)

        assert health_module._check_chroma() == "unknown"

    def test_chroma_http_heartbeat_reports_reachability(self, monkeypatch):
        monkeypatch.setenv("CHROMA_HOST", "chromadb")
        monkeypatch.setenv("CHROMA_PORT", "8000")
        monkeypatch.setenv("CHROMA_SSL", "false")

        class HealthyResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def heartbeat(url, *, timeout):
            assert url == "http://chromadb:8000/api/v2/heartbeat"
            assert timeout == 2
            return HealthyResponse()

        monkeypatch.setattr(health_module, "urlopen", heartbeat)

        assert health_module._check_chroma() == "ok"

    def test_embedding_status_uses_public_lazy_lifecycle_state(self, monkeypatch):
        monkeypatch.setattr(
            health_module,
            "get_embedding_model_status",
            lambda: {"state": "not_loaded"},
        )
        assert health_module._check_embedding_model() == "not_loaded"

        monkeypatch.setattr(
            health_module,
            "get_embedding_model_status",
            lambda: {"state": "loaded"},
        )
        assert health_module._check_embedding_model() == "loaded"

    def test_health_response_degrades_on_dependency_failure(self, monkeypatch):
        monkeypatch.setattr(health_module, "_check_database", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_redis", lambda: "unavailable")
        monkeypatch.setattr(health_module, "_check_chroma", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_runtime", lambda: "ok")
        monkeypatch.setattr(
            health_module,
            "_check_embedding_model",
            lambda: "not_loaded",
        )

        response = client.get("/api/v1/health")
        data = response.json()

        assert data["status"] == "degraded"
        assert data["redis"] == "unavailable"
        assert data["chroma"] == "ok"
        assert data["runtime"] == "ok"
        assert data["embedding_model"] == "not_loaded"

    def test_readiness_returns_503_on_dependency_failure(self, monkeypatch):
        monkeypatch.setattr(health_module, "_check_database", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_redis", lambda: "unavailable")
        monkeypatch.setattr(health_module, "_check_chroma", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_runtime", lambda: "ok")
        monkeypatch.setattr(
            health_module,
            "_check_embedding_model",
            lambda: "loaded",
        )
        monkeypatch.setattr(
            health_module,
            "get_checkpoint_backend_status",
            lambda: {"backend": "postgres", "status": "ok"},
        )

        response = client.get("/api/v1/ready")

        assert response.status_code == 503
        assert response.json()["status"] == "degraded"

    def test_readiness_returns_200_when_dependencies_are_ready(self, monkeypatch):
        monkeypatch.setattr(health_module, "_check_database", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_redis", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_chroma", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_runtime", lambda: "ok")
        monkeypatch.setattr(
            health_module,
            "_check_embedding_model",
            lambda: "loaded",
        )
        monkeypatch.setattr(
            health_module,
            "get_checkpoint_backend_status",
            lambda: {"backend": "postgres", "status": "ok"},
        )

        response = client.get("/api/v1/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_production_health_degrades_when_chroma_state_is_unknown(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("APP_ENV", "production")

        assert (
            health_module._overall_status(
                database="ok",
                redis="ok",
                chroma="unknown",
                runtime="ok",
                embedding_model="not_loaded",
            )
            == "degraded"
        )

    def test_health_degrades_after_checkpoint_backend_fallback(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(health_module, "_check_database", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_redis", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_chroma", lambda: "ok")
        monkeypatch.setattr(health_module, "_check_runtime", lambda: "ok")
        monkeypatch.setattr(
            health_module,
            "_check_embedding_model",
            lambda: "loaded",
        )
        monkeypatch.setattr(
            health_module,
            "get_checkpoint_backend_status",
            lambda: {
                "backend": "postgres",
                "status": "fallback",
                "fallback_count": 1,
                "last_error_type": "OperationalError",
            },
        )

        response = client.get("/api/v1/health")

        assert response.json()["status"] == "degraded"
        assert response.json()["checkpointing"]["fallback_count"] == 1
