# ============================================================
# HttpTool — HTTP 请求工具
# ============================================================
# 发送 HTTP 请求并返回响应。
# HTTP execution is intentionally disabled.  This tool never issues
# request-controlled network calls.
# ============================================================

from agent.tools.base_tool import BaseTool
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolStatus, ToolType
from agent.tools.tool_models import ToolCapability, ToolMetadata
from agent.tools.tool_result import ToolResult


class HttpTool(BaseTool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="http",
            tool_type=ToolType.HTTP,
            description="Disabled: outbound HTTP calls are not approved",
            version="1.0.0",
            capability=ToolCapability(),
            metadata={"availability": "disabled"},
        )

    def supports(self, context: ToolContext) -> bool:
        return True

    def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(
            status=ToolStatus.SKIPPED,
            output=None,
            latency_ms=0.0,
            error="HTTP execution is disabled; no outbound network adapter is configured",
            metadata={"tool": "HttpTool", "availability": "disabled"},
        )
