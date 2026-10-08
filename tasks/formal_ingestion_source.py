"""Canonical finalized upload source, independent of experimental registration."""

from pathlib import Path

from sqlalchemy import select

from models.document import Document
from models.ingestion_persistence import UploadSession
from models.task import Task


class FormalUploadSource:
    def __init__(self, session_factory, storage_root):
        self.session_factory = session_factory
        self.root = Path(storage_root).resolve()

    def __call__(self, lease):
        with self.session_factory() as session:
            task = session.scalar(
                select(Task).where(Task.public_id == lease.task_id, Task.tenant_id == lease.tenant_id)
            )
            if task is None:
                raise PermissionError("INGESTION_SOURCE_NOT_FOUND")
            upload = session.scalar(select(UploadSession).where(UploadSession.task_id == task.id))
            document = session.get(Document, lease.document_id)
            if upload is None or document is None:
                raise PermissionError("INGESTION_SOURCE_NOT_FOUND")
            if (
                upload.status != "FINALIZED"
                or upload.tenant_id != task.tenant_id
                or upload.user_id != task.user_id
                or upload.document_id != document.id
                or document.tenant_id != task.tenant_id
                or document.uploaded_by_user_id != task.user_id
                or upload.verified_sha256 != lease.source_sha256
                or document.content_sha256 != lease.source_sha256
                or not upload.storage_path
            ):
                raise ValueError("INGESTION_SOURCE_BINDING_FAILED")
            path = Path(upload.storage_path).resolve()
            expected = (
                self.root / str(upload.tenant_id) / str(upload.user_id) / upload.upload_id / "document.pdf"
            ).resolve()
            if path != expected or not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError("INGESTION_SOURCE_PATH_INVALID")
            return path
