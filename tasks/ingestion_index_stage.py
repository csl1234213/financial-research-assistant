"""Idempotent real vector writes with exact source-bound readback validation."""

import hashlib
import json
import math

from document_compatibility.evidence_subject import INDEX_POLICY, SUBJECT_SCHEMA, project_subjects
from storage.core_index_evidence import FORMAT, CoreIndexEvidenceReader, encode_projection
from storage.index_build_integrity import IndexBuildIntegrityEvaluator
from storage.vector_models import VectorDocument


class CoreIndexBuilder:
    def __init__(self, artifact_store, vector_store, *, embedder, embedding_identity, enhancement=None):
        if not embedding_identity:
            raise ValueError("EMBEDDING_IDENTITY_REQUIRED")
        self.artifacts, self.vectors = artifact_store, vector_store
        self.embedder, self.embedding_identity = embedder, embedding_identity
        self.enhancement = enhancement
        self.index_policy_version = enhancement.version if enhancement is not None else INDEX_POLICY

    def execute(self, lease, *, parse_artifact_sha256, quality_artifact_sha256):
        if lease.stage != "INDEXING":
            raise ValueError("INDEX_STAGE_MISMATCH")
        parsed = json.loads(self.artifacts.read(lease.tenant_id, lease.source_sha256, parse_artifact_sha256))
        quality = json.loads(self.artifacts.read(lease.tenant_id, lease.source_sha256, quality_artifact_sha256))
        if (parsed.get("document_id") != lease.document_id or parsed.get("tenant_id") != lease.tenant_id
                or parsed.get("source_sha256") != lease.source_sha256
                or quality.get("quality_status") != "PASS"
                or quality.get("source_sha256") != lease.source_sha256
                or quality.get("parse_artifact_sha256") != parse_artifact_sha256):
            raise ValueError("INDEX_SOURCE_GATE_FAILED")
        chunks = parsed["chunks"]
        texts = [chunk["text"] for chunk in chunks]
        embeddings = self.embedder(texts)
        if not chunks or len(embeddings) != len(chunks):
            raise ValueError("INDEX_EMBEDDING_COUNT_MISMATCH")
        sizes = {len(vector) for vector in embeddings}
        if len(sizes) != 1 or not next(iter(sizes)) or any(
            any(not math.isfinite(value) for value in vector) or not any(vector) for vector in embeddings
        ):
            raise ValueError("INDEX_INVALID_EMBEDDING")
        identity = (f"{lease.tenant_id}:{lease.document_id}:{lease.source_sha256}:"
                    f"{parse_artifact_sha256}:{self.embedding_identity}:{self.index_policy_version}")
        collection = "p23_isolated_" + hashlib.sha256(identity.encode()).hexdigest()[:40]
        documents = []
        report_identity = parsed.get("document_identity", {})
        report_context = {}
        if report_identity.get("source_sha256") == lease.source_sha256:
            for field, name in (("company", "report_company"), ("report_period", "report_period")):
                value = report_identity.get(field)
                if isinstance(value, str) and value.strip() and value != "Unknown":
                    report_context[name] = value
        extra_metadata = (self.enhancement.project(chunks) if self.enhancement is not None
                          else tuple({} for _ in chunks))
        subjects = (project_subjects(parsed, quality, parse_sha=parse_artifact_sha256,
                                    quality_sha=quality_artifact_sha256) if self.enhancement is None else None)
        if len(extra_metadata) != len(chunks):
            raise ValueError("INDEX_ENHANCEMENT_COUNT_MISMATCH")
        for index, (chunk, vector, extra) in enumerate(zip(chunks, embeddings, extra_metadata)):
            # Subject schema versions isolate collections, not original block identity.
            block_identity = (f"{lease.tenant_id}:{lease.document_id}:{lease.source_sha256}:"
                              f"{parse_artifact_sha256}:{self.embedding_identity}:core-index.v1"
                              if self.enhancement is None else identity)
            identifier = hashlib.sha256(f"{block_identity}:{index}".encode()).hexdigest()
            provenance = {key: chunk[key] for key in ("section", "source_locator", "content_type",
                          "source_format", "parser_version", "chunker_version")
                          if isinstance(chunk.get(key), str) and chunk[key]}
            provenance.update(extra)
            if subjects is not None:
                subject = subjects[index]
                provenance.update(evidence_subject_schema=SUBJECT_SCHEMA,
                                  evidence_subject=subject.serialize(),
                                  subject_provenance_digest=subject.digest)
            documents.append(VectorDocument(str(lease.document_id), identifier, "Unknown", chunk["text"], vector,
                                           {"collection": collection, "tenant_id": lease.tenant_id,
                                            "source_sha256": lease.source_sha256, "page": chunk["page"],
                                            **provenance,
                                            **report_context,
                                            "embedding_identity": self.embedding_identity}))
        self.vectors.add_documents(documents)
        if self.enhancement is None:
            # Chroma persists document_id as an existing store-owned metadata field.
            # Include it in expected evidence so cross-document rebinding is rejected.
            for document in documents:
                document.metadata["document_id"] = document.document_id
        IndexBuildIntegrityEvaluator().evaluate(self.vectors, collection, documents)
        payload = {"schema": "financial-ingestion-index.v1", "collection": collection,
                   "source_sha256": lease.source_sha256, "document_id": lease.document_id,
                   "tenant_id": lease.tenant_id, "verified_chunk_count": len(documents),
                   "embedding_identity": self.embedding_identity}
        if self.enhancement is None:
            payload["index_policy_version"] = self.index_policy_version
            binding = {key: payload[key] for key in ("document_id", "tenant_id", "source_sha256",
                       "collection", "embedding_identity", "index_policy_version")}
            binding.update(parse_artifact_sha256=parse_artifact_sha256,
                           quality_artifact_sha256=quality_artifact_sha256)
            evidence, sizes = encode_projection(documents, binding)
            evidence_digest = self.artifacts.put(lease.tenant_id, lease.source_sha256, evidence)
            self.artifacts.read(lease.tenant_id, lease.source_sha256, evidence_digest)
            payload.update(evidence_artifact_ref=evidence_digest, evidence_artifact_sha256=evidence_digest,
                           evidence_format_version=FORMAT, evidence_size=sizes,
                           parse_artifact_sha256=parse_artifact_sha256,
                           quality_artifact_sha256=quality_artifact_sha256)
            CoreIndexEvidenceReader(self.artifacts, self.vectors).validate(
                payload, tenant_id=lease.tenant_id, document_id=lease.document_id,
                source_sha256=lease.source_sha256)
        digest = self.artifacts.put(lease.tenant_id, lease.source_sha256,
                                    json.dumps(payload, sort_keys=True).encode())
        return {"artifact_id": digest, "artifact_sha256": digest}



class FinancialIndexStage(CoreIndexBuilder):
    """Compatibility composition for the existing explicitly enriched index."""

    def __init__(self, artifact_store, vector_store, *, embedder, embedding_identity):
        from services.index_subject_enhancement import SubjectContextIndexEnhancement

        super().__init__(artifact_store, vector_store, embedder=embedder,
                         embedding_identity=embedding_identity,
                         enhancement=SubjectContextIndexEnhancement())
