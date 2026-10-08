"""Isolated SQLite lifecycle pilot. Never imports production DB or queues.

Registrations are pilot records, NOT production Document/Task instances.
No resumable byte transport is implemented here.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from core.upload_session_contracts import UploadSessionContract, UploadState


def _encode(value: UploadSessionContract) -> str:
    data = asdict(value)
    data["created_at"] = value.created_at.isoformat()
    data["expires_at"] = value.expires_at.isoformat()
    data["updated_at"] = value.updated_at.isoformat()
    return json.dumps(data)


def _decode(payload: str) -> UploadSessionContract:
    data = json.loads(payload)
    for field in ("created_at", "expires_at"):
        data[field] = datetime.fromisoformat(data[field])
    if data.get("updated_at") is not None:
        data["updated_at"] = datetime.fromisoformat(data["updated_at"])
    data["state"] = UploadState(data["state"])
    return UploadSessionContract(**data)


class SQLiteUploadPilot:
    def __init__(self, path: Path):
        self.path = path.resolve()
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS pilot_uploads (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS pilot_registrations (
                upload_id TEXT PRIMARY KEY, document_id TEXT UNIQUE NOT NULL,
                job_id TEXT UNIQUE NOT NULL, event_id TEXT UNIQUE NOT NULL,
                document_state TEXT NOT NULL CHECK(document_state='REGISTERED'))""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def create(self, value: UploadSessionContract):
        if value.state != UploadState.CREATED:
            raise ValueError("CREATE_REQUIRES_INITIAL_STATE")
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO pilot_uploads VALUES (?, ?)", (value.upload_id, _encode(value)))

    @staticmethod
    def _load(db, upload_id, tenant_id, user_id):
        row = db.execute("SELECT payload FROM pilot_uploads WHERE id=?", (upload_id,)).fetchone()
        if row is None:
            raise PermissionError("UPLOAD_NOT_FOUND")
        value = _decode(row[0])
        value.authorize(tenant_id, user_id)
        return value

    def get(self, upload_id, tenant_id, user_id):
        with closing(self._connect()) as db:
            return self._load(db, upload_id, tenant_id, user_id)

    def _change(self, upload_id, tenant_id, user_id, change):
        # SQLite-only serialization; PostgreSQL needs its own row-lock tests.
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            value = self._load(db, upload_id, tenant_id, user_id)
            result = change(db, value)
            db.execute("UPDATE pilot_uploads SET payload=? WHERE id=?", (_encode(result), upload_id))
            return result

    def transition(self, upload_id, tenant_id, user_id, state, now):
        return self._change(upload_id, tenant_id, user_id, lambda db, value: value.transition(state, now))

    def verify_bytes(self, upload_id, tenant_id, user_id, content: bytes, now):
        # Test-pilot API only: production must stream/hash storage rather than load a large PDF.
        return self._change(upload_id, tenant_id, user_id, lambda db, value: value.verify(
            size=len(content), sha256=hashlib.sha256(content).hexdigest(),
            pdf_magic_valid=content.startswith(b"%PDF-"), now=now))

    def finalize(self, upload_id, tenant_id, user_id, now):
        def register(db, value):
            if value.state == UploadState.FINALIZED:
                return value
            result = value.finalize(document_id=uuid4().hex, ingestion_job_id=uuid4().hex, now=now)
            db.execute("INSERT INTO pilot_registrations VALUES (?, ?, ?, ?, 'REGISTERED')",
                       (upload_id, result.document_id, result.ingestion_job_id, uuid4().hex))
            return result

        return self._change(upload_id, tenant_id, user_id, register)
