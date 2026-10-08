from __future__ import annotations

from dataclasses import dataclass

from agent.tools.implementations.retrieval_tool import RetrievalTool
from agent.tools.mcp_adapter import _default_context_factory
from agent.tools.retrieval_contract import RetrievalRequest, trusted_retrieval_adapter
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolStatus


class TestRetrievalTool:
    def test_citation_keeps_structured_file_locator(self):
        result = RetrievalTool(
            lambda _request: [
                {
                    "content": "Metric: Revenue | Q1 FY2026: 81.6 billion USD",
                    "source": "nvidia.xlsx",
                    "document_id": "nvidia-q1",
                    "chunk_id": "nvidia-q1-0",
                    "metadata": {
                        "source_locator": "Sheet 'Income Statement', row 4, columns A–C",
                        "content_type": "table",
                        "source_format": "xlsx",
                    },
                }
            ]
        ).execute(ToolContext(tenant_id=1, parameters={"query": "NVIDIA Q1 revenue"}))

        assert result.status is ToolStatus.SUCCESS
        assert result.output["citations"][0]["source_locator"] == (
            "Sheet 'Income Statement', row 4, columns A–C"
        )
        assert result.output["citations"][0]["content_type"] == "table"

    def test_executes_only_with_tenant_scope_and_trusted_adapter(self):
        received: list[RetrievalRequest] = []

        def retrieve(request: RetrievalRequest):
            received.append(request)
            return [
                {
                    "content": "Tesla revenue increased year over year.",
                    "source": "Tesla_Q2_2025.pdf",
                    "score": 0.93,
                    "document_id": "tesla-q2-2025",
                    "chunk_id": "tesla-q2-2025-04",
                    "page": 4,
                    "company": "Tesla",
                    "metadata": {"section": "Revenue", "year": 2025},
                }
            ]

        adapter = trusted_retrieval_adapter(retrieve, name="financial_retriever")
        result = RetrievalTool().execute(
            ToolContext(
                tenant_id=12,
                parameters={
                    "query": "  Analyze Tesla revenue growth  ",
                    "top_k": 3,
                    "company": "Tesla",
                    "document_ids": ["tesla-q2-2025"],
                    "filters": {"year": 2025},
                    "include_public": True,
                    "retrieval_adapter": adapter,
                },
            )
        )

        assert result.status is ToolStatus.SUCCESS
        assert received == [
            RetrievalRequest(
                query="Analyze Tesla revenue growth",
                tenant_id=12,
                top_k=3,
                company="Tesla",
                document_ids=("tesla-q2-2025",),
                filters={"year": 2025},
                include_public=True,
            )
        ]
        assert result.metadata["tenant_id"] == 12
        assert result.output == {
            "query": "Analyze Tesla revenue growth",
            "tenant_id": 12,
            "result_count": 1,
            "evidence": [
                {
                    "rank": 1,
                    "content": "Tesla revenue increased year over year.",
                    "source_filename": "Tesla_Q2_2025.pdf",
                    "similarity_score": 0.93,
                    "document_id": "tesla-q2-2025",
                    "chunk_id": "tesla-q2-2025-04",
                    "page": 4,
                    "company": "Tesla",
                    "metadata": {"section": "Revenue", "year": 2025},
                }
            ],
            "citations": [
                {
                    "rank": 1,
                    "source_filename": "Tesla_Q2_2025.pdf",
                    "document_id": "tesla-q2-2025",
                    "chunk_id": "tesla-q2-2025-04",
                    "page": 4,
                    "similarity_score": 0.93,
                }
            ],
        }

    def test_rejects_missing_query_without_calling_adapter(self):
        calls = []
        adapter = trusted_retrieval_adapter(lambda request: calls.append(request), name="test")

        result = RetrievalTool().execute(
            ToolContext(tenant_id=4, parameters={"retrieval_adapter": adapter})
        )

        assert result.status is ToolStatus.FAILED
        assert result.error == "query is required"
        assert result.metadata["failure_code"] == "invalid_request"
        assert calls == []

    def test_rejects_missing_or_mismatched_tenant_scope(self):
        calls = []
        adapter = trusted_retrieval_adapter(lambda request: calls.append(request), name="test")

        missing_scope = RetrievalTool().execute(
            ToolContext(parameters={"query": "Tesla", "retrieval_adapter": adapter})
        )
        mismatched_scope = RetrievalTool().execute(
            ToolContext(
                tenant_id=4,
                parameters={"query": "Tesla", "tenant_id": 5, "retrieval_adapter": adapter},
            )
        )

        assert missing_scope.status is ToolStatus.FAILED
        assert missing_scope.metadata["failure_code"] == "invalid_request"
        assert mismatched_scope.status is ToolStatus.FAILED
        assert mismatched_scope.error == "tenant_id parameter does not match the trusted context scope"
        assert calls == []

    def test_rejects_untrusted_callable_in_context(self):
        result = RetrievalTool().execute(
            ToolContext(
                tenant_id=4,
                parameters={"query": "Tesla", "retrieval_adapter": lambda request: []},
            )
        )

        assert result.status is ToolStatus.FAILED
        assert result.metadata["failure_code"] == "adapter_unavailable"

    def test_constructor_dependency_injection_is_explicit_and_works(self):
        received: list[RetrievalRequest] = []
        tool = RetrievalTool(
            lambda request: received.append(request)
            or [{"content": "Revenue evidence", "source": "Tesla_Q2_2025.pdf"}]
        )

        result = tool.execute(ToolContext(tenant_id=4, parameters={"query": "Tesla revenue"}))

        assert result.status is ToolStatus.SUCCESS
        assert received[0].tenant_id == 4
        assert result.metadata["adapter"] == "injected_retriever"

    def test_adapter_exception_is_a_truthful_failure(self):
        def broken_adapter(_request: RetrievalRequest):
            raise RuntimeError("connection refused")

        result = RetrievalTool(broken_adapter).execute(
            ToolContext(tenant_id=4, parameters={"query": "Tesla revenue"})
        )

        assert result.status is ToolStatus.FAILED
        assert result.error == "trusted retrieval adapter failed"
        assert result.metadata["failure_code"] == "adapter_failure"
        assert result.metadata["exception_type"] == "RuntimeError"

    def test_invalid_adapter_evidence_is_a_truthful_failure(self):
        result = RetrievalTool(lambda _request: [{"source": "missing-content.pdf"}]).execute(
            ToolContext(tenant_id=4, parameters={"query": "Tesla revenue"})
        )

        assert result.status is ToolStatus.FAILED
        assert result.metadata["failure_code"] == "invalid_adapter_result"
        assert result.error == "retrieval evidence requires non-empty content"

    def test_empty_evidence_is_successful_but_not_fabricated(self):
        result = RetrievalTool(lambda _request: []).execute(
            ToolContext(tenant_id=4, parameters={"query": "No matching report"})
        )

        assert result.status is ToolStatus.SUCCESS
        assert result.output["result_count"] == 0
        assert result.output["evidence"] == []
        assert result.output["citations"] == []


@dataclass
class _ObjectAdapter:
    requests: list[RetrievalRequest]

    def retrieve(self, request: RetrievalRequest):
        self.requests.append(request)
        return [{"content": "Object adapter evidence", "source": "report.pdf"}]


def test_adapter_protocol_is_supported_for_server_side_dependency_injection():
    adapter = _ObjectAdapter(requests=[])
    result = RetrievalTool(adapter).execute(
        ToolContext(tenant_id=1, parameters={"query": "Quarterly report"})
    )

    assert result.status is ToolStatus.SUCCESS
    assert adapter.requests[0].query == "Quarterly report"


def test_mcp_context_factory_preserves_the_trusted_tenant_scope():
    original = ToolContext(tenant_id=9, parameters={"retrieval_adapter": object()})

    derived = _default_context_factory("retrieval", {"query": "Tesla revenue"}, original)

    assert derived.tenant_id == 9
    assert derived.parameters["query"] == "Tesla revenue"
    assert derived.parameters["retrieval_adapter"] is original.parameters["retrieval_adapter"]
