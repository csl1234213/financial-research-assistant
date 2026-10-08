import pytest

from agent.tools.base_tool import BaseTool
from agent.tools.mcp_adapter import ToolEngineMCPAdapter
from agent.tools.tool_authorization import ToolAuthorizationDecision
from agent.tools.tool_context import ToolContext
from agent.tools.tool_engine import ToolEngine
from agent.tools.tool_enums import ToolStatus, ToolType
from agent.tools.tool_models import ToolMetadata
from agent.tools.tool_registry import ToolRegistry
from agent.tools.tool_result import ToolResult


class _CaptureTool(BaseTool):
    contexts = []

    @property
    def metadata(self):
        return ToolMetadata(
            name="capture",
            tool_type=ToolType.CUSTOM,
            description="Capture its local arguments",
            version="1.0.0",
        )

    def supports(self, context):
        return True

    def execute(self, context):
        self.contexts.append(context)
        return ToolResult(
            status=ToolStatus.SUCCESS,
            output={"received": context.parameters["query"]},
            metadata={"tool": "CaptureTool"},
        )


@pytest.fixture(autouse=True)
def _tool_registry():
    ToolRegistry.clear()
    _CaptureTool.contexts = []
    ToolRegistry.register("capture", _CaptureTool, metadata=_CaptureTool().metadata)
    yield
    ToolRegistry.clear()


def test_tool_engine_adapter_forwards_validated_arguments_to_a_local_tool():
    adapter = ToolEngineMCPAdapter(
        ToolEngine(),
        {
            "capture": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            }
        },
        allowed_tools={"capture"},
    )

    response = adapter.handle(
        {
            "jsonrpc": "2.0",
            "id": "capture-call",
            "method": "tools/call",
            "params": {"name": "capture", "arguments": {"query": "revenue"}},
        },
        request_context=ToolContext(parameters={"trace_id": "trace-1"}),
    )

    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"]["status"] == "success"
    assert response["result"]["structuredContent"]["output"] == {"received": "revenue"}
    assert _CaptureTool.contexts[0].parameters == {"trace_id": "trace-1", "query": "revenue"}


def test_optional_tool_engine_hook_returns_skipped_result_without_breaking_default_execution():
    denied_engine = ToolEngine(
        authorization_hook=lambda name, _context: ToolAuthorizationDecision(
            allowed=False,
            reason=f"{name} requires approval",
            metadata={"policy_id": "local-test"},
        )
    )

    denied = denied_engine.execute(ToolContext(parameters={"query": "x"}), "capture")
    assert denied.status == ToolStatus.SKIPPED
    assert denied.error == "capture requires approval"
    assert denied.metadata["governance"] == {
        "decision": "deny",
        "reason": "capture requires approval",
        "policy_id": "local-test",
    }
    assert _CaptureTool.contexts == []

    allowed = ToolEngine().execute(ToolContext(parameters={"query": "x"}), "capture")
    assert allowed.status == ToolStatus.SUCCESS
    assert _CaptureTool.contexts[0].parameters == {"query": "x"}
