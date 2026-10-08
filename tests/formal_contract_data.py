"""Neutral upload inputs; transitions delegate to the production contract."""

from datetime import datetime, timedelta, timezone

from core.upload_session_contracts import UploadSessionContract, UploadState

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
HASH = "a" * 64


def session():
    return UploadSessionContract(
        "upload-1", 1, 2, "report.pdf", "application/pdf", 100, HASH,
        "legacy_multipart", NOW, NOW + timedelta(hours=1),
    )


def verifying():
    value = session()
    for state in (UploadState.UPLOADING, UploadState.UPLOADED, UploadState.VERIFYING):
        value = value.transition(state, NOW)
    return value
