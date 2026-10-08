# ============================================================
# Tool Factory — Creates tool instances by name or type
# ============================================================
# The Factory only knows how to create, not which tools exist.
# That knowledge lives in the Registry.
#
# Usage:
#   tool = ToolFactory.create("sql")
#   tool = ToolFactory.create(ToolType.SQL)
#   result = tool.execute(context)
#
# Mirrors:
#   ToolFactory ↔ MemoryFactory
#   ToolFactory ↔ WorkflowFactory
#   ToolFactory ↔ StrategyFactory
# ============================================================

from typing import Optional, Union

from .base_tool import BaseTool
from .tool_enums import ToolType
from .tool_registry import ToolRegistry


class ToolFactory:
    _default_tool: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, name: Union[str, ToolType]) -> BaseTool:
        if isinstance(name, ToolType):
            name = name.value
        tool_cls = ToolRegistry.get(name)
        return tool_cls()

    # ============================================================
    # Default tool
    # ============================================================

    @classmethod
    def set_default(cls, name: Union[str, ToolType]) -> None:
        if isinstance(name, ToolType):
            name = name.value
        if not ToolRegistry.has_tool(name):
            raise KeyError(f"Cannot set default. Tool '{name}' not registered.")
        cls._default_tool = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_tool

    @classmethod
    def create_default(cls) -> BaseTool:
        if cls._default_tool is None:
            raise RuntimeError("No default tool set. Call ToolFactory.set_default(...) first.")
        return cls.create(cls._default_tool)
