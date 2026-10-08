"""Read-only formal ownership/dispatch acceptance, independent of transport count.

HARNESS_FIX_ONLY: documents are owned by uploaded_by_user_id, not user_id.
An observed terminal execution may originate from DB polling or broker delivery.
Redis message counts are telemetry, never proof of exactly-once business execution.
"""

from sqlalchemy import select

from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint, UploadSession
from models.task import Task
from tasks.dispatch_lifecycle import dispatchable_task_predicate


def verify_hybrid_retrieval(evidence, *, tenant_id, document_id, source_sha256, page_count):
    """Validate retrieval evidence only, after the official READY ownership check.

    This is deliberately not Narrative issuer/period/synthesis acceptance. Empty
    issuer metadata remains a separate Narrative rejection, never a promoted fact.
    """
    if not evidence or type(page_count) is not int or page_count < 1:
        raise ValueError("CANARY_HYBRID_EVIDENCE_REQUIRED")
    for item in evidence:
        payload = item.payload
        provenance = payload.get("provenance", {})
        page = payload.get("page")
        if (
            item.document_id != str(document_id)
            or provenance.get("tenant_id") != tenant_id
            or provenance.get("content_sha256") != source_sha256
            or provenance.get("document_version") != source_sha256
            or payload.get("retriever") != "HYBRID"
            or provenance.get("retrieval_component") != "hybrid_bm25_vector_rrf"
            or type(page) is not int or not 1 <= page <= page_count
        ):
            raise ValueError("CANARY_HYBRID_SOURCE_BINDING_INVALID")
    return {
        "status": "PASS", "scope": "RETRIEVAL_SOURCE_BINDING_ONLY",
        "component": "hybrid_bm25_vector_rrf", "evidence_count": len(evidence),
        "pages": [item.payload["page"] for item in evidence],
        "narrative_answer_accepted": False,
    }


def verify_formal_canary(session, *, task_id, tenant_id, user_id, source_sha256, now):
    """SELECT-only validation; does not claim, ACK, enqueue, or reconcile state."""
    row = session.execute(
        select(Task, UploadSession, Document)
        .join(UploadSession, UploadSession.task_id == Task.id)
        .join(Document, Document.id == UploadSession.document_id)
        .where(
            Task.public_id == task_id,
            Task.tenant_id == tenant_id,
            Task.user_id == user_id,
            UploadSession.tenant_id == tenant_id,
            UploadSession.user_id == user_id,
            Document.tenant_id == tenant_id,
            Document.uploaded_by_user_id == user_id,
        )
    ).one_or_none()
    if row is None:
        raise PermissionError("CANARY_OWNERSHIP_NOT_ESTABLISHED")
    task, upload, document = row
    if not (
        upload.status == "FINALIZED"
        and upload.verified_sha256 == source_sha256 == document.content_sha256
        and task.status == "success" and document.status == "ready"
    ):
        raise ValueError("CANARY_TERMINAL_SOURCE_BINDING_INVALID")
    if (
        task.dispatch_state not in {"none", "delivered", "failed"}
        or task.dispatch_lease_token is not None
        or task.dispatch_lease_expires_at is not None
        or task.dispatch_next_attempt_at is not None
    ):
        raise ValueError("CANARY_DISPATCH_NOT_CLOSED")
    eligible = session.scalar(
        select(Task.id).where(Task.id == task.id, dispatchable_task_predicate())
    ) is not None
    if eligible:
        raise ValueError("CANARY_TERMINAL_TASK_DISPATCHABLE")
    checkpoints = session.scalars(
        select(TaskStageCheckpoint).where(TaskStageCheckpoint.task_id == task.id)
        .order_by(TaskStageCheckpoint.checkpoint_id)
    ).all()
    if (
        len(checkpoints) != 5 or len({row.stage for row in checkpoints}) != 5
        or any(row.status != "complete" or row.source_sha256 != source_sha256
               or not row.artifact_sha256 or row.completed_at is None for row in checkpoints)
    ):
        raise ValueError("CANARY_CHECKPOINTS_NOT_COMPLETE")
    return {
        "status": "PASS", "document_id": document.id, "task_id": task.id,
        "ownership_authority": "tenant_id+uploaded_by_user_id+finalized_upload+task",
        "dispatch_state": task.dispatch_state, "dispatch_attempt_count": task.dispatch_attempt_count,
        "task_retry_count": task.retry_count, "terminal_dispatch_eligible": False,
        "transport_authority": "BROKER_OR_DB_POLL", "fixed_redis_delivery_count_required": False,
        "checkpoint_count": len(checkpoints), "observed_at": now.isoformat(),
    }
