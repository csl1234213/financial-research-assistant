"""Minimal MCP lifecycle and stdio transport around the governed tool adapter.

The transport targets the stable 2025-06-18 protocol revision.  It deliberately
keeps tool registration and authorization in ``LocalMCPAdapter`` so the same
governed implementation can be embedded in tests, a subprocess, or a future
Streamable HTTP adapter without duplicating policy logic.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TextIO

from .local_adapter import LocalMCPAdapter

MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = (
    MCP_PROTOCOL_VERSION,
    "2025-03-26",
)


@dataclass(frozen=True, slots=True)
class MCPServerInfo:
    name: str
    version: str
    instructions: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("server name must be non-empty")
        if not self.version.strip():
            raise ValueError("server version must be non-empty")


class MCPServer:
    """Connection-scoped MCP lifecycle for one governed local adapter."""

    def __init__(
        self,
        adapter: LocalMCPAdapter,
        *,
        server_info: MCPServerInfo,
    ) -> None:
        if not isinstance(adapter, LocalMCPAdapter):
            raise TypeError("adapter must be a LocalMCPAdapter")
        self._adapter = adapter
        self._server_info = server_info
        self._phase = "new"
        self._negotiated_protocol: str | None = None

    @property
    def ready(self) -> bool:
        return self._phase == "ready"

    @property
    def negotiated_protocol(self) -> str | None:
        return self._negotiated_protocol

    def handle(
        self,
        request: Mapping[str, Any],
        *,
        request_context: Any = None,
    ) -> dict[str, Any] | None:
        """Handle one JSON-RPC message, suppressing responses to notifications."""

        if not isinstance(request, Mapping):
            return _error(None, -32600, "Invalid Request")

        request_id = request.get("id")
        is_notification = "id" not in request
        if request.get("jsonrpc") != "2.0":
            return None if is_notification else _error(request_id, -32600, "Invalid Request")

        method = request.get("method")
        params = request.get("params", {})
        if not isinstance(method, str) or not isinstance(params, Mapping):
            return None if is_notification else _error(request_id, -32600, "Invalid Request")

        if method == "initialize":
            response = self._initialize(request_id, params)
        elif method == "notifications/initialized":
            response = self._mark_ready(request_id)
        elif method == "ping":
            response = _result(request_id, {})
        elif self._phase != "ready":
            response = _error(
                request_id,
                -32002,
                "Server is not initialized",
            )
        else:
            response = self._adapter.handle(
                request,
                request_context=request_context,
            )

        return None if is_notification else response

    def _initialize(
        self,
        request_id: Any,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        if self._phase != "new":
            return _error(request_id, -32600, "Server is already initialized")

        requested_version = params.get("protocolVersion")
        capabilities = params.get("capabilities")
        client_info = params.get("clientInfo")
        if (
            not isinstance(requested_version, str)
            or not isinstance(capabilities, Mapping)
            or not _valid_implementation(client_info)
        ):
            return _error(request_id, -32602, "Invalid initialize parameters")

        negotiated = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else MCP_PROTOCOL_VERSION
        )
        self._negotiated_protocol = negotiated
        self._phase = "awaiting_initialized"
        result: dict[str, Any] = {
            "protocolVersion": negotiated,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": self._server_info.name,
                "version": self._server_info.version,
            },
        }
        if self._server_info.instructions:
            result["instructions"] = self._server_info.instructions
        return _result(request_id, result)

    def _mark_ready(self, request_id: Any) -> dict[str, Any]:
        if self._phase != "awaiting_initialized":
            return _error(request_id, -32600, "Initialize request is required")
        self._phase = "ready"
        return _result(request_id, {})


def serve_stdio(
    server: MCPServer,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    request_context: Any = None,
) -> None:
    """Serve newline-delimited UTF-8 JSON-RPC without logging to stdout."""

    source = input_stream or sys.stdin
    destination = output_stream or sys.stdout
    for raw_line in source:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = _error(None, -32700, "Parse error")
        else:
            response = server.handle(
                request,
                request_context=request_context,
            )

        if response is not None:
            destination.write(
                json.dumps(
                    response,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            destination.flush()


def _valid_implementation(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("name"), str)
        and bool(value["name"].strip())
        and isinstance(value.get("version"), str)
        and bool(value["version"].strip())
    )


def _result(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": dict(result),
    }


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
