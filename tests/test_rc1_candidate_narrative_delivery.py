"""Default authenticated formal delivery, real Hybrid evidence, fake generation.

The only generation test double is registered through the real ProviderRegistry.
No router, synthesis source, evidence, citation or READY result is fabricated.
The immutable original report is explicitly supplied; no trimmed-PDF fallback.
"""

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from auth.password import hash_password
from config import EMBEDDING_MODEL, EMBEDDING_MODEL_REVISION
from embedding import embed_passages, load_embedding_model
from llm.providers.base_provider import BaseProvider
from llm.providers.provider_models import ChatResponse, ProviderCapability
from llm.providers.provider_registry import ProviderRegistry
from models.user import User
from services.formal_ingestion_composition import FormalIngestionComposition
from services.llm_settings_service import upsert_provider_setting
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import get_db
from tests.formal_ingestion_test_harness import formal  # noqa: F401

SOURCE_SHA = "474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288"


def test_default_candidate_formal_narrative(formal, tmp_path, monkeypatch, record_property):  # noqa: F811
    _, _, factory = formal
    configured = os.environ.get("FINANCIAL_RAG_TEST_PDF_PATH") or os.environ.get("P2_2_ORIGINAL_REPORT")
    assert configured, "Set FINANCIAL_RAG_TEST_PDF_PATH to the external qualified complete report (see docs/releases/external-fixture.md)."
    source = Path(configured)
    assert source.is_file(), "Configured external report fixture does not exist."
    data = source.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA
    model = load_embedding_model()
    calls = []
    evidence_seen = []
    failures = []

    class OfflineProvider(BaseProvider):
        def __init__(self, config):
            assert config.provider == "deepseek" and config.model == "deepseek-v4-flash"
            assert config.api_key == "isolated-offline-no-network"
            assert config.timeout == 60 and config.total_deadline == 120
            assert config.connect_timeout == 10 and config.read_timeout == 45
            assert config.stream is False
            self.model = config.model

        @property
        def provider_name(self):
            return "deepseek"

        def health(self):
            return True

        def list_models(self):
            return [self.model]

        def get_capability(self):
            return ProviderCapability(supports_system_prompt=True, supports_usage=False,
                                      supports_thinking_control=True)

        def chat(self, request):
            assert request.deadline is not None
            assert request.thinking_enabled is False and request.max_tokens == 1024
            payload = json.loads(request.messages[0]["content"])
            calls.append("review" if "draft" in payload else "generation")
            if "draft" in payload:
                response = {"claims": [{"claim_id": row["claim_id"],
                    "evidence_ids": row["evidence_ids"], "verdict": "SUPPORTED",
                    "causal_strength": "UNSUPPORTED", "rationale": "Exact source disclosure."}
                    for row in payload["claims"]]}
                assert "公司主要业务是茅台酒及系列酒的生产与销售" in payload["draft"]
            else:
                assert payload["coverage"]["complete"] is None
                evidence_seen.extend(payload["evidence"])
                disclosed = "公司主要业务是茅台酒及系列酒的生产与销售"
                matches = [row for row in payload["evidence"]
                    if disclosed in row["payload"]["text"] and row["payload"]["page"] == 8]
                assert matches, "Original page-8 disclosure must reach the real generator"
                response = {"claims": [{"text": disclosed,
                    "evidence_ids": [matches[0]["evidence_id"]],
                    "causal_strength": "UNSUPPORTED", "caveat": None}]}
            return ChatResponse(content=json.dumps(response, ensure_ascii=False),
                provider=self.provider_name, model=self.model, finish_reason="stop")

    monkeypatch.setitem(ProviderRegistry._registry, "deepseek", OfflineProvider)
    # Observe failures without replacing the real workflow or changing admission.
    from api.routers import grounded_answers

    original_synthesize = grounded_answers.synthesize_narrative

    def observed_synthesize(*args, **kwargs):
        outcome = original_synthesize(*args, **kwargs)
        failures.append({"reason": outcome.reason, "failure_class": outcome.failure_class})
        return outcome

    monkeypatch.setattr(grounded_answers, "synthesize_narrative", observed_synthesize)
    with ChromaEmbeddingStore(tmp_path / "vectors", host="") as vectors:
        runtime = FormalIngestionComposition(factory, storage_root=tmp_path / "uploads",
            artifact_root=tmp_path / "artifacts", vectors=vectors,
            embedder=lambda texts: embed_passages(model, texts).tolist(),
            embedding_identity=f"{EMBEDDING_MODEL}@{EMBEDDING_MODEL_REVISION}")
        monkeypatch.setattr("services.rc1_delivery.get_delivery", lambda: runtime)
        with factory() as db, db.begin():
            user = db.get(User, 2)
            user.email = "candidate@example.com"
            user.password_hash = hash_password("Candidate-Isolated-Password")
        # The settings service owns commit/refresh. It must not run inside
        # a caller-owned Session.begin() context already closed by its commit.
        with factory() as db:
            upsert_provider_setting(db, tenant_id=1, user_id=2, provider="deepseek",
                model="deepseek-v4-flash", api_key="isolated-offline-no-network")

        def isolated_db():
            with factory() as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        try:
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"email": "candidate@example.com",
                "password": "Candidate-Isolated-Password"})
            assert login.status_code == 200
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
            assert client.get("/api/v1/auth/me").json()["id"] == 2
            created = client.post("/api/v1/upload-sessions", json={"filename": source.name,
                "expected_size": len(data), "expected_sha256": SOURCE_SHA})
            assert created.status_code == 201
            path = "/api/v1/upload-sessions/" + created.json()["upload_id"]
            assert client.post(path + "/content", files={"file": (source.name, data)}).status_code == 200
            finalized = client.post(path + "/finalize")
            assert finalized.status_code == 200
            from tasks.formal_ready_tasks import process_formal_ready_task

            job = finalized.json()["ingestion_job_id"]
            process_formal_ready_task(job)
            state = client.get(path + "/ingestion").json()
            assert state["status"] == "ready" and len(state["completed_stages"]) == 5
            assert client.get("/api/v1/upload-sessions/ready-documents").json()["items"]
            response = client.post("/api/v1/grounded-chat", json={"ingestion_job_id": job,
                "question": "说明贵州茅台的主要业务", "answer_language": "zh-CN"})
            record_property("workflow_diagnostics", json.dumps(failures))
            record_property("fake_provider_calls", json.dumps(calls))
            assert response.status_code == 200, (response.text, failures, calls)
            result = response.json()
            assert result["plan"]["verified"] is True
            assert calls == ["generation", "review"]
            assert result["usage"]["usage_complete"] is False
            assert evidence_seen and result["citations"]
            citation = result["citations"][0]
            assert citation["page"] == 8 and citation["content_sha256"] == SOURCE_SHA
            pdf = client.get(f"/api/v1/documents/{citation['document_id']}/source",
                params={"version": SOURCE_SHA, "page": 8})
            assert pdf.status_code == 200 and pdf.content == data
            record_property("source_sha256", SOURCE_SHA)
            record_property("embedding_identity", runtime.index.embedding_identity)
        finally:
            app.dependency_overrides.pop(get_db, None)
