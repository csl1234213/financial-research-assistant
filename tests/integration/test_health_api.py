import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from agent.__version__ import __version__


@pytest.mark.integration
class TestHealthAPI:
    def test_health_status_code(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_json(self, client):
        response = client.get("/api/v1/health")
        data = response.json()
        assert isinstance(data, dict)
        assert data["status"] in {"ok", "degraded"}

    def test_health_version(self, client):
        response = client.get("/api/v1/health")
        data = response.json()
        assert "version" in data
        assert data["version"] == __version__

    def test_health_service_name(self, client):
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["service"] == "Financial Research Copilot"

    def test_health_runtime_fields(self, client):
        response = client.get("/api/v1/health")
        data = response.json()
        assert "api" in data
        assert data["api"] == "ok"
        assert "runtime" in data
        assert data["runtime"] in {"ok", "unavailable"}
        assert data["chroma"] in {"ok", "unknown", "unavailable"}
        assert "embedding_model" in data
        assert data["embedding_model"] in {"loaded", "not_loaded", "error", "unknown"}
        assert "documents" in data

    def test_root_endpoint(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Financial Research Copilot"
        assert data["version"] == __version__
