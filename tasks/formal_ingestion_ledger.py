"""Authoritative per-stage checkpoint execution, without experimental storage."""

import json
import re
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from core.ingestion_contracts import STAGES, StageLease, StageLeaseLost
from models.document import Document
from models.ingestion_persistence import TaskStageCheckpoint, UploadSession
from models.task import Task
from storage.core_index_evidence import CoreIndexEvidenceReader
from storage.ingestion_transactions import require_aware, serialize_sqlite, utc
from tasks.dispatch_lifecycle import close_terminal_obligation


class FormalIngestionLedger:
    def __init__(self, session_factory, *, artifact_store, max_attempts=3, lease_seconds=300):
        if not 1 <= max_attempts <= 10 or not 1 <= lease_seconds <= 3600:
            raise ValueError("INVALID_STAGE_BUDGET")
        self.session_factory, self.artifact_store = session_factory, artifact_store
        self.max_attempts, self.lease_seconds = max_attempts, lease_seconds

    @staticmethod
    def _load(session, task_id, *, lock=False):
        query = select(Task).where(Task.public_id == task_id)
        task = session.scalar(query.with_for_update() if lock else query)
        if task is None:
            raise PermissionError("INGESTION_NOT_FOUND")
        upload = session.scalar(select(UploadSession).where(UploadSession.task_id == task.id))
        doc = session.get(Document, upload.document_id) if upload else None
        if (
            upload is None
            or upload.status != "FINALIZED"
            or doc is None
            or upload.tenant_id != task.tenant_id
            or upload.user_id != task.user_id
            or doc.tenant_id != task.tenant_id
            or doc.uploaded_by_user_id != task.user_id
            or doc.content_sha256 != upload.verified_sha256
        ):
            raise ValueError("INGESTION_SOURCE_IDENTITY_CHANGED")
        query = select(TaskStageCheckpoint).where(TaskStageCheckpoint.task_id == task.id)
        rows = session.scalars(query.with_for_update() if lock else query).all()
        graph = {row.stage: row for row in rows}
        if set(graph) != set(STAGES) or any(
            row.document_id != doc.id or row.source_sha256 != doc.content_sha256 for row in rows
        ):
            raise ValueError("STAGE_CHECKPOINT_GRAPH_INVALID")
        return task, doc, graph

    def claim(self, task_id, now):
        require_aware(now)
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            task, doc, graph = self._load(session, task_id, lock=True)
            if doc.status in {"ready", "failed", "quarantined"}:
                return None
            row = next((graph[stage] for stage in STAGES if graph[stage].status != "complete"), None)
            if row is None or row.status in {"failed", "quarantined"}:
                return None
            if row.status == "leased" and utc(row.lease_expires_at) > now:
                return None
            if row.next_retry_at and utc(row.next_retry_at) > now:
                return None
            if row.attempt_count >= self.max_attempts:
                row.status, row.error_code = "failed", "STAGE_ATTEMPTS_EXHAUSTED"
                row.lease_token = row.lease_expires_at = None
                task.status, doc.status = "failed", "failed"
                close_terminal_obligation(task)
                return None
            row.attempt_count += 1
            row.status, row.lease_token = "leased", uuid4().hex
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.next_retry_at = None
            task.status, doc.status = "running", "processing"
            return StageLease(task.public_id, row.lease_token, row.stage, row.source_sha256, doc.id, task.tenant_id)

    @staticmethod
    def _current(task, doc, row, lease, now):
        return (
            row is not None
            and row.status == "leased"
            and row.lease_token == lease.token
            and row.lease_expires_at is not None
            and utc(row.lease_expires_at) > now
            and task.public_id == lease.task_id
            and task.tenant_id == lease.tenant_id
            and doc.id == lease.document_id
            and row.source_sha256 == lease.source_sha256
        )

    def finish(
        self,
        lease,
        *,
        now,
        artifact_id=None,
        artifact_sha256=None,
        quality_status=None,
        error_code=None,
        retryable=False,
    ):
        require_aware(now)
        with self.session_factory() as session, session.begin():
            serialize_sqlite(session)
            task, doc, graph = self._load(session, lease.task_id, lock=True)
            row = graph.get(lease.stage)
            if not self._current(task, doc, row, lease, now):
                return False
            if quality_status == "FAIL":
                if lease.stage != "QUALITY_CHECK":
                    raise ValueError("QUALITY_RESULT_WRONG_STAGE")
                row.status, row.quality_status, row.error_code = "quarantined", "FAIL", "QUALITY_HARD_FAILURE"
                task.status, doc.status = "failed", "quarantined"
                close_terminal_obligation(task)
            elif error_code:
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error_code):
                    raise ValueError("INVALID_ERROR_CODE")
                retry = retryable and row.attempt_count < self.max_attempts
                row.status, row.error_code = "pending" if retry else "failed", error_code
                row.next_retry_at = now + timedelta(seconds=min(60, 2**row.attempt_count)) if retry else None
                task.status, doc.status = ("pending", "processing") if retry else ("failed", "failed")
                if not retry:
                    close_terminal_obligation(task)
            else:
                if not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256 or "") or artifact_id != artifact_sha256:
                    raise ValueError("STAGE_ARTIFACT_REQUIRED")
                if lease.stage == "QUALITY_CHECK" and quality_status != "PASS":
                    raise ValueError("QUALITY_GATE_NOT_PASSED")
                self.artifact_store.read(lease.tenant_id, lease.source_sha256, artifact_sha256)
                if lease.stage == "INDEXING":
                    receipt = json.loads(
                        self.artifact_store.read(lease.tenant_id, lease.source_sha256, artifact_sha256)
                    )
                    CoreIndexEvidenceReader(self.artifact_store).load(
                        receipt,
                        tenant_id=lease.tenant_id,
                        document_id=lease.document_id,
                        source_sha256=lease.source_sha256,
                    )
                    if (
                        receipt["parse_artifact_sha256"] != graph["PARSING"].artifact_sha256
                        or receipt["quality_artifact_sha256"] != graph["QUALITY_CHECK"].artifact_sha256
                    ):
                        raise ValueError("INDEX_CHECKPOINT_DEPENDENCY_MISMATCH")
                row.artifact_id, row.artifact_sha256 = artifact_id, artifact_sha256
                row.status, row.completed_at, row.error_code = "complete", now, None
                row.quality_status = quality_status
                task.status = "pending"
                # Completing INDEXING is deliberately NOT a READY promotion.
            row.lease_token = row.lease_expires_at = None
            return True

    def prior_artifact(self, lease, stage, *, now):
        require_aware(now)
        with self.session_factory() as session:
            task, doc, graph = self._load(session, lease.task_id)
            if not self._current(task, doc, graph.get(lease.stage), lease, now):
                raise StageLeaseLost("STAGE_LEASE_NOT_CURRENT")
            if stage not in STAGES or STAGES.index(stage) >= STAGES.index(lease.stage):
                raise ValueError("STAGE_DEPENDENCY_INVALID")
            prior = graph[stage]
            if prior.status != "complete":
                raise ValueError("STAGE_CHECKPOINT_MISSING")
            self.artifact_store.read(lease.tenant_id, lease.source_sha256, prior.artifact_sha256)
            return prior.artifact_sha256

    def status(self, task_id, tenant_id, user_id):
        with self.session_factory() as session:
            # Authorize before loading/checking another owner's artifact graph.
            if (
                session.scalar(
                    select(Task.id).where(
                        Task.public_id == task_id, Task.tenant_id == tenant_id, Task.user_id == user_id
                    )
                )
                is None
            ):
                raise PermissionError("INGESTION_NOT_FOUND")
            task, doc, graph = self._load(session, task_id)
            current = next((graph[stage] for stage in STAGES if graph[stage].status != "complete"), None)
            completed = [stage for stage in STAGES if graph[stage].status == "complete"]
            status = (
                doc.status
                if doc.status in {"ready", "failed", "quarantined"}
                else (current.status if current else "pending")
            )
            return {
                "status": status,
                "stage": current.stage if current else "READY",
                "quality_status": graph["QUALITY_CHECK"].quality_status or "UNKNOWN",
                "attempt": current.attempt_count if current else 0,
                "error_code": current.error_code if current else None,
                "retryable": bool(current and current.status == "pending" and current.next_retry_at),
                "completed_stages": completed,
            }

    def ready_index(self, task_id, tenant_id, user_id):
        """Scoped formal read port; never promotes or repairs an index."""
        import json

        from storage.core_index_evidence import CoreIndexEvidenceReader

        if self.status(task_id, tenant_id, user_id)["status"] != "ready":
            raise ValueError("DOCUMENT_NOT_READY")
        with self.session_factory() as session:
            task, document, graph = self._load(session, task_id)
            if task.tenant_id != tenant_id or task.user_id != user_id:
                raise PermissionError("INGESTION_NOT_FOUND")
            receipt = json.loads(self.artifact_store.read(
                tenant_id, document.content_sha256, graph["INDEXING"].artifact_sha256))
            CoreIndexEvidenceReader(self.artifact_store).load(
                receipt, tenant_id=tenant_id, document_id=document.id, source_sha256=document.content_sha256)
            return receipt

    def ready_document_metadata(self, task_id, tenant_id, user_id):
        manifest = self.ready_index(task_id, tenant_id, user_id)
        with self.session_factory() as session:
            task, document, _ = self._load(session, task_id)
            if task.tenant_id != tenant_id or task.user_id != user_id:
                raise PermissionError("INGESTION_NOT_FOUND")
            if document.id != manifest["document_id"] or document.content_sha256 != manifest["source_sha256"]:
                raise ValueError("READY_DOCUMENT_SOURCE_CHANGED")
            return {"document_id": document.id, "source_sha256": document.content_sha256,
                    "filename": document.filename}

    def ready_facts(self, task_id, tenant_id, user_id):
        """Read verified artifacts through formal checkpoints, never pilot tables."""
        import json

        manifest = self.ready_index(task_id, tenant_id, user_id)

        def receipts():
            with self.session_factory() as session:
                task, document, graph = self._load(session, task_id)
                if task.tenant_id != tenant_id or task.user_id != user_id:
                    raise PermissionError("INGESTION_NOT_FOUND")
                if (document.id, document.content_sha256) != (
                        manifest["document_id"], manifest["source_sha256"]):
                    raise ValueError("FACT_RECEIPT_SOURCE_CHANGED")
                stages = ("PARSING", "QUALITY_CHECK", "BUILDING_FACTS")
                if any(graph[stage].status != "complete" or not graph[stage].artifact_sha256 for stage in stages):
                    raise ValueError("READY_FACT_CHECKPOINT_REQUIRED")
                return {stage: graph[stage].artifact_sha256 for stage in stages}

        graph = receipts()
        payload = json.loads(self.artifact_store.read(
            tenant_id, manifest["source_sha256"], graph["BUILDING_FACTS"]))
        if (not isinstance(payload, dict) or payload.get("schema") != "financial-ingestion-facts.v1"
                or type(payload.get("tenant_id")) is not int or payload["tenant_id"] != tenant_id
                or type(payload.get("document_id")) is not int
                or payload["document_id"] != manifest["document_id"]
                or payload.get("source_sha256") != manifest["source_sha256"]
                or payload.get("parse_artifact_sha256") != graph["PARSING"]
                or payload.get("quality_artifact_sha256") != graph["QUALITY_CHECK"]
                or not isinstance(payload.get("facts"), list)):
            raise ValueError("READY_FACT_ARTIFACT_BINDING_INVALID")
        if self.ready_index(task_id, tenant_id, user_id) != manifest or receipts() != graph:
            raise ValueError("READY_FACT_RECEIPT_GRAPH_CHANGED")
        if not payload["facts"]:
            return payload
        from services.financial_fact_provenance import bind_table_rows
        from tasks.ingestion_fact_stage import _calendar

        parsed = json.loads(self.artifact_store.read(tenant_id, manifest["source_sha256"], graph["PARSING"]))
        bound = bind_table_rows(payload, parsed, context=_calendar(parsed["chunks"]))
        if self.ready_index(task_id, tenant_id, user_id) != manifest or receipts() != graph:
            raise ValueError("READY_FACT_RECEIPT_GRAPH_CHANGED")
        return bound
