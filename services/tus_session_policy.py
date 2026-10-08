"""Business policy for an authenticated tus gateway; not an HTTP auth layer."""

from datetime import datetime, timezone

from core.upload_session_contracts import UploadState


class TusSessionPolicy:
    def __init__(self, repository, *, clock=lambda: datetime.now(timezone.utc)):
        self.repository = repository
        self.clock = clock

    def authorize(self, upload_id, tenant_id, user_id):
        # IDs are checked before any transport filesystem access. Identity must
        # originate in the existing JWT dependency, never upload metadata.
        if not isinstance(upload_id, str) or len(upload_id) != 32 or any(
            char not in "0123456789abcdef" for char in upload_id
        ):
            raise PermissionError("UPLOAD_NOT_FOUND")
        session = self.repository.get(upload_id, tenant_id, user_id)
        if session.protocol != "tus":
            raise ValueError("TUS_SESSION_REQUIRED")
        if session.state in {UploadState.FAILED, UploadState.EXPIRED}:
            raise ValueError("UPLOAD_TERMINAL_STATE")
        if self.clock() >= session.expires_at:
            raise ValueError("UPLOAD_EXPIRED")
        return session

    def pre_create(self, upload_id, tenant_id, user_id, *, size, deferred=False, partial=False, final=False):
        session = self.authorize(upload_id, tenant_id, user_id)
        if session.state != UploadState.CREATED:
            raise ValueError("TUS_CREATION_ALREADY_BOUND")
        if type(size) is not int or size != session.expected_size or deferred is not False:
            raise ValueError("TUS_LENGTH_MISMATCH")
        if partial is not False or final is not False:
            raise ValueError("TUS_CONCATENATION_NOT_ALLOWED")
        # Official tusd v2 hook response. Client metadata is deliberately not
        # copied; server-owned UUID is shared by transport and business session.
        return {"ChangeFileInfo": {"ID": session.upload_id, "MetaData": {
            "upload_id": session.upload_id, "filename": session.filename,
        }}}

    def pre_finish(self, upload_id, tenant_id, user_id, *, size, offset):
        session = self.authorize(upload_id, tenant_id, user_id)
        if type(size) is not int or type(offset) is not int or size != session.expected_size or offset != size:
            raise ValueError("TUS_INCOMPLETE_CONTENT")
        # Completion only permits checksum handoff; it never sets READY or
        # bypasses receive/finalize/quality gates.
        return {}

    def resource_created(self, upload_id, tenant_id, user_id):
        self.authorize(upload_id, tenant_id, user_id)
        return self.repository.transport_created(upload_id, tenant_id, user_id, self.clock())

    def resource_progress(self, upload_id, tenant_id, user_id, *, offset, length=None):
        session = self.authorize(upload_id, tenant_id, user_id)
        if (not isinstance(offset, str) or not offset.isascii() or not offset.isdecimal()
                or len(offset) > 20):
            raise ValueError("TUS_OFFSET_INVALID")
        if length is not None and length != str(session.expected_size):
            raise ValueError("TUS_LENGTH_MISMATCH")
        return self.repository.transport_progress(upload_id, tenant_id, user_id,
            offset=int(offset), now=self.clock())
