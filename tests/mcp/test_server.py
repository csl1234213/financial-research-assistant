import io
import json

from mcp import (
    MCP_PROTOCOL_VERSION,
    LocalMCPAdapter,
    LocalTool,
    MCPServer,
    MCPServerInfo,
    serve_stdio,
)


def _server():
    adapter = LocalMCPAdapter(
        [
            LocalTool(
                name="echo",
                description="Echo a value",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additionalProperties": False,
                },
                handler=lambda arguments: {"echo": arguments["message"]},
            )
        ],
        allowed_tools={"echo"},
    )
    return MCPServer(
        adapter,
        server_info=MCPServerInfo(
            name="financial-agent-tools",
            version="test-version",
        ),
    )


def _initialize(server):
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
    )
    assert response is not None
    return response


def test_server_requires_lifecycle_before_tool_discovery():
    server = _server()

    early = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )

    assert early["error"]["code"] == -32002
    initialized = _initialize(server)
    assert initialized["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert initialized["result"]["capabilities"] == {
        "tools": {"listChanged": False}
    }
    assert server.ready is False

    notification = server.handle(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert notification is None
    assert server.ready is True

    listed = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["echo"]


def test_server_negotiates_a_supported_version_for_an_unknown_client_version():
    server = _server()

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "unknown-version",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
    )

    assert response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert server.negotiated_protocol == MCP_PROTOCOL_VERSION


def test_stdio_transport_emits_only_json_rpc_responses():
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "hello"}},
        },
    ]
    source = io.StringIO(
        "".join(json.dumps(message) + "\n" for message in messages)
    )
    destination = io.StringIO()

    serve_stdio(
        _server(),
        input_stream=source,
        output_stream=destination,
    )

    responses = [
        json.loads(line)
        for line in destination.getvalue().splitlines()
    ]
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[-1]["result"]["structuredContent"] == {"echo": "hello"}


def test_stdio_transport_returns_parse_error_for_invalid_json():
    destination = io.StringIO()

    serve_stdio(
        _server(),
        input_stream=io.StringIO("{not-json}\n"),
        output_stream=destination,
    )

    response = json.loads(destination.getvalue())
    assert response["error"] == {"code": -32700, "message": "Parse error"}
