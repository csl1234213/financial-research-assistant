"""Explicit ingestion composition works when answer implementations cannot load."""
import hashlib
import subprocess
import sys

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app_factory import create_app
from api.routers.upload_sessions import build_upload_session_router
from auth.jwt import create_access_token
from services.upload_session_service import UploadSessionService
from storage.database import get_db
from tests.formal_ingestion_test_harness import SOURCE, formal  # noqa: F401


def test_ingestion_import_and_worker_without_answer():
    code = '''
import importlib.abc
import sys
class RejectAnswer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('core.answer_synthesis', 'api.routers.grounded_answers',
                                'services.ready_fact_synthesis_source', 'llm.adapters')):
            raise AssertionError('forbidden answer dependency: ' + fullname)
sys.meta_path.insert(0, RejectAnswer())
from api.app_factory import create_app
from api.routers.upload_sessions import build_upload_session_router
from tasks.ingestion_stage_executor import IngestionStageExecutor
from tasks.ingestion_task_runner import IngestionTaskRunner
class Ledger:
    artifact_store = None
executor = IngestionStageExecutor(Ledger(), source_resolver=None, clock=None)
runner = IngestionTaskRunner(executor)
app = create_app(profile='ingestion')
assert runner.executor is executor
assert not any(name.startswith('core.answer_synthesis') for name in sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_ingestion_app_health_and_authenticated_create(formal, tmp_path):  # noqa: F811
    engine, repo, _ = formal
    app = create_app(profile="ingestion", ingestion_routers=(
        build_upload_session_router(UploadSessionService(repo, tmp_path)),))

    def db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "capability": "ingestion"}
        data = SOURCE.read_bytes()
        response = client.post("/upload-sessions", headers={
            "Authorization": "Bearer " + create_access_token({"sub": "2"}),
        }, json={"filename": "report.pdf", "expected_size": len(data),
                 "expected_sha256": hashlib.sha256(data).hexdigest()})
        assert response.status_code == 201
        assert not any("grounded" in path for path in app.openapi()["paths"])
