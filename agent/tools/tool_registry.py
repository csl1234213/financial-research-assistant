# ============================================================
# Tool Registry — Central registration for all tool implementations
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new tools without modifying Factory
# 2. Plugin architecture: Tools can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
# 4. Metadata index: Runtime can query ToolType / ToolCapability
#    without instantiating the Tool
#
# Mirrors:
#   ToolRegistry ↔ MemoryRegistry
#   ToolRegistry ↔ WorkflowRegistry
#   ToolRegistry ↔ StrategyRegistry
# ============================================================

from typing import Dict, List, Optional, Type

from .base_tool import BaseTool
from .tool_exceptions import ToolNotFound, ToolRegistrationError
from .tool_models import ToolMetadata


class ToolRegistry:
    _registry: Dict[str, Type[BaseTool]] = {}
    _metadata: Dict[str, ToolMetadata] = {}

    # ============================================================
    # Register
    # ============================================================

    @classmethod
    def register(
        cls,
        name: str,
        tool_cls: Type[BaseTool],
        metadata: Optional[ToolMetadata] = None,
    ) -> None:
        if not issubclass(tool_cls, BaseTool):
            raise ToolRegistrationError(f"'{tool_cls.__name__}' must be a subclass of BaseTool")
        cls._registry[name] = tool_cls
        if metadata is not None:
            cls._metadata[name] = metadata

    # ============================================================
    # Query
    # ============================================================

    @classmethod
    def get(cls, name: str) -> Type[BaseTool]:
        if not cls.has_tool(name):
            raise ToolNotFound(f"Tool '{name}' not registered. Available: {cls.list_tools()}")
        return cls._registry[name]

    @classmethod
    def get_metadata(cls, name: str) -> ToolMetadata:
        if name not in cls._metadata:
            raise ToolNotFound(
                f"Metadata for tool '{name}' not found. Available metadata: {list(cls._metadata.keys())}"
            )
        return cls._metadata[name]

    @classmethod
    def has_tool(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def list_tools(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def list_tools_by_type(cls, tool_type) -> List[str]:
        result = []
        for name, meta in cls._metadata.items():
            if meta.tool_type == tool_type:
                result.append(name)
        return result

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
        cls._metadata.clear()
