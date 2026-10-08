"""Authenticated finalize regression using formal repositories on both DBs."""

import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from api.routers.upload_sessions import build_upload_session_router
from auth.jwt import create_access_token
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task
from models.user import User
from services.upload_session_service import UploadSessionService
from storage.database import get_db
from storage.upload_session_repository import UploadSessionRepository
from tests.formal_ingestion_test_harness import formal  # noqa: F401

PDF = Path(__file__).parent / "fixtures/moutai-standard-statements-2025.pdf"


def setup_client(engine, repository, root):
    app = FastAPI()
    service = UploadSessionService(repository, root)
    app.include_router(build_upload_session_router(service))

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    return TestClient(app)


def authorization(user=2):
    return {"Authorization": "Bearer " + create_access_token({"sub": str(user)})}


def prepared(client, *, wrong_digest=False):
    data = PDF.read_bytes()
    response = client.post(
        "/upload-sessions",
        headers=authorization(),
        json={
            "filename": "report.pdf",
            "expected_size": len(data),
            "expected_sha256": "0" * 64 if wrong_digest else hashlib.sha256(data).hexdigest(),
        },
    )
    assert response.status_code == 201
    path = "/upload-sessions/" + response.json()["upload_id"]
    response = client.post(
        path + "/content", headers=authorization(), files={"file": ("report.pdf", data, "application/pdf")}
    )
    assert response.status_code == (409 if wrong_digest else 200)
    return path


def test_normal_duplicate_and_service_restart_finalize(formal, tmp_path):  # noqa: F811
    engine, repo, factory = formal
    root = tmp_path / "upload"
    with setup_client(engine, repo, root) as client:
        path = prepared(client)
        result = client.post(path + "/finalize", headers=authorization())
        assert result.status_code == 200
        first = result.json()
        assert client.post(path + "/finalize", headers=authorization()).json() == first
    with setup_client(engine, UploadSessionRepository(factory), root) as client:
        assert client.post(path + "/finalize", headers=authorization()).json() == first
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 5


def test_checksum_and_cross_userspace_rejected(formal, tmp_path):  # noqa: F811
    engine, repo, factory = formal
    with factory() as session, session.begin():
        session.add(User(id=3, tenant_id=1, email="other@example.test", password_hash="fixture"))
    with setup_client(engine, repo, tmp_path / "upload") as client:
        path = prepared(client, wrong_digest=True)
        assert client.post(path + "/finalize", headers=authorization()).status_code == 409
        assert client.get(path, headers=authorization(3)).status_code == 404
        assert client.post(path + "/finalize", headers=authorization(3)).status_code == 404
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 0
        assert session.scalar(select(func.count()).select_from(Task)) == 0


def test_failure_before_commit_is_atomic_and_retriable(formal, tmp_path):  # noqa: F811
    engine, repo, factory = formal
    with setup_client(engine, repo, tmp_path / "upload") as client:
        path = prepared(client)

        def fail(*args):
            raise RuntimeError("finalize transaction fault")

        event.listen(TaskStageCheckpoint, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="transaction fault"):
                client.post(path + "/finalize", headers=authorization())
        finally:
            event.remove(TaskStageCheckpoint, "before_insert", fail)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(Document)) == 0
            assert session.scalar(select(func.count()).select_from(Task)) == 0
            assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 0
        assert client.get(path, headers=authorization()).json()["status"] == "VERIFIED"
        assert client.post(path + "/finalize", headers=authorization()).status_code == 200
