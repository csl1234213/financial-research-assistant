"""Production composition root for the governed MCP stdio server."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent.tools import ToolContext, ToolEngine, trusted_retrieval_adapter
from agent.tools.implementations import register_builtin_tools
from agent.tools.mcp_adapter import ToolEngineMCPAdapter
from agent.tools.retrieval_contract import RETRIEVAL_ADAPTER_PARAMETER, RetrievalAdapter
from config.app import APP_VERSION
from core.retrieval_tool_adapter import RuntimeRetrievalAdapter

from .server import MCPServer, MCPServerInfo

RETRIEVAL_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": 8_000,
        },
        "top_k": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
        },
        "company": {"type": "string", "minLength": 1},
        "document_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 100,
        },
        "filters": {
            "type": "object",
            "additionalProperties": True,
        },
        "include_public": {"type": "boolean"},
    },
    "required": ["query"],
    "additionalProperties": False,
}

FINANCIAL_METRICS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["growth_rate", "margin", "ratio", "cagr"],
        },
        "current": {"type": "number"},
        "previous": {"type": "number"},
        "numerator": {"type": "number"},
        "denominator": {"type": "number"},
        "starting_value": {"type": "number"},
        "ending_value": {"type": "number"},
        "periods": {"type": "number"},
        "precision": {
            "type": "integer",
            "minimum": 0,
            "maximum": 10,
        },
    },
    "required": ["operation"],
    "additionalProperties": False,
}

SUPPORTED_MCP_TOOLS = frozenset({"financial_metrics", "retrieval"})


def build_mcp_server(
    *,
    tenant_id: int | None,
    allowed_tools: Iterable[str] = (),
    retrieval_adapter: RetrievalAdapter | None = None,
) -> MCPServer:
    """Build a default-deny MCP server for one trusted tenant principal."""

    allowed = frozenset(allowed_tools)
    unsupported = allowed - SUPPORTED_MCP_TOOLS
    if unsupported:
        raise ValueError(
            "unsupported MCP tools: " + ", ".join(sorted(unsupported))
        )
    if allowed and (isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id <= 0):
        raise ValueError("a positive tenant_id is required when tools are enabled")

    register_builtin_tools()
    schemas = {
        "financial_metrics": FINANCIAL_METRICS_TOOL_SCHEMA,
        "retrieval": RETRIEVAL_TOOL_SCHEMA,
    }
    trusted_adapter = None
    if "retrieval" in allowed:
        adapter = retrieval_adapter or _default_retrieval_adapter()
        trusted_adapter = trusted_retrieval_adapter(
            adapter,
            name="mcp_hybrid_retriever",
        )

    def context_factory(
        _tool_name: str,
        arguments: dict[str, Any],
        _request_context: Any,
    ) -> ToolContext:
        parameters = dict(arguments)
        if trusted_adapter is not None:
            parameters[RETRIEVAL_ADAPTER_PARAMETER] = trusted_adapter
        return ToolContext(
            tenant_id=tenant_id,
            parameters=parameters,
        )

    adapter = ToolEngineMCPAdapter(
        ToolEngine(),
        schemas,
        allowed_tools=allowed,
        context_factory=context_factory,
    )
    return MCPServer(
        adapter,
        server_info=MCPServerInfo(
            name="financial-agent-tools",
            version=APP_VERSION,
            instructions=(
                "Tools are tenant-scoped and default-deny. "
                "The process operator controls the allowlist."
            ),
        ),
    )


def _default_retrieval_adapter() -> RuntimeRetrievalAdapter:
    """Create the same hybrid retrieval dependencies used by the runtime."""

    from embedding import load_embedding_model
    from retrieval.hybrid_retriever import HybridRetriever
    from storage.chroma_store import ChromaEmbeddingStore

    model = load_embedding_model()
    return RuntimeRetrievalAdapter(
        HybridRetriever(model),
        ChromaEmbeddingStore(),
    )
