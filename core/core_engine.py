import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from threading import Lock
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

# agent 执行组件
from agent.agent_runtime import AgentRuntime
from agent.execution import strategies as _builtin_execution_strategies  # noqa: F401
from agent.execution.execution_dispatcher import ExecutionDispatcher
from agent.execution.execution_engine import StrategyExecutionEngine
from agent.execution.financial_metrics_handler import (
    FinancialMetricsStepHandler,
    authorize_financial_metrics_tool,
)
from agent.execution.step_execution_engine import StepExecutionEngine
from agent.execution_plan import StepType
from agent.query_planner import QueryPlanner
from agent.reasoning_engine import ReasoningEngine
from agent.reasoning_models import Evidence
from agent.tools import ToolEngine
from agent.workflow.workflow_engine import WorkflowEngine
from agent.workflow.workflow_executor import WorkflowExecutor
from agent.workflow.workflows import (  # noqa: F401 — auto-registration
    ComparisonWorkflow,
    DirectChatWorkflow,
    RAGWorkflow,
    ResearchWorkflow,
    ToolPipelineWorkflow,
)
from config import (
    DEBUG_MODE,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
)
from core.answer_policy import finalize_grounded_answer, no_evidence_response
from core.citation_gate import filter_evidence_for_query
from core.context_builder import build_context_from_evidence
from core.fact_ledger import build_evidence_first_context
from core.intent_analyzer import IntentAnalyzer
from core.query_scope import QueryScope, classify_query_scope
from core.rag_result import RAGResult
from core.report_builder import build_research_report
from core.required_fact_plan import (
    infer_required_fact_plan,
)
from core.research_analyzer import analyze_evidence
from core.retrieval_probes import retrieval_probe_queries, retrieval_probe_top_k
from core.retrieval_tool_adapter import TenantRetrievalToolExecutor
from core.structured_financial_query import lookup_persisted_financial_fact
from document_loader import (
    load_documents,
)
from embedding import (
    embed_passages,
    embedding_rows_to_lists,
    load_embedding_model,
)
from llm.provider import call_llm
from llm.router import (
    CapabilityRoutingPolicy,
    ModelRouter,
    RoutingPolicy,
)
from prompt_builder import (
    build_compare_prompt,
    build_direct_chat_prompt,
    build_prompt,
    get_prompt_metadata,
    get_prompt_system_prompt,
)
from research_mode import (
    detect_research_mode,
)
from retrieval.hybrid_retriever import (
    HybridRetriever,
)
from storage.vector_models import VectorDocument

logger = logging.getLogger(__name__)

# =========================
# Pipeline Composition
# =========================

PDF_FOLDER = "pdfs/"
PUBLIC_TENANT_ID = 0

_AUDIT_FACT_QUESTION = re.compile(
    r"\b(?:auditor|audit firm|audited by|audit opinion)\b|"
    r"会计师事务所|审计机构|审计意见|审计报告由",
    re.IGNORECASE,
)
_AUDIT_FIRM_EVIDENCE = re.compile(
    r"\b(?:independent\s+auditor|audit\s+firm|audited\s+by)\b|"
    r"会计师事务所|审计机构",
    re.IGNORECASE,
)
_POSITIVE_AUDIT_OPINION_EVIDENCE = re.compile(
    r"\b(?:unmodified|unqualified)\s+opinion\b|标准无保留意见|(?<!非)无保留意见",
    re.IGNORECASE,
)

_store = None
_model = None
_model_init_lock = Lock()
_store_init_lock = Lock()


def _capture_smoke_grounding(
    *,
    question: str,
    raw_answer: str,
    grounded: Any | None,
    retrieved: Sequence[Any],
    final_grounded: Any | None = None,
    final_report: str | None = None,
    prepared_answer: str | None = None,
) -> None:
    """Write opt-in smoke diagnostics outside the repository/API response."""

    target = os.environ.get("P1_3_SMOKE_AUDIT_PATH", "").strip()
    if not target:
        return

    final_grounded = final_grounded or grounded
    grounded_answer = final_grounded.answer if final_grounded is not None else raw_answer
    grounded_claims = grounded.claims if grounded is not None else []
    grounded_evidence = final_grounded.evidence if final_grounded is not None else []
    safe_metadata_fields = {
        "chunk_id", "document_id", "quarter", "periods", "metrics", "page", "section", "table_context",
        "document_reporting_period", "fact_period", "evidence_row_period", "row_period",
        "table_column_period", "column_period", "semantic_support", "source_authority",
        "period_type", "period_start", "period_end",
    }

    def evidence_payload(item):
        return {
            "source": item.source, "company": item.company,
            "chunk_id": item.metadata.get("chunk_id"), "content": item.content,
            "metadata": {key: value for key, value in item.metadata.items() if key in safe_metadata_fields},
        }

    payload = {
        "question": question,
        "raw_llm_answer": raw_answer,
        "final_sanitized_answer": grounded_answer,
        "final_api_report": final_report,
        "prepared_answer": prepared_answer,
        "grounding_result": {
            "claims": [{"text": claim.text, "disposition": claim.disposition} for claim in grounded_claims],
            "unsupported_count": grounded.unsupported_count if grounded is not None else 0,
            "supported_count": grounded.supported_count if grounded is not None else 0,
            "derivable_count": grounded.derivable_count if grounded is not None else 0,
            "uncertain_count": grounded.uncertain_count if grounded is not None else 0,
            "judgments": [
                {
                    "relation": judgment.relation.value,
                    "action": judgment.action.value,
                    "confidence": judgment.confidence,
                    "reason": judgment.reason,
                }
                for judgment in (grounded.judgments if grounded is not None else [])
            ],
        },
        "final_grounding_result": {
            "claims": [{"text": claim.text, "disposition": claim.disposition}
                       for claim in final_grounded.claims] if final_grounded is not None else [],
            "unsupported_count": final_grounded.unsupported_count if final_grounded is not None else 0,
            "judgments": [
                {
                    "relation": judgment.relation.value,
                    "action": judgment.action.value,
                    "confidence": judgment.confidence,
                    "reason": judgment.reason,
                }
                for judgment in (final_grounded.judgments if final_grounded is not None else [])
            ],
        },
        "retrieved_evidence": [evidence_payload(item) for item in retrieved],
        "final_evidence": [evidence_payload(item) for item in grounded_evidence],
    }
    try:
        output = Path(target)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        # Diagnostics must never make a successful user request fail.
        return


def _log_pipeline_stage(stage: str, started: float, *, thread_id: str | None = None) -> None:
    """Record bounded, secret-free monotonic stage timing for timeout audits."""

    logger.info(
        "pipeline_stage stage=%s duration_ms=%.2f thread_id=%s",
        stage,
        (time.monotonic() - started) * 1000,
        thread_id or "default",
    )


def _get_model():
    global _model
    if _model is None:
        with _model_init_lock:
            if _model is None:
                _model = load_embedding_model()
    return _model


def _get_store():
    global _store
    if _store is None:
        with _store_init_lock:
            if _store is None:
                from storage.chroma_store import ChromaEmbeddingStore

                _store = ChromaEmbeddingStore()
    return _store


# =========================
# Knowledge Base
# =========================


def refresh_knowledge_base():
    """Refresh only the intentionally public/demo knowledge base.

    Private uploads are processed by the tenant-aware worker path.  The old
    implementation deleted every collection before loading demo PDFs, which
    could erase tenant data during an unrelated refresh.
    """
    store = _get_store()
    model = _get_model()

    chunks = load_documents(PDF_FOLDER)
    embeddings = embedding_rows_to_lists(
        embed_passages(
            model,
            [str(chunk["text"]) for chunk in chunks],
        )
    )
    if len(embeddings) != len(chunks):
        raise ValueError("Embedding model returned an unexpected vector count")

    store.create_collection("financial_reports")
    store.delete_by_tenant(PUBLIC_TENANT_ID)

    docs = []
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        content_sha256 = str(chunk["content_sha256"])
        docs.append(
            VectorDocument(
                document_id=str(chunk["document_id"]),
                chunk_id=f"public_{content_sha256}_{chunk['chunk_id']}",
                company=str(chunk["company"]),
                content=str(chunk["text"]),
                embedding=embedding,
                metadata={
                    "source": str(chunk["source"]),
                    "quarter": str(chunk.get("quarter", "")),
                    "periods": str(chunk.get("periods", "")),
                    "metrics": str(chunk.get("metrics", "")),
                    "collection": "financial_reports",
                    "tenant_id": PUBLIC_TENANT_ID,
                    "page": int(chunk["page"]),
                    "section": str(chunk["section"]),
                    "ocr_used": bool(chunk["ocr_used"]),
                    "parser_version": str(chunk["parser_version"]),
                    "chunker_version": str(chunk["chunker_version"]),
                    "table_context": str(chunk.get("table_context", "")),
                    "source_authority": "public_filing",
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_revision": EMBEDDING_MODEL_REVISION or "unversioned",
                    "content_sha256": content_sha256,
                },
            )
        )

    store.add_documents(docs)

    print(f"[RAG] Loaded {len(chunks)} chunks into ChromaDB")

    if len(chunks) > 0:
        print(chunks[0]["source"], chunks[0]["chunk_id"])


def get_chunk_count():
    store = _get_store()
    return store.count()


# =========================
# Runtime Wiring
# =========================

_retriever = None
_retrieval_tool_executor = None
_runtime = None


def _evidence_cited_by_answer(answer: str, evidence: list[Evidence]) -> list[Evidence]:
    """Keep only evidence explicitly bound to final answer clauses.

    Retrieval diagnostics may contain useful but unused chunks. Exposing all
    of them as API citations makes a structurally valid source look like
    support for claims it never backed. The grounding sanitizer renumbers
    references in the final answer; these are the authoritative presentation
    set. If the answer has no valid reference markers, fail closed and expose
    no citations instead of presenting the entire retrieval context as proof.
    """
    return _project_answer_citations(answer, evidence)[1]


def _project_answer_citations(
    answer: str,
    evidence: list[Evidence],
) -> tuple[str, list[Evidence]]:
    """Return only cited evidence and compact its visible reference ranks.

    ``build_context_from_evidence`` assigns citation ranks from 1 in the
    projected list. The final answer must use that same rank space; otherwise
    a sole ``[Evidence 3]`` reference can point at the second/third citation
    card after unused retrieval chunks are removed.
    """
    used_ranks = sorted(
        {
            int(value)
            for value in re.findall(r"\[Evidence\s+(\d+)\]", str(answer), re.I)
            if 1 <= int(value) <= len(evidence)
        }
    )
    rank_map = {old_rank: new_rank for new_rank, old_rank in enumerate(used_ranks, 1)}
    projected = [evidence[old_rank - 1] for old_rank in used_ranks]

    def replace_rank(match: re.Match[str]) -> str:
        old_rank = int(match.group(1))
        new_rank = rank_map.get(old_rank)
        return f"[Evidence {new_rank}]" if new_rank is not None else ""

    compacted_answer = re.sub(
        r"\[Evidence\s+(\d+)\]",
        replace_rank,
        str(answer),
        flags=re.I,
    )
    return compacted_answer, projected


def _prioritize_explicit_audit_disclosure(
    question: str,
    evidence: Sequence[Evidence],
) -> list[Evidence]:
    """Put a source chunk that explicitly states auditor and opinion first."""
    items = list(evidence)
    if not _AUDIT_FACT_QUESTION.search(question or ""):
        return items
    direct = [
        item
        for item in items
        if _AUDIT_FIRM_EVIDENCE.search(item.content or "")
        and _POSITIVE_AUDIT_OPINION_EVIDENCE.search(item.content or "")
    ]
    direct_ids = {id(item) for item in direct}
    return [*direct, *(item for item in items if id(item) not in direct_ids)]


def _project_explicit_audit_answer(
    question: str,
    evidence: Sequence[Evidence],
    response_language: str | None,
) -> str | None:
    """Render audit facts only when one retrieved source explicitly states them."""
    if not _AUDIT_FACT_QUESTION.search(question or ""):
        return None

    firm_pattern = re.compile(
        r"(?P<firm>[\u3400-\u9fffA-Za-z0-9·]{2,32}会计师事务所\s*[（(]\s*特殊普通合伙\s*[）)])",
        re.IGNORECASE,
    )
    opinion_pattern = re.compile(r"标准无保留意见|(?<!非)无保留意见")
    wants_firm = bool(re.search(r"会计师事务所|审计机构|auditor|audit firm", question, re.I))
    wants_opinion = bool(re.search(r"审计意见|audit opinion|opinion", question, re.I))

    for rank, item in enumerate(evidence, 1):
        content = item.content or ""
        firm_match = firm_pattern.search(content) if wants_firm else None
        opinion_match = opinion_pattern.search(content) if wants_opinion else None
        if wants_firm and firm_match is None:
            continue
        if wants_opinion and opinion_match is None:
            continue
        if not firm_match and not opinion_match:
            continue
        citation = f"[Evidence {rank}]"
        if response_language and response_language.casefold().startswith("en"):
            parts = []
            if firm_match:
                parts.append(f"Auditor: {firm_match.group('firm')}")
            if opinion_match:
                parts.append(f"Audit opinion: {opinion_match.group(0)}")
            return "; ".join(parts) + f" {citation}."
        parts = []
        if firm_match:
            parts.append(f"审计机构为{firm_match.group('firm')}")
        if opinion_match:
            parts.append(f"审计意见为{opinion_match.group(0)}")
        return "；".join(parts) + f" {citation}。"
    return None


def _get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever(_get_model())
    return _retriever


def _get_retrieval_tool_executor():
    global _retrieval_tool_executor
    if _retrieval_tool_executor is None:
        _retrieval_tool_executor = TenantRetrievalToolExecutor(_get_retriever())
    return _retrieval_tool_executor


intent_analyzer = IntentAnalyzer()
query_planner = QueryPlanner()

engine = StepExecutionEngine()
reasoning_engine = ReasoningEngine()

strategy_engine = StrategyExecutionEngine()

dispatcher = ExecutionDispatcher()
financial_metrics_tool_engine = ToolEngine(
    authorization_hook=authorize_financial_metrics_tool,
)


def _retrieve_handler(step, shared_context):
    executor = _get_retrieval_tool_executor()
    # A four-chunk default is adequate for a single numeric lookup but is not
    # enough for a filing summary or a comparison: headline tables, segment
    # tables, MD&A and risk disclosures commonly live on different pages.
    # Keep the request bounded while making the production context coverage
    # explicit and deterministic.
    scope = classify_query_scope(step.query or "")
    configured_top_k = step.parameters.get("top_k")
    if configured_top_k is None:
        configured_top_k = {
            QueryScope.SUMMARY: 10,
            QueryScope.COMPARE: 8,
            QueryScope.FACT: 8,
            QueryScope.ANALYSIS: 10,
            QueryScope.RISK: 8,
        }.get(scope, 6)
    retrieval_kwargs = dict(
        store=_get_store(),
        query=step.query or "",
        company=step.company,
        document_ids=step.document_ids or None,
        top_k=configured_top_k,
        filters=step.parameters.get("filters", {}),
        tenant_id=shared_context.get("tenant_id", 0),
        include_public=shared_context.get("include_public", False),
    )
    evidences = executor.execute(**retrieval_kwargs)

    # A semantically-close narrative paragraph can outrank the table that
    # contains the requested number (for example NVIDIA gross margin or
    # Apple's Services revenue).  Add a few bounded, deterministic probes to
    # the same retriever.  This enriches the context without changing the
    # hybrid ranker weights or its global top-K policy.
    probe_queries = retrieval_probe_queries(step.query or "", scope, evidences)

    if probe_queries:
        existing = {str(item.metadata.get("chunk_id") or item.source) for item in evidences}
        for probe_query in dict.fromkeys(probe_queries):
            probe = dict(retrieval_kwargs)
            probe["query"] = probe_query
            probe["top_k"] = retrieval_probe_top_k(step.query or "", probe_query)
            for item in executor.execute(**probe):
                key = str(item.metadata.get("chunk_id") or item.source)
                if key not in existing:
                    evidences.append(item)
                    existing.add(key)

    shared_context.setdefault("_all_evidence", []).extend(evidences)
    return evidences


engine.register_handler(StepType.RETRIEVE, _retrieve_handler)
engine.register_handler(StepType.COMPARE, lambda s, c: None)
engine.register_handler(StepType.SYNTHESIS, lambda s, c: None)
engine.register_handler(
    StepType.TOOL_CALL,
    FinancialMetricsStepHandler(financial_metrics_tool_engine),
)

router = ModelRouter(policy=RoutingPolicy(CapabilityRoutingPolicy()))


def _build_runtime(runtime_router: ModelRouter) -> AgentRuntime:
    return AgentRuntime(
        planner=query_planner,
        executor=engine,
        reasoner=reasoning_engine,
        retriever=_get_retriever(),
        intent_analyzer=intent_analyzer,
        router=runtime_router,
        strategy_engine=strategy_engine,
        dispatcher=dispatcher,
        workflow_engine=WorkflowEngine(),
        workflow_executor=WorkflowExecutor(),
        structured_fact_lookup=lookup_persisted_financial_fact,
    )


def _get_runtime():
    global _runtime
    if _runtime is None:
        _runtime = _build_runtime(router)
    return _runtime


def _get_request_runtime(llm_settings):
    if llm_settings is None or not llm_settings.provider_configs:
        return _get_runtime()

    request_router = ModelRouter(
        policy=RoutingPolicy(
            CapabilityRoutingPolicy(
                default_provider=llm_settings.default_provider,
                provider_models=llm_settings.provider_models,
            )
        ),
        provider_configs=llm_settings.provider_configs,
        available_providers=list(llm_settings.provider_configs),
    )
    return _build_runtime(request_router)


# =========================
# RAG MAIN
# =========================


def run_rag(
    question: str,
    company=None,
    *,
    tenant_id: int = 0,
    thread_id: str | None = None,
    conversation_history: Sequence[dict[str, Any]] | None = None,
    llm_settings=None,
    answer_language: str | None = None,
    deadline: float | None = None,
) -> RAGResult:
    research_mode = detect_research_mode(question)
    result = _get_request_runtime(llm_settings).run(
        question,
        company,
        tenant_id=tenant_id,
        thread_id=thread_id,
        conversation_history=list(conversation_history or []),
        answer_language=answer_language,
    )
    evidence_question = getattr(result, "resolved_question", None) or question

    if result.execution and result.execution.get("strategy") == "structured_financial_fact":
        # Structured facts are already deterministically verified, tenant
        # scoped, and adapted to the common citation contract. They do not
        # need provider generation or vector/BM25/reranker retrieval.
        return RAGResult(
            report=result.report,
            citations=result.citations,
            context=result.context,
            research_mode="financial_fact",
            intent=result.intent_result,
            evidence=result.evidence,
            plan=result.plan,
            routing=result.routing,
            planning=result.planning,
            execution=result.execution,
            workflow=result.workflow,
        )

    is_tool_call = result.execution and result.execution.get("strategy") == "tool_calling"
    if is_tool_call:
        # A deterministic tool result is already the final answer.  Do not
        # route it through retrieval or an LLM, and never fabricate citations.
        answer = result.context or "The financial calculation could not be completed."
        return RAGResult(
            report=answer,
            citations=[],
            context=result.context,
            research_mode=research_mode,
            intent=result.intent_result,
            evidence=[],
            plan=result.plan,
            routing=result.routing,
            planning=result.planning,
            execution=result.execution,
            workflow=result.workflow,
        )

    is_direct_chat = result.workflow and result.workflow.get("type") == "direct_chat"

    if is_direct_chat:
        prompt_name = "direct_chat"
        prompt_metadata = get_prompt_metadata(prompt_name)
        prompt = build_direct_chat_prompt(
            question,
            history=conversation_history,
            response_language=answer_language,
        )
        if result.planning is not None:
            result.planning["prompt"] = prompt_metadata
        provider_started = time.monotonic()
        try:
            answer = call_llm(
                prompt,
                provider=result.provider_instance,
                system_prompt=get_prompt_system_prompt(
                    prompt_name,
                    response_language=answer_language,
                ),
                deadline=deadline,
            )
        finally:
            _log_pipeline_stage("provider_request", provider_started, thread_id=thread_id)
        if not str(answer).strip():
            answer = _empty_answer_for_question(question, answer_language)
        _capture_smoke_grounding(
            question=question,
            raw_answer=str(answer),
            grounded=None,
            retrieved=[],
        )
        return RAGResult(
            report=answer,
            # Direct chat is not evidence-grounded retrieval.  Do not expose
            # incidental planner evidence as financial citations.
            citations=[],
            context="",
            research_mode=research_mode,
            intent=result.intent_result,
            evidence=[],
            plan=result.plan,
            routing=result.routing,
            planning=result.planning,
            execution=result.execution,
            workflow=result.workflow,
        )

    if company:
        from agent.planning.entity_extractor import extract_companies

        if not extract_companies(evidence_question):
            company_context = (
                f"本次问题的目标公司范围：{company}。"
                if any("\u3400" <= char <= "\u9fff" for char in str(company))
                else f"Target company context: {company}."
            )
            evidence_question = f"{evidence_question}\n{company_context}"

    # Apply deterministic semantic constraints before constructing the LLM
    # prompt.  Structural retrieval can return a real chunk from the wrong
    # company/period/metric; passing it through would invite a plausible but
    # unsupported answer and citation.
    fact_ledger = None
    required_fact_plan = None
    if result.evidence:
        gated_evidence = filter_evidence_for_query(evidence_question, result.evidence)
        gated_evidence = _prioritize_explicit_audit_disclosure(
            evidence_question,
            gated_evidence,
        )
        result.evidence = gated_evidence
        required_fact_plan = infer_required_fact_plan(evidence_question, gated_evidence)
        result.context, fact_ledger = build_evidence_first_context(
            evidence_question,
            gated_evidence,
            required_fact_plan,
        )
        _, result.citations = build_context_from_evidence(gated_evidence)

    if research_mode == "compare":
        prompt_name = "financial_compare"
        prompt_metadata = get_prompt_metadata(prompt_name)
        prompt = build_compare_prompt(
            # The planner may resolve an entityless follow-up (for example
            # ``What about its margins?``) against the previous user turn.
            # Retrieval and grounding already use that resolved question; the
            # model prompt must use the same contract or the provider can see
            # an ambiguous latest turn and answer for the wrong company.
            evidence_question,
            result.context,
            history=conversation_history,
            response_language=answer_language,
        )
    else:
        prompt_name = "financial_rag"
        prompt_metadata = get_prompt_metadata(prompt_name)
        prompt = build_prompt(
            # Keep generation scope identical to retrieval/grounding.  This
            # prevents a multi-turn follow-up from losing the inherited
            # company/period at the final provider boundary.
            evidence_question,
            result.context,
            history=conversation_history,
            response_language=answer_language,
        )

    if result.planning is not None:
        result.planning["prompt"] = prompt_metadata
        if required_fact_plan is not None and fact_ledger is not None:
            result.planning["required_fact_plan"] = required_fact_plan.as_dict(fact_ledger)
            result.planning["fact_ledger"] = fact_ledger.as_dict()

    if DEBUG_MODE:
        return RAGResult(
            report=prompt,
            citations=result.citations,
            context=result.context,
            research_mode=research_mode,
            intent=result.intent_result,
            evidence=result.evidence,
            plan=result.plan,
            routing=result.routing,
            planning=result.planning,
            execution=result.execution,
            workflow=result.workflow,
        )

    if len(result.citations) == 0:  # 计算结果长度
        no_evidence_answer = no_evidence_response(question, answer_language)
        return RAGResult(
            report=no_evidence_answer,
            citations=[],
            context="",
            research_mode=research_mode,
            intent=result.intent_result,
            evidence=result.evidence,
            plan=result.plan,
            routing=result.routing,
            planning=result.planning,
            execution=result.execution,
            workflow=result.workflow,
        )

    provider_started = time.monotonic()
    try:
        answer = call_llm(
            prompt,
            provider=result.provider_instance,
            system_prompt=get_prompt_system_prompt(
                prompt_name,
                response_language=answer_language,
            ),
            deadline=deadline,
        )
    finally:
        _log_pipeline_stage("provider_request", provider_started, thread_id=thread_id)
    raw_answer = str(answer)
    if not raw_answer.strip():
        answer = _empty_answer_for_question(question, answer_language)

    retrieved = list(result.evidence)
    explicit_audit_answer = _project_explicit_audit_answer(
        evidence_question,
        retrieved,
        answer_language,
    )
    grounding_input = explicit_audit_answer or str(answer)
    grounding_started = time.monotonic()
    final = finalize_grounded_answer(
        evidence_question,
        grounding_input,
        retrieved,
        response_language=answer_language,
    )
    _log_pipeline_stage("grounding_sanitizer", grounding_started, thread_id=thread_id)
    final_answer = _nonempty_final_answer(
        evidence_question,
        final.answer,
        answer_language,
    )
    answer, result.evidence = _project_answer_citations(final_answer, final.grounded.evidence)
    result.context, result.citations = build_context_from_evidence(result.evidence)
    if result.planning is not None:
        statuses = final.plan.statuses(final.ledger, answer)
        result.planning["required_fact_plan"] = final.plan.as_dict(final.ledger, answer)
        result.planning["fact_ledger"] = final.ledger.as_dict()
        result.planning["evidence_coverage"] = {
            "scope": final.plan.scope,
            "grade": "FULL" if all(status.answer_present for status in statuses) else "PARTIAL",
            "required": final.plan.as_dict(final.ledger, answer)["required"],
            "added_facts": len(final.added_fact_ids),
        }
        result.planning["verified_facts_only_projection"] = final.verified_facts_only_projection
        result.planning["fact_ledger_added_ids"] = list(final.added_fact_ids)
        result.planning["fact_ledger_removed_lines"] = list(final.removed_lines)

    evidence_stats = analyze_evidence(result.citations)

    # Raw reasoner extracts are retrieval diagnostics, not validated claims.
    # Keep evidence available through citations/context without reintroducing
    # an unchecked numeric appendix into the user-visible answer.
    report = build_research_report(
        question,
        answer,
        result.citations,
        evidence_stats,
        response_language=answer_language,
    )
    _capture_smoke_grounding(
        question=evidence_question, raw_answer=raw_answer, grounded=final.raw_grounding,
        retrieved=retrieved, final_grounded=final.grounded, final_report=report,
        prepared_answer=final.prepared_answer,
    )

    return RAGResult(
        report=report,
        citations=result.citations,
        context=result.context,
        research_mode=research_mode,
        intent=result.intent_result,
        evidence=result.evidence,
        plan=result.plan,
        routing=result.routing,
        planning=result.planning,
        execution=result.execution,
        workflow=result.workflow,
    )


def _empty_answer_for_question(
    question: str,
    response_language: str | None = None,
) -> str:
    """Return a user-visible answer when a provider returns an empty body."""

    is_chinese = (
        response_language == "zh-CN"
        if response_language in {"en", "zh-CN"}
        else any("\u3400" <= char <= "\u9fff" for char in str(question))
    )
    if is_chinese:
        return (
            "当前模型未返回可用内容。已完成检索，但没有获得足够的有效回答。请缩小问题范围，或补充对应公司的财报与期间。"
        )
    return (
        "The model returned no usable content. Retrieval completed, but the "
        "answer was empty. Please narrow the question or provide the relevant "
        "company filing and reporting period."
    )


def _nonempty_final_answer(
    question: str,
    answer: str,
    response_language: str | None = None,
) -> str:
    """Never serialize an empty answer if final grounding removed every claim."""

    return answer.strip() or no_evidence_response(question, response_language)
