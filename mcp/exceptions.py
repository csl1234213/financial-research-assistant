"""Exceptions used by the local MCP governance boundary."""


class MCPError(Exception):
    """Base exception for local MCP adapter failures."""


class MCPProtocolError(MCPError):
    """Raised when an MCP-shaped request is malformed."""


class SchemaDefinitionError(MCPError):
    """Raised for unsupported or malformed input schemas."""


class SchemaValidationError(MCPError):
    """Raised when call arguments do not satisfy a tool input schema."""


class ToolNotAllowed(MCPError):
    """Raised when a tool is absent from the configured allowlist."""


class ToolAuthorizationDenied(MCPError):
    """Raised when an explicit authorization hook refuses a call."""


class ToolNotRegistered(MCPError):
    """Raised when an allowed tool has no local handler."""


class ToolExecutionError(MCPError):
    """Raised when a local tool handler fails."""
