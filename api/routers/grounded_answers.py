"""Opt-in authenticated, READY-bound synthesis endpoint; no production mount."""

import json
import time
from types import MappingProxyType
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.schemas.response import ChatResponse, Citation, Reasoning
from auth.dependencies import get_current_user
from core.answer_synthesis_budget import NarrativeTimeBudget
from core.answer_synthesis_contracts import SynthesisInput
from core.answer_synthesis_narrative import NARRATIVE_TYPES
from core.answer_synthesis_narrative_workflow import synthesize_narrative, verified_narrative_outcome_chunks
from core.answer_synthesis_planner import DeterministicAnswerPlanner
from core.answer_synthesis_release import verified_answer_chunks
from core.answer_synthesis_renderer import RestrictedAnswerRenderer
from core.answer_synthesis_workflow import BoundedSynthesisWorkflow
from document_compatibility.evidence_subject import subject_from_metadata
from models.user import User


class GroundedChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ingestion_job_id: str = Field(min_length=1, max_length=128)
    additional_ingestion_job_ids: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=4)
    question: str = Field(min_length=1, max_length=4000)
    answer_language: Literal["zh-CN", "zh-TW", "en"] = "zh-CN"
    stream: bool = False

    @model_validator(mode="after")
    def distinct_jobs(self):
        jobs = [self.ingestion_job_id, *self.additional_ingestion_job_ids]
        if any(not job.strip() or job != job.strip() for job in jobs) or len(set(jobs)) != len(jobs):
            raise ValueError("distinct nonblank ingestion job identities required")
        return self


def _event(name, payload):
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_grounded_answer_router(ledger, *, source_resolver, narrative_generator=None,
                                semantic_reviewer=None, narrative_enabled=False, multi_source_resolver=None,
                                narrative_time_budget=None, narrative_ports_resolver=None,
                                narrative_max_total_tokens=8192):
    """Resolver is trusted server wiring, not user-submitted evidence or routing.

    It must obtain authoritative query semantics and evidence from the admitted
    document. Provider authorization is explicit server policy, never a body flag.
    """
    if narrative_time_budget is None:
        narrative_time_budget = NarrativeTimeBudget()
    if not isinstance(narrative_time_budget, NarrativeTimeBudget):
        raise ValueError("SERVER_NARRATIVE_TIME_POLICY_REQUIRED")
    router = APIRouter(tags=["Grounded Answer Pilot"])

    @router.post("/grounded-chat", response_model=ChatResponse)
    def answer(body: GroundedChatRequest, user: User = Depends(get_current_user)):
        started = time.monotonic()
        jobs = (body.ingestion_job_id, *body.additional_ingestion_job_ids)
        def ready():
            return {job: ledger.ready_index(job, user.tenant_id, user.id) for job in jobs}
        try:
            manifests = ready()
            manifest = manifests[body.ingestion_job_id]
            by_document = {str(value["document_id"]): value for value in manifests.values()}
            if len(by_document) != len(jobs):
                raise ValueError("DISTINCT_DOCUMENTS_REQUIRED")
            if len(jobs) > 1:
                if multi_source_resolver is None:
                    raise ValueError("MULTI_DOCUMENT_SOURCE_NOT_CONFIGURED")
                source = multi_source_resolver(question=body.question, locale=body.answer_language,
                    tenant_id=user.tenant_id, user_id=user.id,
                    manifests=MappingProxyType({job: MappingProxyType(value) for job, value in manifests.items()}))
            else:
                source = source_resolver(question=body.question, locale=body.answer_language,
                                     tenant_id=user.tenant_id, user_id=user.id,
                                     ingestion_job_id=body.ingestion_job_id,
                                     manifest=MappingProxyType(manifest))
            if (not isinstance(source, SynthesisInput) or source.query != body.question
                    or source.locale != body.answer_language or source.tenant_id != user.tenant_id
                    or (len(jobs) > 1 and {item.document_id for item in source.evidence} != set(by_document))
                    or any(item.document_id not in by_document
                           or type(item.payload["provenance"].get("tenant_id")) is not int
                           or item.payload["provenance"].get("tenant_id") != user.tenant_id
                           or item.payload["provenance"].get("content_sha256")
                           != by_document[item.document_id]["source_sha256"]
                           or item.payload["provenance"].get("document_version",
                               by_document[item.document_id]["source_sha256"])
                           != by_document[item.document_id]["source_sha256"]
                           for item in source.evidence)):
                raise ValueError("SOURCE_BINDING_MISMATCH")
            if source.answer_type in NARRATIVE_TYPES:
                generator, reviewer, enabled, budget = (
                    narrative_generator, semantic_reviewer, narrative_enabled, narrative_time_budget)
                if narrative_ports_resolver is not None:
                    generator, reviewer, budget = narrative_ports_resolver(
                        tenant_id=user.tenant_id, user_id=user.id)
                    if not isinstance(budget, NarrativeTimeBudget):
                        raise ValueError("SERVER_NARRATIVE_TIME_POLICY_REQUIRED")
                    enabled = True
                result = synthesize_narrative(source, generator=generator,
                    reviewer=reviewer, enabled=enabled, max_total_tokens=narrative_max_total_tokens,
                    max_seconds=budget.total_seconds,
                    max_call_seconds=budget.per_call_seconds)
                report = "".join(verified_narrative_outcome_chunks(source, result))
                plan = result.generated.buffered.plan
                citation_ids = result.generated.buffered.citation_evidence_ids
                tokens = result.total_tokens
                usage = {"answer_tokens": tokens, "usage_complete": result.usage_complete,
                         "generation_calls": result.generation_calls, "reviewer_calls": result.reviewer_calls,
                         "revision_count": result.generation_calls - 1,
                         "synthesis_latency": result.generation_seconds,
                         "verify_latency": result.review_seconds,
                         "workflow_latency": result.workflow_seconds}
            else:
                plan = DeterministicAnswerPlanner().plan(source)
                result = BoundedSynthesisWorkflow().run(source, plan, analysis_enabled=True)
                report = "".join(verified_answer_chunks(source, plan, result))
                citation_ids = RestrictedAnswerRenderer().render(source, plan).citation_evidence_ids
                tokens = result.total_tokens
                usage = {"answer_tokens": tokens}
            evidence = {item.evidence_id: item for item in source.evidence}
            citations = [Citation(rank=rank, source=str(evidence[eid].payload.get("source", "")),
                chunk_id=eid, similarity=None, preview=str(evidence[eid].payload.get("text", ""))[:300],
                source_locator=str(evidence[eid].payload["source_locator"].get("locator", "")),
                evidence_locator=dict(evidence[eid].payload["source_locator"]),
                page=evidence[eid].payload["source_locator"].get("page"),
                document_id=evidence[eid].document_id,
                content_sha256=by_document[evidence[eid].document_id]["source_sha256"],
                evidence_subject=(subject_from_metadata(evidence[eid].payload.get("provenance", {})).to_dict()
                    if subject_from_metadata(evidence[eid].payload.get("provenance", {})) is not None else None))
                for rank, eid in enumerate(citation_ids, 1)]
            response = ChatResponse(report=report, citations=citations,
                reasoning=Reasoning(intent=source.answer_type.value,
                    companies=list(dict.fromkeys(str(item.payload.get("company", "")) for item in source.evidence)),
                    research_mode="grounded-pilot", evidence_count=len(source.evidence)),
                plan={"answer_type": plan.answer_type.value, "claim_ids": [c.claim_id for c in plan.claims],
                      "claims": [{"claim_id": c.claim_id, "claim_type": c.claim_type.value,
                                  "evidence_ids": list(c.evidence_ids), "fact_status": c.fact_status,
                                  "claim_subject": dict(c.claim_subject) if c.claim_subject is not None else None}
                                 for c in plan.claims],
                      "caveats": list(plan.caveats), "verified": True},
                execution_time=time.monotonic() - started, usage=usage)
            if ready() != manifests:
                raise ValueError("READINESS_CHANGED")
        except PermissionError as exc:
            raise HTTPException(404, "DOCUMENT_NOT_FOUND") from exc
        except Exception as exc:
            # No provider body, source text, failed draft or local path escapes.
            raise HTTPException(409, "GROUNDED_ANSWER_NOT_AVAILABLE") from exc
        if not body.stream:
            return response

        def events():
            for offset in range(0, len(response.report), 48):
                try:
                    if ready() != manifests:
                        raise ValueError("READINESS_CHANGED")
                except Exception:
                    yield _event("error", {"status": 409, "detail": "DOCUMENT_READINESS_CHANGED"})
                    return
                yield _event("delta", {"text": response.report[offset:offset + 48]})
            try:
                if ready() != manifests:
                    raise ValueError("READINESS_CHANGED")
            except Exception:
                yield _event("error", {"status": 409, "detail": "DOCUMENT_READINESS_CHANGED"})
                return
            yield _event("complete", response.model_dump(mode="json"))
        return StreamingResponse(events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"})
    return router
