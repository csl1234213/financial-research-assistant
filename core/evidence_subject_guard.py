"""Deterministic claim/evidence entity authority; no LLM or issuer fallback."""

import re

from core.fact_ledger import canonical_company
from core.intent_analyzer import IntentAnalyzer
from document_compatibility.evidence_subject import SubjectRelation, subject_from_metadata

GROUP_PREFIXES = ("控股股东", "控股股東", "控股股东集团", "控股股東集團",
                  "The controlling shareholder", "Controlling shareholder")


def _starts_subject(text, names):
    # A role/name must end at a grammatical boundary, not inside another name.
    boundary = (r"(?=$|\s|[，,:：。的是以在]|主要|主营|主營|业务|業務|从事|從事|经营|經營|"
                r"生产|生產|销售|銷售|包括|涉及|涉足|拥有|擁有)")
    return any(re.match(re.escape(name) + boundary, text, re.I) for name in names)


def bind_claim_subject(source, text, evidence_ids, *, caveat=None):
    evidence = {item.evidence_id: item for item in source.evidence}
    used = [evidence[eid] for eid in evidence_ids]
    formal = any(item.payload.get("source_kind") == "ready_indexed_text"
                 or "evidence_subject_schema" in item.payload.get("provenance", {}) for item in used)
    if not formal:
        # Explicitly unqualified legacy/non-formal research observations are not
        # upgraded to issuer authority by this new formal-index contract.
        return {"entity_id": None, "name": None, "relation": "UNKNOWN", "authority": "LEGACY_UNQUALIFIED"}
    subjects = [subject_from_metadata(item.payload.get("provenance", {})) for item in used]
    if any(s is None or s.subject_relation_to_issuer == SubjectRelation.UNKNOWN for s in subjects):
        raise ValueError("NARRATIVE_SUBJECT_UNQUALIFIED")
    group = [s for s in subjects if s.subject_relation_to_issuer == SubjectRelation.CONTROLLING_SHAREHOLDER]
    prefixes = GROUP_PREFIXES + tuple(s.subject_name for s in group)
    explicitly_group = _starts_subject(text, prefixes)
    rendered = text + (" " + caveat if caveat else "")
    names = IntentAnalyzer().analyze(source.query).get("companies") or []
    query_entities = {canonical_company(name) for name in names}
    if explicitly_group:
        if not group:
            raise ValueError("NARRATIVE_SUBJECT_CONFLICT")
        chosen = group[0]
        relation, identifier = SubjectRelation.CONTROLLING_SHAREHOLDER, chosen.subject_entity_id
        remainder = rendered
        for subject in group:
            remainder = remainder.replace(subject.subject_name, "")
        mentioned = IntentAnalyzer().analyze(remainder).get("companies") or []
        if mentioned or re.search(r"公司|\b(?:company|issuer)\b", remainder, re.I):
            raise ValueError("NARRATIVE_CLAIM_MULTIPLE_SUBJECTS")
    else:
        # An issuer claim is explicitly bound to the already resolved query and
        # report identity, not to whichever document happened to be retrieved.
        issuers = {canonical_company(item.payload.get("company", "")) for item in used}
        if not names or issuers != query_entities or len(issuers) != 1:
            raise ValueError("NARRATIVE_CLAIM_SUBJECT_NOT_BOUND")
        explicit = tuple(names) + tuple(item.payload["company"] for item in used) + (
            "公司", "本公司", "上市公司", "The company", "Company", "The issuer")
        mentioned = {canonical_company(name) for name in IntentAnalyzer().analyze(rendered).get("companies") or []}
        if (not _starts_subject(text, explicit) or mentioned - query_entities
                or re.search(r"控股股东|控股股東|\bcontrolling shareholder\b", rendered, re.I)):
            raise ValueError("NARRATIVE_CLAIM_SUBJECT_NOT_BOUND")
        chosen = subjects[0]
        relation, identifier = SubjectRelation.ISSUER, chosen.issuer_entity_id
    if any(s.subject_relation_to_issuer != relation or s.subject_entity_id != identifier for s in subjects):
        raise ValueError("NARRATIVE_SUBJECT_CONFLICT")
    return {"entity_id": identifier, "name": chosen.subject_name,
            "relation": relation.value, "authority": "QUERY_AND_SOURCE_SUBJECT_COMPATIBILITY.v1"}
