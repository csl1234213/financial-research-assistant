import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


class TestSecurityHeaders:
    def test_x_content_type_options(self):
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self):
        response = client.get("/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self):
        response = client.get("/health")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_referrer_policy(self):
        response = client.get("/health")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_x_download_options(self):
        response = client.get("/health")
        assert response.headers.get("X-Download-Options") == "noopen"

    def test_x_permitted_cross_domain(self):
        response = client.get("/health")
        assert response.headers.get("X-Permitted-Cross-Domain-Policies") == "none"


class TestRequestID:
    def test_request_id_header_present(self):
        response = client.get("/health")
        assert "X-Request-ID" in response.headers

    def test_request_id_is_uuid_format(self):
        response = client.get("/health")
        request_id = response.headers.get("X-Request-ID")
        assert request_id is not None
        assert len(request_id) == 36
        assert request_id.count("-") == 4


class TestResponseTime:
    def test_x_response_time_header(self):
        response = client.get("/health")
        assert "X-Response-Time" in response.headers
        assert response.headers["X-Response-Time"].endswith("ms")


class TestRateLimit:
    def test_health_endpoint_not_rate_limited(self):
        for _ in range(5):
            response = client.get("/health")
            assert response.status_code == 200

    def test_root_endpoint_not_rate_limited(self):
        for _ in range(5):
            response = client.get("/")
            assert response.status_code == 200
