# ============================================================
# SQLTool — SQL 查询工具
# ============================================================
# 执行 SQL 查询并返回结构化结果。
# SQL execution is intentionally disabled until a separately reviewed,
# read-only, tenant-aware database adapter is introduced.
# ============================================================

from agent.tools.base_tool import BaseTool
from agent.tools.tool_context import ToolContext
from agent.tools.tool_enums import ToolStatus, ToolType
from agent.tools.tool_models import ToolCapability, ToolMetadata
from agent.tools.tool_result import ToolResult


class SQLTool(BaseTool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="sql",
            tool_type=ToolType.SQL,
            description="Disabled: SQL execution has no approved read-only adapter",
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
            error="SQL execution is disabled; no approved database adapter is configured",
            metadata={"tool": "SQLTool", "availability": "disabled"},
        )
