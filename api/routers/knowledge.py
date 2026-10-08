import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.schemas.request import CompanyDocumentDiscoveryRequest
from auth.dependencies import get_current_user
from core.usage_events import ResourceType, UsageEvent
from document_formats import validate_document_payload
from models.document import Document
from models.task import Task, TaskStatus, TaskType
from models.user import User
from services.filing_discovery import FilingDiscoveryError, FilingNotFound, discover_latest_company_filing
from services.plan_service import can_upload, get_document_quota
from services.usage_service import record_usage
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import get_db
from tasks.broker import get_broker
from tasks.repository import TaskRepository

router = APIRouter(tags=["Knowledge"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "storage/uploads"))


@router.get("/knowledge/quota")
def document_quota(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_document_quota(db, current_user.tenant_id)


def _document_item(
    document: Document,
    *,
    source_url: str | None = None,
    source_type: str | None = None,
) -> dict[str, object]:
    # Knowledge documents and their quota are workspace-scoped.  Once a row
    # has passed the tenant filter in ``knowledge_overview``, every member of
    # that workspace may manage it, including documents uploaded by an older
    # test account or by a legacy import with no owner.
    can_delete = True
    return {
        "id": document.id,
        "filename": document.filename,
        "company": document.company,
        "period": document.period,
        "status": document.status,
        "chunk_count": document.indexed_chunk_count or 0,
        "byte_size": document.byte_size,
        "content_sha256": document.content_sha256,
        "uploaded_at": document.created_at,
        "can_delete": can_delete,
        "source_url": source_url,
        "source_type": source_type,
    }


def _document_tasks(
    db: Session,
    *,
    tenant_id: int,
    document_id: int,
) -> list[Task]:
    candidates = (
        db.query(Task)
        .filter(
            Task.tenant_id == tenant_id,
            Task.task_type == TaskType.PROCESS_DOCUMENT.value,
        )
        .all()
    )
    return [
        task
        for task in candidates
        if task.payload.get("document_id") == document_id
    ]


def _document_source_metadata(
    db: Session,
    *,
    tenant_id: int,
    document_id: int,
) -> dict[str, str | None]:
    for task in reversed(_document_tasks(db, tenant_id=tenant_id, document_id=document_id)):
        source_url = task.payload.get("source_url")
        if isinstance(source_url, str) and source_url:
            source_type = task.payload.get("source_type")
            return {
                "source_url": source_url,
                "source_type": source_type if isinstance(source_type, str) else None,
            }
    return {"source_url": None, "source_type": None}


def _upload_directories(*, tenant_id: int, document_id: int) -> list[Path]:
    """Resolve only the upload directories owned by one document.

    The directory layout is ``UPLOAD_DIR/<tenant>/<document-id>-<uuid>``.
    Every resolved target must remain an immediate child of the tenant root,
    preventing a malformed task path or symlink from widening deletion scope.
    """

    tenant_root = (UPLOAD_DIR / str(tenant_id)).resolve()
    if not tenant_root.is_dir():
        return []

    directories: list[Path] = []
    for candidate in tenant_root.glob(f"{document_id}-*"):
        resolved = candidate.resolve()
        if (
            candidate.is_dir()
            and not candidate.is_symlink()
            and resolved.parent == tenant_root
            and resolved.name.startswith(f"{document_id}-")
        ):
            directories.append(resolved)
    return sorted(directories)


def _stage_upload_directories(
    directories: list[Path],
    *,
    tenant_id: int,
    document_id: int,
) -> list[tuple[Path, Path]]:
    tenant_root = (UPLOAD_DIR / str(tenant_id)).resolve()
    staged: list[tuple[Path, Path]] = []
    try:
        for original in directories:
            staged_path = tenant_root / (
                f".deleting-{document_id}-{uuid.uuid4().hex}"
            )
            original.rename(staged_path)
            staged.append((original, staged_path))
    except OSError:
        _restore_upload_directories(staged)
        raise
    return staged


def _restore_upload_directories(staged: list[tuple[Path, Path]]) -> None:
    for original, staged_path in reversed(staged):
        if staged_path.exists() and not original.exists():
            staged_path.rename(original)


def _remove_staged_upload_directories(
    staged: list[tuple[Path, Path]],
    *,
    tenant_id: int,
) -> None:
    tenant_root = (UPLOAD_DIR / str(tenant_id)).resolve()
    for _, staged_path in staged:
        resolved = staged_path.resolve()
        if (
            staged_path.is_dir()
            and not staged_path.is_symlink()
            and resolved.parent == tenant_root
            and resolved.name.startswith(".deleting-")
        ):
            shutil.rmtree(resolved)


@router.get("/knowledge")
def knowledge_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    docs = (
        db.query(Document)
        .filter(Document.tenant_id == current_user.tenant_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .all()
    )
    return {
        # Keep the legacy filename list while clients transition to stable
        # document IDs in ``items``.
        "documents": [document.filename for document in docs],
        "items": [
            _document_item(
                document,
                **_document_source_metadata(
                    db,
                    tenant_id=current_user.tenant_id,
                    document_id=document.id,
                ),
            )
            for document in docs
        ],
        "document_count": len(docs),
        "companies": sorted(
            {document.company for document in docs if document.company}
        ),
    }


@router.post("/knowledge/discover")
def discover_company_filing(
    request: CompanyDocumentDiscoveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a trusted SEC filing or audited A-share annual report."""

    company_query = request.company.strip()
    existing = (
        db.query(Document)
        .filter(
            Document.tenant_id == current_user.tenant_id,
            Document.company.ilike(f"%{company_query}%"),
            Document.status != "failed",
        )
        .order_by(Document.created_at.desc(), Document.id.desc())
        .first()
    )
    if existing is not None:
        source_metadata = _document_source_metadata(
            db,
            tenant_id=current_user.tenant_id,
            document_id=existing.id,
        )
        return {
            "status": "already_present",
            "document_id": existing.id,
            "filename": existing.filename,
            "company": existing.company,
            "period": existing.period,
            **source_metadata,
        }
    if not can_upload(db, current_user.tenant_id):
        raise HTTPException(status_code=429, detail="Upload limit exceeded. Upgrade your plan.")

    try:
        filing = discover_latest_company_filing(company_query)
    except FilingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FilingDiscoveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    content_sha256 = hashlib.sha256(filing.content).hexdigest()
    duplicate = (
        db.query(Document)
        .filter(
            Document.tenant_id == current_user.tenant_id,
            Document.content_sha256 == content_sha256,
        )
        .first()
    )
    if duplicate is not None:
        return {
            "status": "already_present",
            "document_id": duplicate.id,
            "filename": duplicate.filename,
            "company": duplicate.company,
            "period": duplicate.period,
            "source_url": filing.source_url,
            "source_type": filing.source_type,
        }

    validate_document_payload(filing.filename, filing.content)
    document = Document(
        filename=filing.filename,
        company=filing.company,
        period=filing.report_date or filing.filing_date,
        status="processing",
        tenant_id=current_user.tenant_id,
        content_sha256=content_sha256,
        byte_size=len(filing.content),
        uploaded_by_user_id=current_user.id,
        indexed_chunk_count=0,
    )
    db.add(document)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This public filing already exists in your workspace.") from exc

    upload_directory = (
        UPLOAD_DIR / str(current_user.tenant_id) / f"{document.id}-{uuid.uuid4().hex}"
    )
    file_path = upload_directory / filing.filename
    try:
        upload_directory.mkdir(parents=True, exist_ok=False)
        file_path.write_bytes(filing.content)
        task = TaskRepository(db).create_task(
            task_type=TaskType.PROCESS_DOCUMENT,
            payload={
                "file_path": str(file_path),
                "document_id": document.id,
                "content_sha256": content_sha256,
                "source_url": filing.source_url,
                "source_type": filing.source_type,
                "source_company": filing.company,
                "source_form": filing.form,
                "source_filing_date": filing.filing_date,
                "source_report_date": filing.report_date,
                "source_stock_code": filing.stock_code,
                "source_exchange": filing.exchange,
                "source_report_type": filing.report_type,
                "source_report_year": filing.report_year,
                "source_audited": filing.audited,
            },
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
    except OSError as exc:
        db.rollback()
        shutil.rmtree(upload_directory, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Unable to persist public filing") from exc

    broker = get_broker()
    if broker.enabled:
        broker.publish_task(task.public_id, current_user.tenant_id, task.task_type)
    record_usage(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        event_type=UsageEvent.DOCUMENT_UPLOAD,
        resource_type=ResourceType.DOCUMENT,
        quantity=1,
        metadata={
            "document_id": document.id,
            "task_id": task.public_id,
            "source_type": filing.source_type,
            "source_form": filing.form,
            "source_report_year": filing.report_year,
            "source_audited": filing.audited,
        },
        db=db,
    )
    return {
        "status": "downloaded",
        "message": (
            "Official A-share annual report with an audit report section downloaded and queued for indexing."
            if filing.source_type == "cninfo"
            else "SEC filing downloaded and queued for indexing."
        ),
        "filename": filing.filename,
        "document_id": document.id,
        "task_id": task.public_id,
        "company": filing.company,
        "period": filing.report_date or filing.filing_date,
        "source_url": filing.source_url,
        "source_type": filing.source_type,
        "source_form": filing.form,
        "source_stock_code": filing.stock_code,
        "source_exchange": filing.exchange,
        "source_report_type": filing.report_type,
        "source_report_year": filing.report_year,
        "source_audited": filing.audited,
    }


@router.get("/knowledge/statistics")
def knowledge_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    docs = (
        db.query(Document)
        .filter(Document.tenant_id == current_user.tenant_id)
        .all()
    )
    chunk_count = sum(document.indexed_chunk_count or 0 for document in docs)
    return {
        "documents": len(docs),
        "companies": len(
            {document.company for document in docs if document.company}
        ),
        "chunks": chunk_count,
        "embeddings": chunk_count,
    }


@router.delete("/knowledge/{document_id}")
def delete_knowledge_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if document is None:
        # The same response is used for absent and foreign-tenant IDs.
        raise HTTPException(status_code=404, detail="Document not found")

    document_tasks = _document_tasks(
        db,
        tenant_id=current_user.tenant_id,
        document_id=document.id,
    )
    has_active_task = any(
        task.status
        in {
            TaskStatus.PENDING.value,
            TaskStatus.RUNNING.value,
        }
        for task in document_tasks
    )
    if document.status == "processing" or has_active_task:
        raise HTTPException(
            status_code=409,
            detail="Document is still processing and cannot be deleted.",
        )

    directories = _upload_directories(
        tenant_id=current_user.tenant_id,
        document_id=document.id,
    )
    try:
        staged = _stage_upload_directories(
            directories,
            tenant_id=current_user.tenant_id,
            document_id=document.id,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to prepare document storage for deletion.",
        ) from exc

    vector_document_id = (
        f"tenant_{current_user.tenant_id}_document_{document.id}"
    )
    try:
        with ChromaEmbeddingStore() as store:
            store.delete_document(
                vector_document_id,
                tenant_id=current_user.tenant_id,
            )
    except Exception as exc:
        try:
            _restore_upload_directories(staged)
        except OSError:
            logger.exception(
                "Failed to restore upload directory after vector delete error"
            )
        raise HTTPException(
            status_code=503,
            detail="Unable to delete document vectors.",
        ) from exc

    try:
        db.delete(document)
        db.commit()
    except Exception:
        db.rollback()
        try:
            _restore_upload_directories(staged)
        except OSError:
            logger.exception(
                "Failed to restore upload directory after database error"
            )
        raise

    try:
        _remove_staged_upload_directories(
            staged,
            tenant_id=current_user.tenant_id,
        )
    except OSError:
        logger.exception(
            "Document metadata was deleted but staged file cleanup failed",
            extra={
                "tenant_id": current_user.tenant_id,
                "document_id": document_id,
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Document was deleted but storage cleanup is pending.",
        )

    return {
        "deleted": True,
        "document_id": document_id,
    }
