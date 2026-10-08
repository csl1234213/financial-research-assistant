"""Governed MCP tool adapter and stdio server.

The reusable adapter remains independent of transport. ``python -m mcp``
provides an operator-scoped, default-deny stdio entry point without exposing a
network listener.
"""

from .exceptions import (
    MCPError,
    MCPProtocolError,
    SchemaDefinitionError,
    SchemaValidationError,
    ToolAuthorizationDenied,
    ToolExecutionError,
    ToolNotAllowed,
    ToolNotRegistered,
)
from .governance import AuthorizationDecision, AuthorizationHook, ToolAuthorizationRequest, ToolGovernance
from .local_adapter import LocalMCPAdapter, LocalTool, MCPToolResult
from .schema import validate_arguments
from .server import (
    MCP_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    MCPServer,
    MCPServerInfo,
    serve_stdio,
)

__all__ = [
    "AuthorizationDecision",
    "AuthorizationHook",
    "LocalMCPAdapter",
    "LocalTool",
    "MCPError",
    "MCPProtocolError",
    "MCP_PROTOCOL_VERSION",
    "MCPServer",
    "MCPServerInfo",
    "MCPToolResult",
    "SchemaDefinitionError",
    "SchemaValidationError",
    "ToolAuthorizationDenied",
    "ToolAuthorizationRequest",
    "ToolExecutionError",
    "ToolGovernance",
    "ToolNotAllowed",
    "ToolNotRegistered",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "serve_stdio",
    "validate_arguments",
]
