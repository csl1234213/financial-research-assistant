"""Durable expected projection, never an index or a READY authority."""

import hashlib
import json
import math
import struct
import zlib

from document_compatibility.evidence_subject import INDEX_POLICY, project_subjects, subject_from_metadata
from storage.index_build_integrity import IndexBuildIntegrityEvaluator
from storage.vector_models import VectorDocument

FORMAT = "core-index-projection.v1"
MAGIC = b"FRIP1\x00"
MAX_RAW_BYTES = 256 * 1024 * 1024
BINDINGS = ("document_id", "tenant_id", "source_sha256", "collection", "embedding_identity", "index_policy_version")


def encode_projection(documents, binding):
    if not documents or set(BINDINGS) - set(binding):
        raise ValueError("INDEX_EVIDENCE_BINDING_REQUIRED")
    dimension = len(documents[0].embedding)
    if not dimension or any(len(doc.embedding) != dimension for doc in documents):
        raise ValueError("INDEX_EVIDENCE_DIMENSION_INVALID")
    rows = []
    vectors = bytearray()
    for doc in documents:
        if doc.document_id != str(binding["document_id"]) or any(not math.isfinite(v) for v in doc.embedding):
            raise ValueError("INDEX_EVIDENCE_PROJECTION_INVALID")
        rows.append(
            {
                "block_id": doc.chunk_id,
                "document_id": doc.document_id,
                "text": doc.content,
                "text_sha256": hashlib.sha256(doc.content.encode()).hexdigest(),
                "metadata": doc.metadata,
            }
        )
        vectors.extend(struct.pack(f"<{dimension}d", *doc.embedding))
    header = json.dumps(
        {"format": FORMAT, "binding": binding, "count": len(documents), "dimension": dimension, "blocks": rows},
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()
    raw = MAGIC + struct.pack("<I", len(header)) + header + vectors
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("INDEX_EVIDENCE_SIZE_LIMIT")
    compressed = zlib.compress(raw, level=6)
    return compressed, {
        "vector_count": len(documents),
        "dimension": dimension,
        "raw_evidence_bytes": len(raw),
        "compressed_evidence_bytes": len(compressed),
        "compression_ratio": len(raw) / len(compressed),
    }


def decode_projection(content, binding):
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(content, MAX_RAW_BYTES + 1)
        if len(raw) > MAX_RAW_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("INDEX_EVIDENCE_COMPRESSION_INVALID")
        if raw[: len(MAGIC)] != MAGIC:
            raise ValueError("INDEX_EVIDENCE_FORMAT_UNSUPPORTED")
        start = len(MAGIC) + 4
        size = struct.unpack("<I", raw[len(MAGIC) : start])[0]
        header = json.loads(raw[start : start + size])
        if header["format"] != FORMAT or header["binding"] != binding:
            raise ValueError("INDEX_EVIDENCE_IDENTITY_MISMATCH")
        count, dimension = header["count"], header["dimension"]
        if type(count) is not int or type(dimension) is not int or count <= 0 or dimension <= 0:
            raise ValueError("INDEX_EVIDENCE_SHAPE_INVALID")
        binary = raw[start + size :]
        if len(header["blocks"]) != count or len(binary) != count * dimension * 8:
            raise ValueError("INDEX_EVIDENCE_SHAPE_INVALID")
        result = []
        for index, row in enumerate(header["blocks"]):
            if (
                row["document_id"] != str(binding["document_id"])
                or hashlib.sha256(row["text"].encode()).hexdigest() != row["text_sha256"]
            ):
                raise ValueError("INDEX_EVIDENCE_BLOCK_INVALID")
            vector = list(struct.unpack_from(f"<{dimension}d", binary, index * dimension * 8))
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("INDEX_EVIDENCE_VECTOR_INVALID")
            result.append(
                VectorDocument(row["document_id"], row["block_id"], "Unknown", row["text"], vector, row["metadata"])
            )
        if len({doc.chunk_id for doc in result}) != count:
            raise ValueError("INDEX_EVIDENCE_DUPLICATE_BLOCK")
        return result
    except (KeyError, TypeError, UnicodeDecodeError, struct.error, zlib.error) as exc:
        raise ValueError("INDEX_EVIDENCE_INVALID") from exc


class CoreIndexEvidenceReader:
    def __init__(self, artifact_store, vector_store=None):
        self.artifacts, self.vectors = artifact_store, vector_store

    def load(self, receipt, *, tenant_id, document_id, source_sha256):
        if (
            receipt.get("schema") != "financial-ingestion-index.v1"
            or receipt.get("tenant_id") != tenant_id
            or type(receipt.get("tenant_id")) is not int
            or receipt.get("document_id") != document_id
            or type(receipt.get("document_id")) is not int
            or receipt.get("source_sha256") != source_sha256
            or receipt.get("index_policy_version") not in {"core-index.v1", INDEX_POLICY}
            or receipt.get("evidence_format_version") != FORMAT
            or not receipt.get("evidence_artifact_ref")
            or receipt.get("evidence_artifact_ref") != receipt.get("evidence_artifact_sha256")
        ):
            raise ValueError("INDEX_EVIDENCE_RECEIPT_INVALID")
        binding = {key: receipt[key] for key in BINDINGS}
        binding["parse_artifact_sha256"] = receipt["parse_artifact_sha256"]
        binding["quality_artifact_sha256"] = receipt["quality_artifact_sha256"]
        documents = decode_projection(
            self.artifacts.read(tenant_id, source_sha256, receipt["evidence_artifact_sha256"]), binding
        )
        if len(documents) != receipt.get("verified_chunk_count"):
            raise ValueError("INDEX_EVIDENCE_COUNT_MISMATCH")
        if receipt["index_policy_version"] == INDEX_POLICY:
            parsed = json.loads(self.artifacts.read(tenant_id, source_sha256, receipt["parse_artifact_sha256"]))
            quality = json.loads(self.artifacts.read(tenant_id, source_sha256, receipt["quality_artifact_sha256"]))
            expected = project_subjects(parsed, quality, parse_sha=receipt["parse_artifact_sha256"],
                                        quality_sha=receipt["quality_artifact_sha256"])
            if len(expected) != len(documents):
                raise ValueError("INDEX_SUBJECT_SOURCE_COUNT_CHANGED")
            for document, original in zip(documents, expected):
                subject = subject_from_metadata(document.metadata)
                if (subject is None or subject.parse_artifact_sha256 != receipt["parse_artifact_sha256"]
                        or subject.quality_artifact_sha256 != receipt["quality_artifact_sha256"]
                        or subject != original):
                    raise ValueError("INDEX_SUBJECT_PROJECTION_REQUIRED")
        return documents

    def validate(self, receipt, *, tenant_id, document_id, source_sha256):
        documents = self.load(receipt, tenant_id=tenant_id, document_id=document_id, source_sha256=source_sha256)
        if self.vectors is None:
            raise ValueError("INDEX_STORE_REQUIRED")
        return IndexBuildIntegrityEvaluator().evaluate(self.vectors, receipt["collection"], documents)
