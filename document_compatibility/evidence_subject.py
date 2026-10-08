"""Source-bound structural subject authority, not keyword/entity inference."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum

from document_compatibility.source_subject_context import controlling_shareholder_contexts, explicitly_named_subject

SUBJECT_SCHEMA = "formal-evidence-subject.v1"
INDEX_POLICY = "core-index.v2-subject"


class SubjectRelation(StrEnum):
    ISSUER = "ISSUER"
    CONTROLLING_SHAREHOLDER = "CONTROLLING_SHAREHOLDER"
    UNKNOWN = "UNKNOWN"


def entity_id(name):
    return "entity:" + hashlib.sha256(name.strip().encode()).hexdigest() if name else None


@dataclass(frozen=True)
class EvidenceSubject:
    subject_entity_id: str | None
    subject_name: str | None
    subject_type: str
    subject_relation_to_issuer: str
    subject_authority: str
    subject_source_block_id: str | None
    issuer_entity_id: str | None
    source_sha256: str
    parse_artifact_sha256: str
    quality_artifact_sha256: str
    page: int
    section_path: tuple[str, ...]
    schema: str = SUBJECT_SCHEMA

    def to_dict(self):
        value = asdict(self)
        value["section_path"] = list(self.section_path)
        return value

    def serialize(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def digest(self):
        return hashlib.sha256(self.serialize().encode()).hexdigest()

    @classmethod
    def deserialize(cls, value):
        try:
            row = json.loads(value)
            if set(row) != set(cls.__dataclass_fields__) or row["schema"] != SUBJECT_SCHEMA:
                raise ValueError("EVIDENCE_SUBJECT_SCHEMA_INVALID")
            relation = SubjectRelation(row["subject_relation_to_issuer"])
            if (type(row["page"]) is not int or row["page"] < 1
                    or not isinstance(row["section_path"], list)
                    or any(not isinstance(x, str) for x in row["section_path"])):
                raise ValueError("EVIDENCE_SUBJECT_SOURCE_INVALID")
            for key in ("source_sha256", "parse_artifact_sha256", "quality_artifact_sha256"):
                if not isinstance(row[key], str) or not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                    raise ValueError("EVIDENCE_SUBJECT_SOURCE_INVALID")
            if row["issuer_entity_id"] is not None and (not isinstance(row["issuer_entity_id"], str)
                    or not re.fullmatch(r"entity:[0-9a-f]{64}", row["issuer_entity_id"])):
                raise ValueError("EVIDENCE_SUBJECT_ISSUER_INVALID")
            if relation != SubjectRelation.UNKNOWN:
                if (not row["subject_name"] or entity_id(row["subject_name"]) != row["subject_entity_id"]
                        or not row["subject_source_block_id"] or not row["issuer_entity_id"]
                        or row["subject_authority"] != "canonical-title-and-explicit-name.v1"
                        or row["subject_type"] != "ORGANIZATION"):
                    raise ValueError("EVIDENCE_SUBJECT_AUTHORITY_INVALID")
                if relation == SubjectRelation.ISSUER and row["subject_entity_id"] != row["issuer_entity_id"]:
                    raise ValueError("EVIDENCE_SUBJECT_ISSUER_INVALID")
            elif (any(row[key] is not None for key in ("subject_name", "subject_entity_id", "subject_source_block_id"))
                    or row["subject_type"] != "UNKNOWN" or row["subject_authority"] != "UNKNOWN"):
                raise ValueError("UNKNOWN_SUBJECT_CANNOT_BECOME_ISSUER")
            row["section_path"] = tuple(row["section_path"])
            return cls(**row)
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError("EVIDENCE_SUBJECT_INVALID") from exc


def project_subjects(parsed, quality, *, parse_sha, quality_sha):
    """Project only canonical TITLE authority and explicit same-page names.

    No title authority means UNKNOWN. A report issuer is never a default subject.
    Existing owner-context rules supply the relationship; no 'group' name heuristic.
    """
    source = parsed["source_sha256"]
    identity = parsed.get("document_identity", {})
    issuer = identity.get("company") if identity.get("source_sha256") == source else None
    if issuer == "Unknown":
        issuer = None
    canonical = quality.get("compatibility", {}).get("blocks", [])
    titles = [b for b in canonical if b.get("block_type") == "TITLE" and b.get("block_id")]
    contexts = controlling_shareholder_contexts(parsed["chunks"])
    result = []
    for chunk, context in zip(parsed["chunks"], contexts):
        page = chunk["page"]
        relation, name, anchor = SubjectRelation.UNKNOWN, None, None
        section = chunk.get("section", "")
        if issuer and context:
            anchors = [b for b in titles if b["page"] == page
                       and "控股股东情况" in b.get("section", "")
                       and b["text"].strip() in context["context_text"]]
            name = explicitly_named_subject(context["context_text"])
            if anchors and name:
                relation, anchor = SubjectRelation.CONTROLLING_SHAREHOLDER, anchors[0]
            else:
                name = None
        elif issuer:
            # Explicit issuer-business heading is a canonical structural rule,
            # not an occurrence of 'company' or an inferred issuer relationship.
            anchors = [b for b in titles if b["page"] == page
                       and b.get("section") == "一、报告期内公司从事的业务情况"
                       and b["text"].strip() in chunk["text"]]
            if anchors:
                relation, name, anchor = SubjectRelation.ISSUER, issuer, anchors[0]
        subject = EvidenceSubject(entity_id(name), name, "ORGANIZATION" if name else "UNKNOWN",
            relation.value, "canonical-title-and-explicit-name.v1" if name else "UNKNOWN",
            anchor["block_id"] if anchor else None, entity_id(issuer), source, parse_sha, quality_sha,
            page, tuple(dict.fromkeys((anchor["section"], section))) if anchor else (section,))
        result.append(subject)
    return tuple(result)


def subject_from_metadata(metadata):
    """Old indexes are unqualified, never implicitly issuer-subject evidence."""
    if metadata.get("evidence_subject_schema") != SUBJECT_SCHEMA:
        return None
    subject = EvidenceSubject.deserialize(metadata.get("evidence_subject"))
    if (subject.digest != metadata.get("subject_provenance_digest")
            or subject.source_sha256 != metadata.get("source_sha256", metadata.get("content_sha256"))
            or subject.page != metadata.get("page")):
        raise ValueError("EVIDENCE_SUBJECT_PROVENANCE_CHANGED")
    return subject
