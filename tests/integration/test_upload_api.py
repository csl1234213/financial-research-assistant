import hashlib
import io
import os
from pathlib import Path
from unittest.mock import MagicMock

import fitz
import pytest
from docx import Document as WordDocument
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import sessionmaker

from api.app import app
from auth.dependencies import get_current_user
from models.document import Document
from models.task import Task
from models.tenant import Tenant
from models.user import User
from storage.database import Base, get_db
from tests.storage_paths import create_sqlite_test_database

TEST_DATABASE_URL, engine = create_sqlite_test_database("test_upload_api.db")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
    b"startxref\n190\n"
    b"%%EOF"
)
ZERO_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 0>>endobj\n"
    b"trailer<</Size 3/Root 1 0 R>>\n"
    b"%%EOF"
)


def _encrypted_pdf() -> bytes:
    document = fitz.open()
    try:
        document.new_page()
        return document.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner-password",
            user_pw="user-password",
        )
    finally:
        document.close()


def _xlsx_report() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Metric", "Q1 FY2026", "Q1 FY2025"])
    sheet.append(["Revenue", "$95.4 billion", "$90.8 billion"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _docx_report() -> bytes:
    document = WordDocument()
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Metric"
    table.rows[0].cells[1].text = "Q1 FY2026"
    row = table.add_row().cells
    row[0].text = "Revenue"
    row[1].text = "95.4 billion USD"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    db_path = TEST_DATABASE_URL.replace("sqlite:///", "")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except (PermissionError, OSError):
            pass


@pytest.fixture
def user():
    db = TestingSessionLocal()
    try:
        tenant = Tenant(name="Upload Tenant", slug="upload-tenant")
        db.add(tenant)
        db.flush()
        current_user = User(
            email="upload@example.com",
            password_hash="not-used-in-this-test",
            tenant_id=tenant.id,
        )
        db.add(current_user)
        db.commit()
        db.refresh(current_user)
        return current_user
    finally:
        db.close()


@pytest.fixture
def client(user):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def upload_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("api.routers.upload.UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("api.routers.upload.can_upload", lambda *_: True)
    monkeypatch.setattr("api.routers.upload.record_usage", lambda **_: None)
    broker = MagicMock()
    broker.enabled = False
    monkeypatch.setattr("api.routers.upload.get_broker", lambda: broker)
    return tmp_path


@pytest.mark.integration
class TestUploadAPI:
    def test_upload_requires_authentication(self):
        app.dependency_overrides[get_db] = _override_get_db
        with TestClient(app) as test_client:
            response = test_client.post(
                "/api/v1/upload",
                files={"file": ("test_report.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            )
        app.dependency_overrides.clear()
        assert response.status_code == 401

    def test_upload_valid_pdf_creates_tenant_document_and_task(self, client, upload_dir, user):
        response = client.post(
            "/api/v1/upload",
            files={"file": ("Tesla_Q2_2025.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "upload success"
        assert data["file"] == "Tesla_Q2_2025.pdf"
        assert data["status"] == "pending"

        db = TestingSessionLocal()
        try:
            document = db.get(Document, data["document_id"])
            task = db.query(Task).filter(Task.public_id == data["task_id"]).one()

            assert document is not None
            assert document.tenant_id == user.tenant_id
            assert document.status == "processing"
            assert document.content_sha256 == hashlib.sha256(MINIMAL_PDF).hexdigest()
            assert document.byte_size == len(MINIMAL_PDF)
            assert document.uploaded_by_user_id == user.id
            assert document.indexed_chunk_count == 0
            assert task.tenant_id == user.tenant_id
            assert task.payload["document_id"] == document.id
            assert task.payload["content_sha256"] == document.content_sha256
            persisted_file = Path(task.payload["file_path"])
            assert persisted_file.is_relative_to(upload_dir)
            assert persisted_file.name == "Tesla_Q2_2025.pdf"
            assert persisted_file.read_bytes() == MINIMAL_PDF
        finally:
            db.close()

    @pytest.mark.parametrize(
        ("filename", "content", "content_type"),
        [
            ("quarterly.xlsx", _xlsx_report(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("quarterly.docx", _docx_report(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("quarterly.csv", b"Metric,Q1 2026\nRevenue,95.4 billion USD\n", "text/csv"),
        ],
        ids=["xlsx", "docx", "csv"],
    )
    def test_upload_supported_structured_report_formats_creates_processing_task(
        self,
        client,
        upload_dir,
        filename,
        content,
        content_type,
    ):
        response = client.post(
            "/api/v1/upload",
            files={"file": (filename, io.BytesIO(content), content_type)},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["file"] == filename
        db = TestingSessionLocal()
        try:
            task = db.query(Task).filter(Task.public_id == data["task_id"]).one()
            persisted_file = Path(task.payload["file_path"])
            assert persisted_file.name == filename
            assert persisted_file.read_bytes() == content
        finally:
            db.close()

    def test_duplicate_content_in_same_tenant_returns_409(
        self,
        client,
        upload_dir,
    ):
        first = client.post(
            "/api/v1/upload",
            files={
                "file": (
                    "Tesla_Q2_2025.pdf",
                    io.BytesIO(MINIMAL_PDF),
                    "application/pdf",
                )
            },
        )
        duplicate = client.post(
            "/api/v1/upload",
            files={
                "file": (
                    "renamed-copy.pdf",
                    io.BytesIO(MINIMAL_PDF),
                    "application/pdf",
                )
            },
        )

        assert first.status_code == 200
        assert duplicate.status_code == 409
        assert duplicate.json() == {
            "detail": "This document already exists in your workspace."
        }

        db = TestingSessionLocal()
        try:
            assert db.query(Document).count() == 1
            assert db.query(Task).count() == 1
        finally:
            db.close()
        assert len(list(upload_dir.rglob("*.pdf"))) == 1

    def test_same_content_in_another_tenant_is_not_disclosed(
        self,
        client,
        upload_dir,
    ):
        db = TestingSessionLocal()
        try:
            other_tenant = Tenant(name="Other Tenant", slug="other-tenant")
            db.add(other_tenant)
            db.flush()
            db.add(
                Document(
                    filename="private.pdf",
                    company="Private",
                    period="Unknown",
                    status="indexed",
                    tenant_id=other_tenant.id,
                    content_sha256=hashlib.sha256(MINIMAL_PDF).hexdigest(),
                    byte_size=len(MINIMAL_PDF),
                )
            )
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/v1/upload",
            files={
                "file": (
                    "tenant-copy.pdf",
                    io.BytesIO(MINIMAL_PDF),
                    "application/pdf",
                )
            },
        )

        assert response.status_code == 200
        assert len(list(upload_dir.rglob("*.pdf"))) == 1

    def test_upload_non_pdf_returns_400(self, client, upload_dir):
        response = client.post(
            "/api/v1/upload",
            files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
        )
        assert response.status_code == 400

    def test_upload_rejects_non_pdf_content_with_pdf_extension(self, client, upload_dir):
        response = client.post(
            "/api/v1/upload",
            files={
                "file": (
                    "disguised.pdf",
                    io.BytesIO(b"this is not a PDF"),
                    "application/pdf",
                )
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Uploaded content does not match a valid PDF file"

    @pytest.mark.parametrize(
        ("filename", "content"),
        [
            ("zero-pages.pdf", ZERO_PAGE_PDF),
            ("damaged.pdf", b"%PDF-1.4\nthis is damaged\n%%EOF"),
            ("encrypted.pdf", _encrypted_pdf()),
        ],
    )
    def test_unusable_pdf_does_not_create_document_or_task(
        self,
        client,
        upload_dir,
        filename,
        content,
    ):
        response = client.post(
            "/api/v1/upload",
            files={"file": (filename, io.BytesIO(content), "application/pdf")},
        )

        assert response.status_code == 400
        db = TestingSessionLocal()
        try:
            assert db.query(Document).count() == 0
            assert db.query(Task).count() == 0
        finally:
            db.close()
        assert list(upload_dir.rglob("*")) == []

    def test_upload_enforces_size_limit(self, client, upload_dir, monkeypatch):
        monkeypatch.setattr("api.routers.upload.MAX_UPLOAD_BYTES", 10)
        response = client.post(
            "/api/v1/upload",
            files={"file": ("large.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
        )
        assert response.status_code == 413
