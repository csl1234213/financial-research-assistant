import json
import subprocess
import sys

import pytest

from agent.tools.retrieval_contract import RetrievalRequest
from mcp import MCP_PROTOCOL_VERSION
from mcp.app import build_mcp_server


class _CaptureRetrievalAdapter:
    def __init__(self):
        self.requests: list[RetrievalRequest] = []

    def retrieve(self, request: RetrievalRequest):
        self.requests.append(request)
        return [
            {
                "content": "Revenue increased year over year.",
                "source_filename": "Tesla_Q2_2025.pdf",
                "similarity_score": 0.91,
            }
        ]


def _ready(server):
    server.handle(
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
    server.handle(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
    )


def test_composed_retrieval_tool_injects_trusted_tenant_scope():
    retrieval = _CaptureRetrievalAdapter()
    server = build_mcp_server(
        tenant_id=17,
        allowed_tools={"retrieval"},
        retrieval_adapter=retrieval,
    )
    _ready(server)

    listed = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    called = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "retrieval",
                "arguments": {"query": "Tesla revenue", "top_k": 3},
            },
        }
    )

    assert [tool["name"] for tool in listed["result"]["tools"]] == ["retrieval"]
    assert called["result"]["isError"] is False
    assert called["result"]["structuredContent"]["output"]["result_count"] == 1
    assert retrieval.requests[0].tenant_id == 17
    assert retrieval.requests[0].query == "Tesla revenue"


def test_composed_server_is_default_deny_and_rejects_untrusted_scope():
    server = build_mcp_server(tenant_id=None)
    _ready(server)

    listed = server.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    assert listed["result"]["tools"] == []

    with pytest.raises(ValueError, match="tenant_id"):
        build_mcp_server(
            tenant_id=None,
            allowed_tools={"retrieval"},
            retrieval_adapter=_CaptureRetrievalAdapter(),
        )


def test_composed_server_exposes_a_safe_financial_metrics_tool():
    server = build_mcp_server(
        tenant_id=17,
        allowed_tools={"financial_metrics"},
    )
    _ready(server)

    called = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "financial_metrics",
                "arguments": {
                    "operation": "growth_rate",
                    "current": 125,
                    "previous": 100,
                    "precision": 2,
                },
            },
        }
    )

    structured = called["result"]["structuredContent"]
    assert called["result"]["isError"] is False
    assert structured["output"]["value"] == 25.0
    assert structured["metadata"]["side_effects"] == "none"


def test_module_entrypoint_serves_valid_stdio_without_enabling_tools():
    messages = "\n".join(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "subprocess-test",
                            "version": "1.0.0",
                        },
                    },
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                }
            ),
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-m", "mcp"],
        input=messages + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )

    responses = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[-1]["result"]["tools"] == []
