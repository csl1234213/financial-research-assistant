"""Runtime composition for the tenant-scoped retrieval tool.

The tool package owns validation and its stable result contract.  This module
is the only place that knows how that contract maps to the application's
``HybridRetriever`` and ``Evidence`` models.  Keeping the wiring here means
new retrievers can be swapped in without making the tool layer depend on the
vector store or the Agent Runtime.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from agent.reasoning_models import Evidence
from agent.tools import ToolContext, ToolEngine, ToolStatus, ToolType, trusted_retrieval_adapter
from agent.tools.implementations import register_builtin_tools
from agent.tools.retrieval_contract import RetrievalRequest
from retrieval.retrieval_context import RetrievalContext
from storage.embedding_store import EmbeddingStore


class EvidenceRetriever(Protocol):
    """The small retriever surface required by the runtime tool adapter."""

    def retrieve_evidence(
        self,
        context: RetrievalContext,
        store: EmbeddingStore,
    ) -> list[Evidence]: ...


class RetrievalToolExecutionError(RuntimeError):
    """Raised when a retrieval tool result cannot safely continue the plan."""


class RuntimeRetrievalAdapter:
    """Translate a trusted tool request into the application's retriever call."""

    def __init__(self, retriever: EvidenceRetriever, store: EmbeddingStore) -> None:
        self._retriever = retriever
        self._store = store

    def retrieve(self, request: RetrievalRequest) -> Iterable[Evidence]:
        context = RetrievalContext(
            question=request.query,
            company=request.company,
            document_ids=list(request.document_ids) or None,
            top_k=request.top_k,
            filters=dict(request.filters),
            tenant_id=request.tenant_id,
            include_public=request.include_public,
        )
        primary = self._retriever.retrieve_evidence(context=context, store=self._store)
        # Shadow is diagnostic only: failures cannot change or block primary evidence.
        try:
            from core.tree_shadow_runtime import submit_runtime_shadow

            submit_runtime_shadow(request, primary)
        except Exception:
            pass
        return primary


class TenantRetrievalToolExecutor:
    """Execute the registered retrieval tool with server-owned dependencies."""

    def __init__(self, retriever: EvidenceRetriever, engine: ToolEngine | None = None) -> None:
        register_builtin_tools()
        self._retriever = retriever
        self._engine = engine or ToolEngine()

    def execute(
        self,
        *,
        store: EmbeddingStore,
        query: str,
        tenant_id: int,
        company: str | None = None,
        document_ids: list[str] | None = None,
        top_k: int = 4,
        filters: Mapping[str, object] | None = None,
        include_public: bool = False,
    ) -> list[Evidence]:
        adapter = RuntimeRetrievalAdapter(self._retriever, store)
        result = self._engine.execute(
            ToolContext(
                tenant_id=tenant_id,
                parameters={
                    "query": query,
                    "company": company,
                    "document_ids": document_ids or [],
                    "top_k": top_k,
                    "filters": dict(filters or {}),
                    "include_public": include_public,
                    "retrieval_adapter": trusted_retrieval_adapter(
                        adapter,
                        name="hybrid_retriever",
                    ),
                },
            ),
            ToolType.RETRIEVAL,
        )
        if result.status is not ToolStatus.SUCCESS:
            raise RetrievalToolExecutionError(
                "tenant-scoped retrieval tool failed: " + (result.error or "unknown error")
            )
        return evidence_from_tool_output(result.output)


def evidence_from_tool_output(output: object) -> list[Evidence]:
    """Rehydrate downstream evidence exclusively from the tool result contract."""

    if not isinstance(output, Mapping):
        raise RetrievalToolExecutionError("retrieval tool returned a non-mapping output")
    records = output.get("evidence")
    if not isinstance(records, list):
        raise RetrievalToolExecutionError("retrieval tool output is missing evidence records")

    evidences: list[Evidence] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise RetrievalToolExecutionError("retrieval tool returned an invalid evidence record")
        content = record.get("content")
        source = record.get("source_filename")
        if not isinstance(content, str) or not isinstance(source, str):
            raise RetrievalToolExecutionError("retrieval tool returned incomplete evidence")

        score = record.get("similarity_score")
        confidence = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0.0
        metadata = record.get("metadata")
        normalized_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        for key in ("document_id", "chunk_id", "page", "rank"):
            value = record.get(key)
            if value is not None:
                normalized_metadata[key] = value

        company = record.get("company")
        evidences.append(
            Evidence(
                content=content,
                source=source,
                company=company if isinstance(company, str) else "",
                confidence=confidence,
                metadata=normalized_metadata,
            )
        )
    return evidences
