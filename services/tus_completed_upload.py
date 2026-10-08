"""Trusted tusd filesystem handoff; callers never supply a filesystem path.

The authenticated pre-create gateway must assign the business upload UUID as
tusd's ID. This adapter does not replace that gateway or authorize public hooks.
"""

from pathlib import Path


class TusCompletedUpload:
    def __init__(self, service, tus_storage_root: Path):
        self.service = service
        self.root = tus_storage_root.resolve()

    def accept(self, upload_id: str, tenant_id: int, user_id: int):
        session = self.service.repository.get(upload_id, tenant_id, user_id)
        if session.protocol != "tus":
            raise ValueError("TUS_SESSION_REQUIRED")
        if len(upload_id) != 32 or any(char not in "0123456789abcdef" for char in upload_id):
            raise ValueError("INVALID_UPLOAD_ID")
        source = self.root / upload_id
        if source.is_symlink() or not source.resolve().is_relative_to(self.root) or not source.is_file():
            raise ValueError("TUS_CONTENT_MISSING")
        # Bounded read from one descriptor, not unbounded read_bytes(). Business
        # receive independently verifies PDF, exact length and SHA-256.
        with source.open("rb") as stream:
            content = stream.read(self.service.max_bytes + 1)
        if len(content) > self.service.max_bytes:
            raise ValueError("FILE_TOO_LARGE")
        return self.service.receive(upload_id, tenant_id, user_id, content)
