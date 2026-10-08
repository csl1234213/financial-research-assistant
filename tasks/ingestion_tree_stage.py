"""Build the existing source-backed tree from a persisted quality artifact."""

import json
from dataclasses import asdict

from document_compatibility.serialization import compatibility_report_from_dict
from document_compatibility.tree_artifact_builder import TreeArtifactBuilder
from document_compatibility.tree_build_integrity import TreeBuildIntegrityEvaluator


class FinancialTreeStage:
    def __init__(self, artifact_store):
        self.store = artifact_store

    def execute(self, lease, *, parse_artifact_sha256, quality_artifact_sha256):
        if lease.stage != "BUILDING_TREE":
            raise ValueError("TREE_STAGE_MISMATCH")
        quality = json.loads(self.store.read(lease.tenant_id, lease.source_sha256, quality_artifact_sha256))
        if (quality.get("schema") != "financial-ingestion-quality.v1"
                or quality.get("quality_status") != "PASS"
                or quality.get("source_sha256") != lease.source_sha256
                or quality.get("parse_artifact_sha256") != parse_artifact_sha256):
            raise ValueError("TREE_QUALITY_GATE_FAILED")
        self.store.read(lease.tenant_id, lease.source_sha256, parse_artifact_sha256)
        report = compatibility_report_from_dict(quality["compatibility"])
        tree = TreeArtifactBuilder().build(report, tenant_id=lease.tenant_id, content_sha256=lease.source_sha256)
        audit = TreeBuildIntegrityEvaluator().evaluate(tree)
        if audit.tree_quality == "INVALID" or audit.source_block_coverage != 1:
            raise ValueError("TREE_INVALID")
        payload = {"schema": "financial-ingestion-tree.v1", "source_sha256": lease.source_sha256,
                   "document_id": lease.document_id, "tenant_id": lease.tenant_id,
                   "quality_artifact_sha256": quality_artifact_sha256,
                   "source_report_document_id": report.document_id,
                   "nodes": [asdict(node) for node in tree.nodes], "audit": asdict(audit),
                   "source_type": tree.source_type, "builder_version": tree.builder_version}
        digest = self.store.put(lease.tenant_id, lease.source_sha256,
                                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
        return {"artifact_id": digest, "artifact_sha256": digest}
