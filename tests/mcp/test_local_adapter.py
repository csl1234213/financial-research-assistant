import socket

import pytest

from mcp import (
    AuthorizationDecision,
    LocalMCPAdapter,
    LocalTool,
    SchemaValidationError,
    ToolNotAllowed,
)


def _echo_tool(calls):
    def echo(arguments):
        calls.append(dict(arguments))
        return {"echo": arguments["message"]}

    return LocalTool(
        name="echo",
        description="Echo a local string",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "minLength": 1},
                "repeat": {"type": "integer", "minimum": 1},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        handler=echo,
    )


def test_registered_tools_are_hidden_and_denied_without_an_allowlist():
    calls = []
    adapter = LocalMCPAdapter([_echo_tool(calls)])

    assert adapter.tools_list() == {"tools": []}
    with pytest.raises(ToolNotAllowed):
        adapter.call_tool("echo", {"message": "hello"})
    assert calls == []


def test_tools_list_and_call_use_local_mcp_shapes_without_opening_a_socket(monkeypatch):
    calls = []
    adapter = LocalMCPAdapter([_echo_tool(calls)], allowed_tools={"echo"})

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("the local adapter must not open a network socket")

    monkeypatch.setattr(socket, "socket", unexpected_network)

    listed = adapter.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo a local string",
                    "inputSchema": _echo_tool([]).input_schema,
                }
            ]
        },
    }

    called = adapter.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "hello", "repeat": 2}},
        }
    )
    assert called["jsonrpc"] == "2.0"
    assert called["id"] == 2
    assert called["result"]["isError"] is False
    assert called["result"]["structuredContent"] == {"echo": "hello"}
    assert calls == [{"message": "hello", "repeat": 2}]


def test_schema_validation_rejects_bad_arguments_before_the_handler_runs():
    calls = []
    adapter = LocalMCPAdapter([_echo_tool(calls)], allowed_tools={"echo"})

    with pytest.raises(SchemaValidationError, match="message.*required"):
        adapter.call_tool("echo", {"repeat": 1})
    with pytest.raises(SchemaValidationError, match="unexpected property"):
        adapter.call_tool("echo", {"message": "hello", "extra": True})
    assert calls == []

    response = adapter.handle(
        {
            "jsonrpc": "2.0",
            "id": "invalid",
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": ""}},
        }
    )
    assert response["error"]["code"] == -32602
    assert calls == []


def test_authorization_hook_receives_validated_context_and_denies_without_execution():
    calls = []
    observed = []

    def authorize(request):
        observed.append(request)
        if request.request_context != {"approved": True}:
            return AuthorizationDecision(False, "approval is required")
        return True

    adapter = LocalMCPAdapter(
        [_echo_tool(calls)],
        allowed_tools={"echo"},
        authorization_hook=authorize,
    )

    denied = adapter.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "blocked"}},
        }
    )
    assert denied["error"]["code"] == -32001
    assert calls == []

    allowed = adapter.call_tool(
        "echo",
        {"message": "approved"},
        request_context={"approved": True},
    )
    assert allowed["structuredContent"] == {"echo": "approved"}
    assert observed[-1].tool_name == "echo"
    assert observed[-1].arguments == {"message": "approved"}
    assert calls == [{"message": "approved"}]
