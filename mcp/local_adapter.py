"""An in-process adapter for the MCP ``tools/list`` and ``tools/call`` shapes."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, TypeAlias

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
from .governance import AuthorizationHook, ToolGovernance
from .schema import validate_arguments

ToolHandler: TypeAlias = Callable[[Mapping[str, Any]], Any]
ContextToolHandler: TypeAlias = Callable[[Mapping[str, Any], Any], Any]


@dataclass(frozen=True, slots=True)
class LocalTool:
    """A local function plus the public MCP metadata needed to call it."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: ToolHandler
    context_handler: ContextToolHandler | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("tool name must be a non-empty string")
        if not isinstance(self.description, str):
            raise TypeError("tool description must be a string")
        if not isinstance(self.input_schema, Mapping):
            raise TypeError("tool input_schema must be an object")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")
        if self.context_handler is not None and not callable(self.context_handler):
            raise TypeError("tool context_handler must be callable")

    def as_mcp_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": deepcopy(dict(self.input_schema)),
        }

    def invoke(self, arguments: Mapping[str, Any], request_context: Any) -> Any:
        if self.context_handler is not None:
            return self.context_handler(arguments, request_context)
        return self.handler(arguments)


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    """An explicit result type for handlers that need MCP-specific output."""

    content: list[Mapping[str, Any]]
    structured_content: Any = None
    is_error: bool = False

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "content": _json_safe(self.content),
            "isError": self.is_error,
        }
        if self.structured_content is not None:
            result["structuredContent"] = _json_safe(self.structured_content)
        return result


class LocalMCPAdapter:
    """Serve a fixed set of in-process tools without any network transport.

    Registering a tool does not expose it.  A name must appear in
    ``allowed_tools`` before it can be listed or called, and an optional
    authorization hook is evaluated for every validated call.
    """

    def __init__(
        self,
        tools: Iterable[LocalTool] = (),
        *,
        allowed_tools: Iterable[str] = (),
        authorization_hook: AuthorizationHook | None = None,
    ) -> None:
        self.governance = ToolGovernance(
            allowed_tools,
            authorization_hook=authorization_hook,
        )
        self._tools: dict[str, LocalTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: LocalTool) -> None:
        if not isinstance(tool, LocalTool):
            raise TypeError("only LocalTool instances can be registered")
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def tools_list(self) -> dict[str, list[dict[str, Any]]]:
        """Return an MCP-shaped list containing only allowlisted local tools."""

        return {
            "tools": [
                self._tools[name].as_mcp_definition()
                for name in sorted(self._tools)
                if self.governance.is_allowed(name)
            ]
        }

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_context: Any = None,
    ) -> dict[str, Any]:
        """Call a local tool after allowlist, schema, and hook checks."""

        if not isinstance(name, str) or not name:
            raise MCPProtocolError("tools/call requires a non-empty string name")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise SchemaValidationError("tools/call arguments must be an object")

        # Do not disclose or validate non-allowlisted tools.  This makes the
        # allowlist the first and default-deny boundary.
        self.governance.ensure_allowed(name)
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotRegistered(f"Tool '{name}' has no local handler")
        validated_arguments = validate_arguments(arguments, tool.input_schema)
        self.governance.authorize(name, validated_arguments, request_context)

        try:
            result = tool.invoke(validated_arguments, request_context)
        except MCPError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Tool '{name}' failed") from exc
        return _to_mcp_result(result)

    def handle(self, request: Mapping[str, Any], *, request_context: Any = None) -> dict[str, Any]:
        """Handle a local JSON-RPC/MCP-shaped request and return a response."""

        if not isinstance(request, Mapping):
            return self._error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0":
            return self._error(request_id, -32600, "Invalid Request")
        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str) or not isinstance(params, Mapping):
            return self._error(request_id, -32600, "Invalid Request")

        try:
            if method == "tools/list":
                return self._result(request_id, self.tools_list())
            if method == "tools/call":
                return self._result(
                    request_id,
                    self.call_tool(
                        params.get("name"),
                        params.get("arguments", {}),
                        request_context=request_context,
                    ),
                )
            return self._error(request_id, -32601, "Method not found")
        except MCPError as exc:
            return self._mcp_error(request_id, exc)
        except Exception:
            return self._error(request_id, -32603, "Internal error")

    @staticmethod
    def _result(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def _mcp_error(self, request_id: Any, exc: MCPError) -> dict[str, Any]:
        if isinstance(exc, (MCPProtocolError, SchemaValidationError, ToolNotRegistered)):
            return self._error(request_id, -32602, str(exc))
        if isinstance(exc, (ToolNotAllowed, ToolAuthorizationDenied)):
            return self._error(request_id, -32001, str(exc))
        if isinstance(exc, (SchemaDefinitionError, ToolExecutionError)):
            return self._error(request_id, -32000, str(exc))
        return self._error(request_id, -32603, "Internal error")


def _to_mcp_result(value: Any) -> dict[str, Any]:
    if isinstance(value, MCPToolResult):
        return value.as_dict()

    if _looks_like_tool_result(value):
        return _tool_result_to_mcp(value)

    safe_value = _json_safe(value)
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(safe_value, ensure_ascii=False, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": safe_value,
        "isError": False,
    }


def _looks_like_tool_result(value: Any) -> bool:
    return all(hasattr(value, attribute) for attribute in ("status", "output", "artifacts", "latency_ms", "metadata"))


def _tool_result_to_mcp(result: Any) -> dict[str, Any]:
    status = getattr(result.status, "value", result.status)
    structured_content = {
        "status": _json_safe(status),
        "output": _json_safe(result.output),
        "artifacts": _json_safe(result.artifacts),
        "latency_ms": _json_safe(result.latency_ms),
        "error": _json_safe(getattr(result, "error", None)),
        "metadata": _json_safe(result.metadata),
    }
    output = result.output
    text = output if isinstance(output, str) else json.dumps(structured_content, ensure_ascii=False, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured_content,
        "isError": status != "success",
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)
