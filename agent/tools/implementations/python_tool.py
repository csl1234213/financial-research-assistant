# ============================================================
# PythonTool — Python 代码执行工具
# ============================================================
# 在沙箱中执行 Python 代码片段。
# Python execution is intentionally disabled.  This tool never evaluates
# request-provided code and is not a sandbox implementation.
# ============================================================

from agent.tools.base_tool import BaseTool
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolStatus, ToolType
from agent.tools.tool_models import ToolCapability, ToolMetadata
from agent.tools.tool_result import ToolResult


class PythonTool(BaseTool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="python",
            tool_type=ToolType.PYTHON,
            description="Disabled: arbitrary Python execution is not available",
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
            error="Python execution is disabled; no sandbox is configured",
            metadata={"tool": "PythonTool", "availability": "disabled"},
        )
