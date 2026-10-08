"""The formal, transactional Document READY authority; no repair or Provider."""

import json

from core.ingestion_contracts import STAGES
from document_compatibility.models import DocumentState
from document_compatibility.serialization import compatibility_report_from_dict
from document_compatibility.tree_build_integrity import TreeBuildIntegrityEvaluator
from document_compatibility.tree_models import DocumentTree, TreeNode
from document_loader import CHUNKER_VERSION, PARSER_VERSION
from storage.core_index_evidence import CoreIndexEvidenceReader
from storage.ingestion_transactions import require_aware, serialize_sqlite
from tasks.dispatch_lifecycle import close_terminal_obligation
from tasks.formal_ingestion_ledger import FormalIngestionLedger


class ReadyPromotionService:
    def __init__(self, session_factory, *, artifact_store, vector_store):
        self.factory, self.artifacts, self.vectors = session_factory, artifact_store, vector_store

    def promote(self, task_id, *, tenant_id, user_id, now):
        require_aware(now)
        with self.factory() as session, session.begin():
            serialize_sqlite(session)
            # Same Task-first lock order as execution prevents promotion/worker deadlocks.
            from sqlalchemy import select

            from models.document import Document
            from models.task import Task

            task = session.scalar(
                select(Task)
                .where(Task.public_id == task_id, Task.tenant_id == tenant_id, Task.user_id == user_id)
                .with_for_update()
            )
            if task is None:
                raise PermissionError("INGESTION_NOT_FOUND")
            task, doc, graph = FormalIngestionLedger._load(session, task_id, lock=True)
            session.scalar(
                select(Document)
                .where(Document.id == doc.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                doc.tenant_id != tenant_id
                or doc.uploaded_by_user_id != user_id
                or any(row.source_sha256 != doc.content_sha256 for row in graph.values())
            ):
                raise ValueError("READY_LOCKED_DOCUMENT_IDENTITY_CHANGED")
            if any(graph[stage].status != "complete" for stage in STAGES):
                raise ValueError("READY_REQUIRED_STAGE_INCOMPLETE")
            if doc.status in {"failed", "quarantined"} or task.status == "failed":
                raise ValueError("READY_TERMINAL_FAILURE")
            payloads = {}
            for stage in STAGES:
                row = graph[stage]
                if row.artifact_id != row.artifact_sha256 or row.completed_at is None:
                    raise ValueError("READY_ARTIFACT_REFERENCE_INVALID")
                payloads[stage] = json.loads(self.artifacts.read(tenant_id, doc.content_sha256, row.artifact_sha256))
            schemas = {
                "PARSING": "financial-ingestion-parse.v1",
                "QUALITY_CHECK": "financial-ingestion-quality.v1",
                "BUILDING_FACTS": "financial-ingestion-facts.v1",
                "BUILDING_TREE": "financial-ingestion-tree.v1",
                "INDEXING": "financial-ingestion-index.v1",
            }
            for stage, payload in payloads.items():
                if payload.get("schema") != schemas[stage] or payload.get("source_sha256") != doc.content_sha256:
                    raise ValueError("READY_ARTIFACT_VERSION_OR_SOURCE_INVALID")
                # Existing quality schema binds identity through its parse reference/compatibility report.
                if stage != "QUALITY_CHECK" and (
                    type(payload.get("document_id")) is not int
                    or payload["document_id"] != doc.id
                    or type(payload.get("tenant_id")) is not int
                    or payload["tenant_id"] != tenant_id
                ):
                    raise ValueError("READY_ARTIFACT_DOCUMENT_INVALID")
            parsed, quality = payloads["PARSING"], payloads["QUALITY_CHECK"]
            if parsed.get("parser_version") != PARSER_VERSION or parsed.get("chunker_version") != CHUNKER_VERSION:
                raise ValueError("READY_PARSE_VERSION_INVALID")
            if (
                graph["QUALITY_CHECK"].quality_status != "PASS"
                or quality.get("quality_status") != "PASS"
                or quality.get("parse_artifact_sha256") != graph["PARSING"].artifact_sha256
                or quality.get("missing_native_source_ids")
                or quality.get("missing_ocr_source_ids")
                or not parsed.get("chunks")
            ):
                raise ValueError("READY_QUALITY_GATE_FAILED")
            for stage in ("BUILDING_FACTS", "INDEXING"):
                payload = payloads[stage]
                if (
                    payload.get("parse_artifact_sha256") != graph["PARSING"].artifact_sha256
                    or payload.get("quality_artifact_sha256") != graph["QUALITY_CHECK"].artifact_sha256
                ):
                    raise ValueError("READY_ARTIFACT_DEPENDENCY_MISMATCH")
            if not isinstance(payloads["BUILDING_FACTS"].get("facts"), list):
                raise ValueError("READY_FACT_EVIDENCE_INVALID")
            tree = payloads["BUILDING_TREE"]
            report = compatibility_report_from_dict(quality["compatibility"])
            if report.state != DocumentState.READY:
                raise ValueError("READY_COMPATIBILITY_GATE_FAILED")
            if (
                tree.get("builder_version") != "1"
                or tree.get("source_report_document_id") != report.document_id
                or tree.get("quality_artifact_sha256") != graph["QUALITY_CHECK"].artifact_sha256
                or tree.get("audit", {}).get("source_block_coverage") != 1
            ):
                raise ValueError("READY_TREE_EVIDENCE_INVALID")
            nodes = []
            for raw in tree["nodes"]:
                raw = dict(raw)
                if raw.get("tree_version") != "1":
                    raise ValueError("READY_TREE_VERSION_INVALID")
                for field in ("source_block_ids", "child_ids", "provenance"):
                    raw[field] = tuple(raw.get(field, ()))
                nodes.append(TreeNode(**raw))
            artifact = DocumentTree(
                tenant_id, report.document_id, doc.content_sha256, tuple(nodes), report, source_type=tree["source_type"]
            )
            audit = TreeBuildIntegrityEvaluator().evaluate(artifact)
            if audit.tree_quality == "INVALID" or audit.source_block_coverage != 1:
                raise ValueError("READY_TREE_INTEGRITY_FAILED")
            count = CoreIndexEvidenceReader(self.artifacts, self.vectors).validate(
                payloads["INDEXING"], tenant_id=tenant_id, document_id=doc.id, source_sha256=doc.content_sha256
            )
            if doc.status == "ready" and task.status == "success":
                close_terminal_obligation(task)
                return {"document_id": doc.id, "task_id": task.public_id, "status": "ready"}
            if doc.status == "ready" or task.status == "success":
                raise ValueError("READY_FINAL_STATE_INCONSISTENT")
            doc.status, doc.indexed_chunk_count = "ready", count
            task.status, task.progress, task.completed_at = "success", 100, now
            close_terminal_obligation(task)
            return {"document_id": doc.id, "task_id": task.public_id, "status": "ready"}
