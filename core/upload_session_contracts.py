"""Offline upload lifecycle contracts, not a transport or persistence adapter."""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class UploadState(StrEnum):
    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


_NEXT = {
    UploadState.CREATED: {UploadState.UPLOADING, UploadState.FAILED, UploadState.EXPIRED},
    UploadState.UPLOADING: {UploadState.UPLOADED, UploadState.FAILED, UploadState.EXPIRED},
    UploadState.UPLOADED: {UploadState.VERIFYING, UploadState.FAILED, UploadState.EXPIRED},
    UploadState.VERIFYING: {UploadState.VERIFIED, UploadState.FAILED, UploadState.EXPIRED},
    UploadState.VERIFIED: {UploadState.FINALIZED, UploadState.FAILED, UploadState.EXPIRED},
}


@dataclass(frozen=True)
class UploadSessionContract:
    upload_id: str
    tenant_id: int
    user_id: int
    filename: str
    mime_type: str
    expected_size: int
    expected_sha256: str
    protocol: str
    created_at: datetime
    expires_at: datetime
    state: UploadState = UploadState.CREATED
    document_id: str | None = None
    ingestion_job_id: str | None = None
    verified_sha256: str | None = None
    bytes_received: int = 0
    updated_at: datetime | None = None

    def __post_init__(self):
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", self.created_at)
        if (type(self.bytes_received) is not int
                or not 0 <= self.bytes_received <= self.expected_size):
            raise ValueError("INVALID_RECEIVED_BYTES")
        if self.updated_at.tzinfo is None or self.updated_at < self.created_at:
            raise ValueError("INVALID_UPDATE_TIME")
        if not self.upload_id or self.tenant_id <= 0 or self.user_id <= 0:
            raise ValueError("INVALID_IDENTITY")
        if not self.filename or any(c in self.filename for c in '/\\\x00') or self.filename in {".", ".."}:
            raise ValueError("INVALID_FILENAME")
        if self.mime_type != "application/pdf" or self.expected_size <= 0:
            raise ValueError("INVALID_FILE_METADATA")
        if not re.fullmatch(r"[0-9a-f]{64}", self.expected_sha256):
            raise ValueError("INVALID_CHECKSUM")
        if self.protocol not in {"legacy_multipart", "tus", "s3_multipart"}:
            raise ValueError("UNSUPPORTED_PROTOCOL")
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None or self.expires_at <= self.created_at:
            raise ValueError("INVALID_EXPIRY")
        if self.state in {UploadState.VERIFIED, UploadState.FINALIZED}:
            if self.verified_sha256 != self.expected_sha256:
                raise ValueError("UNVERIFIED_CONTENT")
        if self.state == UploadState.FINALIZED and (not self.document_id or not self.ingestion_job_id):
            raise ValueError("UNBOUND_FINALIZE")

    def authorize(self, tenant_id: int, user_id: int):
        if (tenant_id, user_id) != (self.tenant_id, self.user_id):
            raise PermissionError("UPLOAD_NOT_FOUND")

    def transition(self, state: UploadState, now: datetime):
        if now.tzinfo is None:
            raise ValueError("TIMEZONE_REQUIRED")
        if state not in _NEXT.get(self.state, set()):
            raise ValueError("ILLEGAL_TRANSITION")
        if now >= self.expires_at and state != UploadState.EXPIRED:
            raise ValueError("UPLOAD_EXPIRED")
        if state in {UploadState.VERIFIED, UploadState.FINALIZED}:
            raise ValueError("USE_VERIFICATION_OR_FINALIZE")
        return replace(self, state=state, updated_at=max(now, self.updated_at))

    def observe_transport_progress(self, *, offset: int, now: datetime):
        """Trusted tusd receipt only; this is not a client progress assertion."""
        if type(offset) is not int or not 0 <= offset <= self.expected_size:
            raise ValueError("INVALID_RECEIVED_BYTES")
        if now.tzinfo is None or now < self.created_at:
            raise ValueError("INVALID_UPDATE_TIME")
        if self.protocol != "tus" or self.state != UploadState.UPLOADING:
            raise ValueError("TRANSPORT_PROGRESS_STATE_CONFLICT")
        if now >= self.expires_at:
            raise ValueError("UPLOAD_EXPIRED")
        # A concurrent older HEAD response cannot undo a newer PATCH receipt.
        return replace(self, bytes_received=max(offset, self.bytes_received),
                       updated_at=max(now, self.updated_at))

    def verify(self, *, size: int, sha256: str, pdf_magic_valid: bool, now: datetime):
        if self.state != UploadState.VERIFYING:
            raise ValueError("ILLEGAL_TRANSITION")
        if now.tzinfo is None or now >= self.expires_at:
            raise ValueError("UPLOAD_EXPIRED")
        if size != self.expected_size or sha256 != self.expected_sha256 or not pdf_magic_valid:
            return replace(self, state=UploadState.FAILED, updated_at=max(now, self.updated_at))
        return replace(self, state=UploadState.VERIFIED, verified_sha256=sha256,
                       bytes_received=size, updated_at=max(now, self.updated_at))

    def finalize(self, *, document_id: str, ingestion_job_id: str, now: datetime):
        if self.state == UploadState.FINALIZED:
            if (document_id, ingestion_job_id) != (self.document_id, self.ingestion_job_id):
                raise ValueError("FINALIZE_IDENTITY_CONFLICT")
            return self
        if self.state != UploadState.VERIFIED:
            raise ValueError("UNVERIFIED_CONTENT")
        if now.tzinfo is None or now >= self.expires_at:
            raise ValueError("UPLOAD_EXPIRED")
        return replace(self, state=UploadState.FINALIZED,
                       document_id=document_id, ingestion_job_id=ingestion_job_id,
                       updated_at=max(now, self.updated_at))
