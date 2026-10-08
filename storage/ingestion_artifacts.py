"""Content-addressed isolated stage artifacts; no production index mutations."""

import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4


class IngestionArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, tenant_id: int, source_sha256: str, artifact_sha256: str):
        if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0:
            raise ValueError("INVALID_ARTIFACT_OWNER")
        if any(not re.fullmatch(r"[0-9a-f]{64}", value)
               for value in (source_sha256, artifact_sha256)):
            raise ValueError("INVALID_ARTIFACT_DIGEST")
        path = (self.root / str(tenant_id) / source_sha256 / artifact_sha256).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("ARTIFACT_PATH_ESCAPE")
        return path

    def put(self, tenant_id: int, source_sha256: str, content: bytes):
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(tenant_id, source_sha256, digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def read(self, tenant_id: int, source_sha256: str, artifact_sha256: str):
        content = self._path(tenant_id, source_sha256, artifact_sha256).read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact_sha256:
            raise ValueError("ARTIFACT_INTEGRITY_FAILURE")
        return content
