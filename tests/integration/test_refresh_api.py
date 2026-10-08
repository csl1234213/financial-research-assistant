import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from unittest.mock import patch

import pytest

from api.app import app
from auth.dependencies import require_admin_user


@pytest.fixture
def admin_client(client):
    app.dependency_overrides[require_admin_user] = lambda: object()
    try:
        yield client
    finally:
        app.dependency_overrides.pop(require_admin_user, None)


@pytest.mark.integration
class TestRefreshAPI:
    def test_refresh_requires_authentication(self, client):
        response = client.post("/api/v1/refresh")

        assert response.status_code in {401, 403}

    def test_refresh_status_code(self, admin_client):
        with patch("api.routers.refresh.refresh_knowledge_base"):
            response = admin_client.post("/api/v1/refresh")
        assert response.status_code == 200

    def test_refresh_json_structure(self, admin_client):
        with patch("api.routers.refresh.refresh_knowledge_base"):
            response = admin_client.post("/api/v1/refresh")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data
        assert data["status"] == "ok"
        assert "message" in data
        assert "knowledge base refreshed" in data["message"]
