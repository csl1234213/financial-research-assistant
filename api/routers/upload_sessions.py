"""Opt-in router factory; intentionally not mounted into the production app yet."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from auth.dependencies import get_current_user
from models.user import User


class CreateUploadSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = "application/pdf"
    expected_size: int = Field(gt=0)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _view(value):
    return {"upload_id": value.upload_id, "status": value.state.value,
            "filename": value.filename, "expected_sha256": value.expected_sha256,
            "expected_size": value.expected_size, "protocol": value.protocol,
            "bytes_received": value.bytes_received, "updated_at": value.updated_at.isoformat(),
            "expires_at": value.expires_at.isoformat(), "document_id": value.document_id,
            "ingestion_job_id": value.ingestion_job_id}


def build_upload_session_router(service, *, ingestion_ledger=None, transport_protocol="legacy_multipart",
                                completed_transport=None):
    # Transport choice is deployment policy, never an arbitrary client field.
    if transport_protocol not in {"legacy_multipart", "tus"}:
        raise ValueError("UNSUPPORTED_UPLOAD_PROTOCOL")
    router = APIRouter(prefix="/upload-sessions", tags=["Upload Sessions"])

    def invoke(call):
        try:
            return _view(call())
        except PermissionError as exc:
            raise HTTPException(404, "UPLOAD_NOT_FOUND") from exc
        except ValueError as exc:
            code = str(exc)
            raise HTTPException(413 if code == "FILE_TOO_LARGE" else 409, code) from exc

    @router.post("", status_code=201)
    def create(body: CreateUploadSession, user: User = Depends(get_current_user)):
        return invoke(lambda: service.create(tenant_id=user.tenant_id, user_id=user.id,
            filename=body.filename, size=body.expected_size, sha256=body.expected_sha256,
            mime_type=body.mime_type, protocol=transport_protocol))

    @router.get("/ready-documents")
    def ready_documents(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50),
                        user: User = Depends(get_current_user)):
        if ingestion_ledger is None:
            raise HTTPException(503, "INGESTION_PROGRESS_NOT_CONFIGURED")
        try:
            records, next_offset = service.repository.finalized_for_owner(
                user.tenant_id, user.id, offset=offset, limit=limit)
            items = []
            documents = set()
            for value in records:
                try:
                    manifest = ingestion_ledger.ready_index(value.ingestion_job_id, user.tenant_id, user.id)
                    display = ingestion_ledger.ready_document_metadata(value.ingestion_job_id, user.tenant_id, user.id)
                except (ValueError, PermissionError):
                    continue  # Processing/quarantine is not a selectable READY report.
                if (str(manifest["document_id"]) != value.document_id
                        or manifest["source_sha256"] != value.expected_sha256
                        or display["document_id"] != manifest["document_id"]
                        or display["source_sha256"] != manifest["source_sha256"]):
                    raise ValueError("READY_REGISTRY_SOURCE_CHANGED")
                if manifest["document_id"] in documents:
                    continue
                documents.add(manifest["document_id"])
                items.append({"upload_id": value.upload_id, "ingestion_job_id": value.ingestion_job_id,
                    "document_id": manifest["document_id"], "filename": display["filename"],
                    "content_sha256": manifest["source_sha256"]})
            return {"schema": "ready-document-options.v1", "items": items, "next_offset": next_offset}
        except PermissionError as exc:
            raise HTTPException(404, "DOCUMENT_NOT_FOUND") from exc
        except ValueError as exc:
            raise HTTPException(409, "READY_DOCUMENT_LIST_NOT_AVAILABLE") from exc

    @router.get("/{upload_id}")
    def status(upload_id: str, user: User = Depends(get_current_user)):
        return invoke(lambda: service.repository.get(upload_id, user.tenant_id, user.id))

    @router.post("/{upload_id}/content")
    async def content(upload_id: str, file: UploadFile = File(...), user: User = Depends(get_current_user)):
        # Authorize before consuming a potentially large file.
        session = await run_in_threadpool(invoke, lambda: service.repository.get(upload_id, user.tenant_id, user.id))
        if session["protocol"] != "legacy_multipart":
            raise HTTPException(409, "STANDARD_TRANSPORT_REQUIRED")
        data = await file.read(service.max_bytes + 1)
        # PDF validation, checksum, disk writes and SQL transactions are blocking;
        # keep them off the async request loop while preserving error mapping.
        return await run_in_threadpool(invoke, lambda: service.receive(upload_id, user.tenant_id, user.id, data))

    @router.post("/{upload_id}/finalize")
    def finalize(upload_id: str, user: User = Depends(get_current_user)):
        return invoke(lambda: service.finalize(upload_id, user.tenant_id, user.id))

    @router.post("/{upload_id}/verify")
    def verify(upload_id: str, user: User = Depends(get_current_user)):
        session = invoke(lambda: service.repository.get(upload_id, user.tenant_id, user.id))
        if session["protocol"] != "tus":
            raise HTTPException(409, "TUS_SESSION_REQUIRED")
        if completed_transport is None:
            raise HTTPException(503, "TRANSPORT_VERIFICATION_NOT_CONFIGURED")
        # Only the injected adapter selects a trusted storage path. The client
        # supplies a business UUID, never a path or a claimed digest/offset.
        return invoke(lambda: completed_transport.accept(upload_id, user.tenant_id, user.id))

    @router.get("/{upload_id}/ingestion")
    def ingestion(upload_id: str, user: User = Depends(get_current_user)):
        value = invoke(lambda: service.repository.get(upload_id, user.tenant_id, user.id))
        if not value["ingestion_job_id"]:
            raise HTTPException(409, "INGESTION_NOT_REGISTERED")
        if ingestion_ledger is None:
            raise HTTPException(503, "INGESTION_PROGRESS_NOT_CONFIGURED")
        try:
            progress = ingestion_ledger.status(value["ingestion_job_id"], user.tenant_id, user.id)
        except PermissionError as exc:
            raise HTTPException(404, "INGESTION_NOT_FOUND") from exc
        return {"schema": "financial-ingestion-progress.v1", "upload_id": upload_id,
                "upload_status": value["status"], "document_id": value["document_id"],
                "ingestion_job_id": value["ingestion_job_id"], **progress}

    return router
