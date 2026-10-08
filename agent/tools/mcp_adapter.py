"""Bridge registered ``ToolEngine`` tools into the local MCP-shaped adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeAlias

from mcp import AuthorizationHook, LocalMCPAdapter, LocalTool

from .tool_context import ToolContext
from .tool_engine import ToolEngine
from .tool_registry import ToolRegistry

ToolContextFactory: TypeAlias = Callable[[str, Mapping[str, Any], Any], ToolContext]


class ToolEngineMCPAdapter(LocalMCPAdapter):
    """Expose explicitly declared ToolEngine tools through local MCP methods.

    ``tool_schemas`` is deliberately required: registry metadata describes a
    tool but does not declare its callable argument schema.  The inherited
    allowlist still defaults to empty, so merely constructing this bridge does
    not make any ToolEngine capability callable.
    """

    def __init__(
        self,
        engine: ToolEngine,
        tool_schemas: Mapping[str, Mapping[str, Any]],
        *,
        allowed_tools: Iterable[str] = (),
        authorization_hook: AuthorizationHook | None = None,
        context_factory: ToolContextFactory | None = None,
    ) -> None:
        self._engine = engine
        self._context_factory = context_factory or _default_context_factory
        tools = [self._make_local_tool(name, schema) for name, schema in tool_schemas.items()]
        super().__init__(
            tools,
            allowed_tools=allowed_tools,
            authorization_hook=authorization_hook,
        )

    def _make_local_tool(self, name: str, schema: Mapping[str, Any]) -> LocalTool:
        if not isinstance(name, str) or not name:
            raise ValueError("tool schema names must be non-empty strings")
        if not isinstance(schema, Mapping):
            raise TypeError(f"schema for tool '{name}' must be an object")

        description = f"Local ToolEngine tool: {name}"
        if ToolRegistry.has_tool(name):
            try:
                description = ToolRegistry.get_metadata(name).description
            except Exception:
                # Metadata is optional in the existing registry.  A generic
                # local description is safer than requiring a registry change.
                pass

        def invoke(arguments: Mapping[str, Any], request_context: Any, *, tool_name: str = name) -> Any:
            context = self._context_factory(tool_name, arguments, request_context)
            return self._engine.execute(context, tool_name)

        return LocalTool(
            name=name,
            description=description,
            input_schema=schema,
            handler=lambda _arguments: None,
            context_handler=invoke,
        )


def _default_context_factory(
    _tool_name: str,
    arguments: Mapping[str, Any],
    request_context: Any,
) -> ToolContext:
    if isinstance(request_context, ToolContext):
        return ToolContext(
            runtime_state=request_context.runtime_state,
            workflow=request_context.workflow,
            execution=request_context.execution,
            memory=request_context.memory,
            parameters={**request_context.parameters, **dict(arguments)},
            tenant_id=request_context.tenant_id,
        )
    return ToolContext(parameters=dict(arguments))
