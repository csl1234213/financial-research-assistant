from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.security import RateLimitMiddleware


def _limited_client(requests_per_window: int = 2) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_window=requests_per_window,
        window_seconds=60,
    )

    @app.get("/resource")
    def resource():
        return {"status": "ok"}

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/ready")
    def ready():
        return {"status": "ok"}

    return TestClient(app)


def test_rate_limit_blocks_requests_after_the_configured_quota(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with _limited_client() as client:
        assert client.get("/resource").status_code == 200
        assert client.get("/resource").status_code == 200
        blocked = client.get("/resource")

    assert blocked.status_code == 429
    assert blocked.json()["retry_after"] == 60


def test_health_endpoint_bypasses_rate_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with _limited_client(requests_per_window=1) as client:
        responses = [client.get("/api/v1/health") for _ in range(3)]

    assert all(response.status_code == 200 for response in responses)


def test_readiness_endpoint_bypasses_rate_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with _limited_client(requests_per_window=1) as client:
        responses = [client.get("/api/v1/ready") for _ in range(3)]

    assert all(response.status_code == 200 for response in responses)


def test_authenticated_users_have_independent_rate_limit_buckets(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with _limited_client(requests_per_window=1) as client:
        first = client.get(
            "/resource",
            headers={"Authorization": "Bearer user-one-token"},
        )
        second = client.get(
            "/resource",
            headers={"Authorization": "Bearer user-two-token"},
        )
        blocked = client.get(
            "/resource",
            headers={"Authorization": "Bearer user-one-token"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert blocked.status_code == 429


def test_forwarded_client_ip_is_used_only_when_explicitly_trusted(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")

    with _limited_client(requests_per_window=1) as client:
        first = client.get(
            "/resource",
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        second = client.get(
            "/resource",
            headers={"X-Forwarded-For": "203.0.113.2"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
