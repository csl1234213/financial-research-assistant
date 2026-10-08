from typing import Any, Dict, Optional

import requests


class APIClientError(Exception):
    """
    Unified API Client exception.

    Wraps all requests-level errors so callers
    (Streamlit, CLI, Scheduler) never touch requests directly.
    """
    pass


class APIClient:
    """
    V4 API Client

    Single entry point for all API calls.
    Streamlit, CLI, Scheduler, Batch Job — all use this.

    Usage:
        client = APIClient(base_url="http://127.0.0.1:8000", timeout=120)
        result = client.chat(question="...", company="Apple")
        knowledge = client.knowledge()
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        try:
            resp = self._session.request(
                method,
                self._url(path),
                timeout=self.timeout,
                **kwargs,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise APIClientError(str(e)) from e

    # =========================
    # Chat
    # =========================

    def chat(
        self,
        question: str,
        company: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/chat",
            json={"question": question, "company": company},
        )

    # =========================
    # Knowledge
    # =========================

    def knowledge(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/knowledge")

    def knowledge_statistics(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/knowledge/statistics")

    # =========================
    # Upload
    # =========================

    def upload(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/upload",
            files={"file": (filename, file_bytes, "application/pdf")},
        )

    # =========================
    # Refresh
    # =========================

    def refresh(self) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/refresh")

    # =========================
    # Health
    # =========================

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/health")
