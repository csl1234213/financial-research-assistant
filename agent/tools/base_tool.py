# ============================================================
# BaseTool — Abstract interface for all tool implementations
# ============================================================
# 每一个具体 Tool（RetrievalTool、OCR Tool、
# PythonTool、SQLTool 等）都必须实现这个接口。
#
# 设计原则：
#   - Tool 不负责决定「要不要执行」— 由 Engine 决定
#   - Tool 只负责 metadata / supports / execute
#   - 不包含初始化、关闭等生命周期接口
#   - 不包含 Runtime / Provider / ToolEngine 依赖
#
# Mirrors:
#   BaseMemory      ↔ BaseTool
#   BaseWorkflow    ↔ BaseTool
#   BaseProvider    ↔ BaseTool
# ============================================================

from abc import ABC, abstractmethod

from .tool_context import ToolContext
from .tool_models import ToolMetadata
from .tool_result import ToolResult


class BaseTool(ABC):
    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata: ...

    @abstractmethod
    def supports(
        self,
        context: ToolContext,
    ) -> bool: ...

    @abstractmethod
    def execute(
        self,
        context: ToolContext,
    ) -> ToolResult: ...
