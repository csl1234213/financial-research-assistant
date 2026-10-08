"""Session-aware complete-file transport. Standard resumable transport is a separate gate."""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from core.upload_session_contracts import UploadSessionContract, UploadState
from document_formats import validate_document_payload


class UploadSessionService:
    def __init__(self, repository, storage_root: Path, max_bytes=50 * 1024 * 1024):
        self.repository = repository
        self.storage_root = storage_root.resolve()
        self.max_bytes = max_bytes

    def create(self, *, tenant_id, user_id, filename, size, sha256, mime_type, protocol="legacy_multipart"):
        if size > self.max_bytes:
            raise ValueError("FILE_TOO_LARGE")
        if Path(filename).suffix.lower() != ".pdf":
            raise ValueError("PDF_REQUIRED")
        now = datetime.now(timezone.utc)
        return self.repository.create(UploadSessionContract(
            uuid4().hex, tenant_id, user_id, filename, mime_type, size, sha256,
            protocol, now, now + timedelta(hours=24)))

    def receive(self, upload_id, tenant_id, user_id, content: bytes):
        value = self.repository.get(upload_id, tenant_id, user_id)
        if value.state in {UploadState.FAILED, UploadState.EXPIRED}:
            raise ValueError("UPLOAD_TERMINAL_STATE")
        if len(content) > self.max_bytes:
            raise ValueError("FILE_TOO_LARGE")
        sha256 = hashlib.sha256(content).hexdigest()
        valid = True
        try:
            validate_document_payload(value.filename, content)
        except ValueError:
            valid = False
        identity_valid = valid and len(content) == value.expected_size and sha256 == value.expected_sha256
        # Immutable UUID-based internal storage; filename never selects filesystem paths.
        if len(upload_id) != 32 or any(c not in "0123456789abcdef" for c in upload_id):
            raise ValueError("INVALID_UPLOAD_ID")
        directory = self.storage_root / str(tenant_id) / str(user_id) / upload_id
        target = directory / "document.pdf"
        if not target.resolve().is_relative_to(self.storage_root):
            raise ValueError("INVALID_STORAGE_PATH")
        now = datetime.now(timezone.utc)
        if value.state in {UploadState.VERIFIED, UploadState.FINALIZED}:
            return self.repository.accept_content(upload_id, tenant_id, user_id, size=len(content),
                sha256=sha256, valid_pdf=valid, storage_path=str(target), now=now)
        if now >= value.expires_at:
            raise ValueError("UPLOAD_EXPIRED")
        if identity_valid:
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / f"{uuid4().hex}.tmp"
            try:
                with temporary.open("xb") as file:
                    file.write(content)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        result = self.repository.accept_content(upload_id, tenant_id, user_id, size=len(content),
            sha256=sha256, valid_pdf=valid, storage_path=str(target), now=now)
        if result.state == UploadState.FAILED:
            raise ValueError("CONTENT_VERIFICATION_FAILED")
        return result

    def finalize(self, upload_id, tenant_id, user_id):
        # No broker publish: transaction outbox will drive later durable dispatch.
        value = self.repository.get(upload_id, tenant_id, user_id)
        if value.state != UploadState.FINALIZED:
            if value.state != UploadState.VERIFIED:
                raise ValueError("UNVERIFIED_CONTENT")
            stored = self.repository.stored_path(upload_id, tenant_id, user_id)
            if not stored:
                raise ValueError("VERIFIED_FILE_MISSING")
            path = Path(stored).resolve()
            if not path.is_relative_to(self.storage_root) or not path.is_file():
                raise ValueError("VERIFIED_FILE_MISSING")
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as file:
                while block := file.read(1024 * 1024):
                    size += len(block)
                    if size > self.max_bytes:
                        raise ValueError("FILE_TOO_LARGE")
                    digest.update(block)
            if size != value.expected_size or digest.hexdigest() != value.verified_sha256:
                raise ValueError("STORED_CONTENT_CHANGED")
        return self.repository.finalize(upload_id, tenant_id, user_id, datetime.now(timezone.utc))
