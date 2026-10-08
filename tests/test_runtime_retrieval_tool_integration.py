from __future__ import annotations

from dataclasses import dataclass

from agent.reasoning_models import Evidence
from agent.tools.tool_registry import ToolRegistry
from api.schemas.response import Citation
from core.context_builder import build_context_from_evidence
from core.retrieval_tool_adapter import TenantRetrievalToolExecutor


@dataclass
class _RecordingRetriever:
    contexts: list

    def retrieve_evidence(self, context, store):
        self.contexts.append((context, store))
        return [
            Evidence(
                content="Tesla revenue grew year over year.",
                source="Tesla_Q2_2025.pdf",
                company="Tesla",
                confidence=0.93,
                metadata={"chunk_id": "tesla-q2-04", "document_id": "tesla-q2"},
            )
        ]


def test_runtime_retrieval_executes_registered_tool_with_trusted_tenant_scope():
    retriever = _RecordingRetriever(contexts=[])
    store = object()

    evidence = TenantRetrievalToolExecutor(retriever).execute(
        store=store,
        query="Analyze Tesla revenue growth",
        tenant_id=17,
        company="Tesla",
        document_ids=["tesla-q2"],
        top_k=3,
        filters={"year": 2025},
        include_public=True,
    )

    context, received_store = retriever.contexts[0]
    assert received_store is store
    assert context.tenant_id == 17
    assert context.include_public is True
    assert context.company == "Tesla"
    assert context.document_ids == ["tesla-q2"]
    assert context.filters == {"year": 2025}
    assert evidence[0].source == "Tesla_Q2_2025.pdf"
    assert evidence[0].confidence == 0.93
    assert evidence[0].metadata["chunk_id"] == "tesla-q2-04"
    _, citations = build_context_from_evidence(evidence)
    assert Citation.model_validate(citations[0]).similarity == 0.93


def test_runtime_retrieval_restores_builtin_registration_after_registry_reset():
    ToolRegistry.clear()
    retriever = _RecordingRetriever(contexts=[])

    evidence = TenantRetrievalToolExecutor(retriever).execute(
        store=object(),
        query="Analyze Tesla",
        tenant_id=17,
    )

    assert len(evidence) == 1
    assert ToolRegistry.has_tool("retrieval")
