"""Formal upload repository; transactional binding to canonical Document/Task."""

from uuid import uuid4

from sqlalchemy import select

from core.ingestion_contracts import STAGES
from core.upload_session_contracts import UploadSessionContract, UploadState
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint, UploadSession
from models.task import Task, TaskStatus, TaskType
from models.user import User
from storage.ingestion_transactions import serialize_sqlite, utc


class UploadSessionRepository:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def finalized_for_owner(self, tenant_id, user_id, *, offset=0, limit=20):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("INVALID_UPLOAD_PAGE")
        with self.session_factory() as session:
            self._owner(session, tenant_id, user_id)
            rows = session.scalars(select(UploadSession).where(
                UploadSession.tenant_id == tenant_id, UploadSession.user_id == user_id,
                UploadSession.status == "FINALIZED").order_by(UploadSession.created_at, UploadSession.upload_id)
                .offset(offset).limit(limit + 1)).all()
            return [self._value(session, row) for row in rows[:limit]], offset + limit if len(rows) > limit else None

    @staticmethod
    def _owner(session, tenant_id, user_id):
        if session.scalar(select(User.id).where(User.id == user_id, User.tenant_id == tenant_id)) is None:
            raise PermissionError("UPLOAD_NOT_FOUND")

    @staticmethod
    def _row(session, upload_id, tenant_id, user_id, *, lock=False):
        query = select(UploadSession).where(
            UploadSession.upload_id == upload_id, UploadSession.tenant_id == tenant_id, UploadSession.user_id == user_id
        )
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise PermissionError("UPLOAD_NOT_FOUND")
        return row

    @staticmethod
    def _value(session, row):
        task = session.get(Task, row.task_id) if row.task_id is not None else None
        return UploadSessionContract(
            upload_id=row.upload_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            filename=row.filename,
            mime_type=row.mime_type,
            expected_size=row.expected_size,
            expected_sha256=row.expected_sha256,
            protocol=row.protocol,
            created_at=utc(row.created_at),
            expires_at=utc(row.expires_at),
            state=UploadState(row.status),
            document_id=str(row.document_id) if row.document_id is not None else None,
            ingestion_job_id=task.public_id if task else None,
            verified_sha256=row.verified_sha256,
            bytes_received=row.received_size,
            updated_at=utc(row.updated_at),
        )

    @staticmethod
    def _write(row, value):
        row.status, row.received_size = value.state.value, value.bytes_received
        row.verified_sha256, row.updated_at = value.verified_sha256, value.updated_at
        if value.state == UploadState.VERIFIED and row.verified_at is None:
            row.verified_at = value.updated_at

    def create(self, value):
        if value.state != UploadState.CREATED:
            raise ValueError("CREATE_REQUIRES_INITIAL_STATE")
        with self.session_factory() as session, session.begin():
            self._owner(session, value.tenant_id, value.user_id)
            session.add(
                UploadSession(
                    upload_id=value.upload_id,
                    tenant_id=value.tenant_id,
                    user_id=value.user_id,
                    filename=value.filename,
                    mime_type=value.mime_type,
                    protocol=value.protocol,
                    expected_size=value.expected_size,
                    received_size=value.bytes_received,
                    expected_sha256=value.expected_sha256,
                    status=value.state.value,
                    created_at=value.created_at,
                    updated_at=value.updated_at,
                    expires_at=value.expires_at,
                )
            )
        return value

    def get(self, upload_id, tenant_id, user_id):
        with self.session_factory() as session:
            self._owner(session, tenant_id, user_id)
            return self._value(session, self._row(session, upload_id, tenant_id, user_id))

    def stored_path(self, upload_id, tenant_id, user_id):
        with self.session_factory() as session:
            self._owner(session, tenant_id, user_id)
            return self._row(session, upload_id, tenant_id, user_id).storage_path

    def transport_created(self, upload_id, tenant_id, user_id, now):
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            self._owner(session, tenant_id, user_id)
            row = self._row(session, upload_id, tenant_id, user_id, lock=True)
            value = self._value(session, row)
            if value.protocol != "tus":
                raise ValueError("TUS_SESSION_REQUIRED")
            if value.state == UploadState.CREATED:
                value = value.transition(UploadState.UPLOADING, now)
                self._write(row, value)
            elif value.state != UploadState.UPLOADING:
                raise ValueError("TUS_RESOURCE_STATE_CONFLICT")
            return value

    def transport_progress(self, upload_id, tenant_id, user_id, *, offset, now):
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            self._owner(session, tenant_id, user_id)
            row = self._row(session, upload_id, tenant_id, user_id, lock=True)
            value = self._value(session, row)
            if value.state == UploadState.CREATED and offset == 0:
                return value
            if value.state in {UploadState.VERIFIED, UploadState.FINALIZED}:
                if type(offset) is not int or not 0 <= offset <= value.bytes_received:
                    raise ValueError("TRANSPORT_PROGRESS_STATE_CONFLICT")
                return value
            value = value.observe_transport_progress(offset=offset, now=now)
            self._write(row, value)
            return value

    def accept_content(self, upload_id, tenant_id, user_id, *, size, sha256, valid_pdf, storage_path, now):
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            self._owner(session, tenant_id, user_id)
            row = self._row(session, upload_id, tenant_id, user_id, lock=True)
            value = self._value(session, row)
            if value.state in {UploadState.VERIFIED, UploadState.FINALIZED}:
                if size != value.expected_size or sha256 != value.verified_sha256 or not valid_pdf:
                    raise ValueError("CONTENT_IDENTITY_CONFLICT")
                return value
            next_state = {
                UploadState.CREATED: UploadState.UPLOADING,
                UploadState.UPLOADING: UploadState.UPLOADED,
                UploadState.UPLOADED: UploadState.VERIFYING,
            }
            while value.state in next_state:
                value = value.transition(next_state[value.state], now)
            value = value.verify(size=size, sha256=sha256, pdf_magic_valid=valid_pdf, now=now)
            self._write(row, value)
            row.storage_path = storage_path if value.state == UploadState.VERIFIED else None
            return value

    def finalize(self, upload_id, tenant_id, user_id, now):
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            self._owner(session, tenant_id, user_id)
            row = self._row(session, upload_id, tenant_id, user_id, lock=True)
            value = self._value(session, row)
            if value.state == UploadState.FINALIZED:
                return value
            # Validate domain state BEFORE constructing canonical identities.
            if value.state != UploadState.VERIFIED or row.storage_path is None:
                raise ValueError("UNVERIFIED_CONTENT")
            if (
                session.scalar(
                    select(Document.id).where(
                        Document.tenant_id == tenant_id, Document.content_sha256 == value.expected_sha256
                    )
                )
                is not None
            ):
                raise ValueError("DOCUMENT_ALREADY_EXISTS_REUSE_POLICY_REQUIRED")
            document = Document(
                tenant_id=tenant_id,
                uploaded_by_user_id=user_id,
                filename=value.filename,
                status="registered",
                content_sha256=value.expected_sha256,
                byte_size=value.expected_size,
            )
            session.add(document)
            session.flush()
            task = Task(
                public_id=uuid4().hex,
                tenant_id=tenant_id,
                user_id=user_id,
                task_type=TaskType.FORMAL_READY_DOCUMENT.value,
                status=TaskStatus.PENDING.value,
                dispatch_state="pending",
            )
            task.payload = {
                "document_id": document.id,
                "upload_id": upload_id,
                "file_path": row.storage_path,
                "content_sha256": value.expected_sha256,
            }
            session.add(task)
            session.flush()
            result = value.finalize(document_id=str(document.id), ingestion_job_id=task.public_id, now=now)
            self._write(row, result)
            row.document_id, row.task_id, row.finalized_at = document.id, task.id, now
            for stage in STAGES:
                session.add(
                    TaskStageCheckpoint(
                        task_id=task.id, document_id=document.id, stage=stage, source_sha256=value.expected_sha256
                    )
                )
            return result
