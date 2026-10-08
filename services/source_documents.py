"""Owner-authorized immutable PDF bytes, never client-selected filesystem paths."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import fitz
from sqlalchemy import select

from models.document import Document
from models.ingestion_persistence import UploadSession


@dataclass(frozen=True)
class SourcePDF:
    content: bytes
    sha256: str
    page_count: int


class SourceDocumentService:
    def __init__(self, session_factory, storage_root, *, max_bytes=50 * 1024 * 1024):
        self.factory = session_factory
        self.root = Path(storage_root).resolve()
        self.max_bytes = max_bytes

    def read(self, document_id, *, tenant_id, user_id, version, page):
        if not re.fullmatch(r"[0-9a-f]{64}", version):
            raise ValueError("INVALID_SOURCE_VERSION")
        if type(page) is not int or page < 1:
            raise ValueError("INVALID_SOURCE_PAGE")
        with self.factory() as session:
            document = session.scalar(select(Document).where(
                Document.id == document_id, Document.tenant_id == tenant_id,
                Document.uploaded_by_user_id == user_id,
            ))
            upload = session.scalar(select(UploadSession).where(
                UploadSession.document_id == document_id,
                UploadSession.tenant_id == tenant_id, UploadSession.user_id == user_id,
                UploadSession.status == "FINALIZED",
            ))
            if document is None or upload is None:
                raise PermissionError("SOURCE_NOT_FOUND")
            if document.content_sha256 != version or upload.verified_sha256 != version:
                raise ValueError("SOURCE_VERSION_CHANGED")
            if not re.fullmatch(r"[0-9a-f]{32}", upload.upload_id) or not upload.storage_path:
                raise ValueError("SOURCE_STORAGE_INVALID")
            expected = self.root / str(tenant_id) / str(user_id) / upload.upload_id / "document.pdf"
            stored = Path(upload.storage_path)
            # Resolve only a DB-owned UUID path. Reject links before resolving;
            # a valid final path alone cannot prove ownership of its ancestors.
            if any(part.is_symlink() for part in (expected, *expected.parents)):
                raise ValueError("SOURCE_STORAGE_INVALID")
            if stored != expected or not expected.resolve().is_relative_to(self.root):
                raise ValueError("SOURCE_STORAGE_INVALID")
            expected_size = upload.expected_size
        try:
            with expected.open("rb") as source:
                content = source.read(self.max_bytes + 1)
        except FileNotFoundError as exc:
            raise PermissionError("SOURCE_NOT_FOUND") from exc
        if len(content) > self.max_bytes or len(content) != expected_size:
            raise ValueError("SOURCE_CONTENT_CHANGED")
        # Return exactly the bytes verified here, not a FileResponse reopening
        # a potentially replaced file after the integrity check.
        if hashlib.sha256(content).hexdigest() != version:
            raise ValueError("SOURCE_CONTENT_CHANGED")
        try:
            with fitz.open(stream=content, filetype="pdf") as pdf:
                pages = pdf.page_count
        except Exception as exc:
            raise ValueError("SOURCE_PDF_INVALID") from exc
        if page > pages:
            raise ValueError("INVALID_SOURCE_PAGE")
        return SourcePDF(content, version, pages)
