"""Normal authenticated foundation path without RC1 fault injection."""

import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.routers.upload_sessions import build_upload_session_router
from auth.jwt import create_access_token
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint
from models.task import Task
from services.upload_session_service import UploadSessionService
from storage.database import get_db
from tests.formal_ingestion_test_harness import SOURCE, formal  # noqa: F401


def test_authenticated_normal_upload_finalize(formal, tmp_path):  # noqa: F811
    engine, repository, factory = formal
    app = FastAPI()
    app.include_router(build_upload_session_router(UploadSessionService(repository, tmp_path / "upload")))

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    headers = {"Authorization": "Bearer " + create_access_token({"sub": "2"})}
    data = SOURCE.read_bytes()
    with TestClient(app) as client:
        created = client.post("/upload-sessions", headers=headers, json={
            "filename": "report.pdf", "expected_size": len(data),
            "expected_sha256": hashlib.sha256(data).hexdigest(),
        })
        assert created.status_code == 201
        path = "/upload-sessions/" + created.json()["upload_id"]
        assert client.post(path + "/content", headers=headers,
                           files={"file": ("report.pdf", data, "application/pdf")}).status_code == 200
        assert client.post(path + "/finalize", headers=headers).status_code == 200
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(func.count()).select_from(TaskStageCheckpoint)) == 5
