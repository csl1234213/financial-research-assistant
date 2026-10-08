"""Tenant-scoped, dependency-injected retrieval tool.

This module intentionally contains no vector-store, model, database, or
network imports.  Production wiring supplies a ``TrustedRetrievalAdapter``;
the tool validates the request and makes the resulting evidence/citations
available in a stable, structured ``ToolResult``.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from agent.tools.base_tool import BaseTool
from agent.tools.retrieval_contract import (
    RetrievalAdapter,
    RetrievalCallable,
    RetrievalContractError,
    RetrievalRequest,
    adapter_from_context,
    normalise_evidence,
    trusted_retrieval_adapter,
)
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolStatus, ToolType
from agent.tools.tool_models import ToolCapability, ToolMetadata
from agent.tools.tool_result import ToolResult


class RetrievalTool(BaseTool):
    """Execute a trusted retrieval adapter with an explicit tenant scope.

    Passing a callable or adapter to the constructor is deliberate dependency
    injection by server-side code.  Context-based execution instead accepts
    only ``TrustedRetrievalAdapter`` instances, so request data cannot attach
    an arbitrary callable to the tool invocation.
    """

    def __init__(self, retriever: RetrievalAdapter | RetrievalCallable | None = None) -> None:
        self._adapter = (
            trusted_retrieval_adapter(retriever, name="injected_retriever") if retriever is not None else None
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="retrieval",
            tool_type=ToolType.RETRIEVAL,
            description="Retrieve tenant-scoped evidence through a trusted server-side adapter",
            version="2.0.0",
            capability=ToolCapability(
                supports_parallel=True,
                supports_stream=False,
                supports_retry=True,
                supports_async=False,
            ),
            metadata={
                "requires": ["query", "trusted tenant_id", "trusted retrieval adapter"],
                "returns": ["evidence", "citations"],
            },
        )

    def supports(self, context: ToolContext) -> bool:
        # Input validation occurs in execute() so callers receive a truthful
        # ToolResult instead of an unhandled configuration exception.
        return True

    def execute(self, context: ToolContext) -> ToolResult:
        started = perf_counter()
        try:
            request = RetrievalRequest.from_context(context)
        except RetrievalContractError as exc:
            return self._failure("invalid_request", str(exc), started)

        adapter = self._adapter or adapter_from_context(context)
        if adapter is None:
            return self._failure(
                "adapter_unavailable",
                "retrieval requires a trusted server-side retrieval adapter",
                started,
                tenant_id=request.tenant_id,
            )

        try:
            evidence = normalise_evidence(adapter.retrieve(request))
        except RetrievalContractError as exc:
            return self._failure(
                "invalid_adapter_result",
                str(exc),
                started,
                tenant_id=request.tenant_id,
                adapter=adapter.name,
            )
        except Exception as exc:  # Adapter failures must not be reported as a fake successful retrieval.
            return self._failure(
                "adapter_failure",
                "trusted retrieval adapter failed",
                started,
                tenant_id=request.tenant_id,
                adapter=adapter.name,
                exception_type=type(exc).__name__,
            )

        evidence_output = [item.as_dict(rank=index) for index, item in enumerate(evidence, start=1)]
        citations = [item.citation(rank=index) for index, item in enumerate(evidence, start=1)]
        return ToolResult(
            status=ToolStatus.SUCCESS,
            output={
                "query": request.query,
                "tenant_id": request.tenant_id,
                "result_count": len(evidence),
                "evidence": evidence_output,
                "citations": citations,
            },
            latency_ms=(perf_counter() - started) * 1_000,
            metadata={
                "tool": type(self).__name__,
                "adapter": adapter.name,
                "tenant_id": request.tenant_id,
                "include_public": request.include_public,
                "status": "completed",
            },
        )

    @staticmethod
    def _failure(
        code: str,
        error: str,
        started: float,
        **metadata: Any,
    ) -> ToolResult:
        return ToolResult(
            status=ToolStatus.FAILED,
            error=error,
            latency_ms=(perf_counter() - started) * 1_000,
            metadata={
                "tool": "RetrievalTool",
                "failure_code": code,
                "status": "failed",
                **metadata,
            },
        )
