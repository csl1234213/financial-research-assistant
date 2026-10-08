"""Explicit narrative routing over admitted evidence; no generation or trust promotion."""

import re

from core.answer_synthesis_contracts import AnswerType, SynthesisInput
from core.fact_ledger import canonical_company
from core.intent_analyzer import IntentAnalyzer
from core.narrative_period_binding import narrative_period_is_bound


def narrative_answer_type(question):
    """Shared deterministic answer-shape classification, not retrieval policy."""
    for pattern, answer_type in (
        (r"跨文档|cross.document", AnswerType.CROSS_DOCUMENT),
        (r"跨章节|cross.section", AnswerType.CROSS_SECTION),
        (r"全部|所有|逐项|列出|exhaustive|list all", AnswerType.EXHAUSTIVE_LIST),
        (r"为什么|原因|why|caus", AnswerType.CAUSAL_ANALYSIS),
        (r"风险|risk", AnswerType.RISK_ANALYSIS),
        (r"解释|说明|explain", AnswerType.EXPLANATION),
    ):
        if re.search(pattern, question, re.I):
            return answer_type
    return None


class ReadyNarrativeSynthesisSource:
    def __init__(self, retriever, *, query_embedder=None):
        self.retriever = retriever
        self.query_embedder = query_embedder

    def __call__(self, *, question, locale, tenant_id, user_id, ingestion_job_id, manifest):
        answer_type = narrative_answer_type(question)
        if answer_type == AnswerType.CROSS_DOCUMENT:
            raise ValueError("MULTI_SOURCE_NARRATIVE_NOT_BOUND")
        if answer_type is None:
            raise ValueError("EXPLICIT_NARRATIVE_STRATEGY_REQUIRED")
        # Authorization before embedding work, even if an injected embedder is remote.
        if self.retriever.ledger.ready_index(ingestion_job_id, tenant_id, user_id) != manifest:
            raise ValueError("NARRATIVE_READINESS_CHANGED")
        question_search = getattr(self.retriever, "search_question_evidence", None)
        if callable(question_search):
            evidence = question_search(ingestion_job_id, tenant_id=tenant_id,
                                       user_id=user_id, question=question)
        else:
            evidence = self.retriever.search_evidence(ingestion_job_id, tenant_id=tenant_id,
                user_id=user_id, query_embedding=self.query_embedder(question))
        if not evidence:
            raise ValueError("NARRATIVE_EVIDENCE_MISSING")
        if any(item.document_id != str(manifest["document_id"])
               or item.payload["provenance"]["content_sha256"] != manifest["source_sha256"] for item in evidence):
            raise ValueError("NARRATIVE_SOURCE_CHANGED")
        if answer_type == AnswerType.CROSS_SECTION:
            sections = [item.payload.get("section") for item in evidence]
            if (any(not isinstance(section, str) or not section.strip() for section in sections)
                    or len({section.strip() for section in sections}) < 2):
                raise ValueError("CROSS_SECTION_EVIDENCE_REQUIRED")
        companies = IntentAnalyzer().analyze(question).get("companies") or []
        if companies and any(not item.payload.get("company") or
                canonical_company(item.payload["company"]) not in {canonical_company(c) for c in companies}
                for item in evidence):
            raise ValueError("NARRATIVE_QUERY_COMPANY_NOT_BOUND")
        if any(not narrative_period_is_bound(question, item.payload) for item in evidence):
            raise ValueError("NARRATIVE_QUERY_PERIOD_NOT_BOUND")
        components = {item.payload["provenance"].get("retrieval_component", "vector_only") for item in evidence}
        component = next(iter(components)) if len(components) == 1 else "mixed"
        routes = {item.payload["retriever"] for item in evidence}
        route = "TREE" if routes == {"TREE"} else "HYBRID"
        return SynthesisInput(question, tenant_id, answer_type, locale, evidence, "PARTIAL", route,
                              {"complete": None, "retrieval_component": component})
