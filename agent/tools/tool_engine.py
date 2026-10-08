# ============================================================
# ToolEngine — Tool Layer Orchestrator
# ============================================================
# The ToolEngine is the single entry point for the
# Tool Layer. It receives a ToolContext, creates the
# appropriate Tool instance via Factory, and delegates
# execute to that instance.
#
# The Engine does NOT make business decisions.
# It does NOT know about:
#   - Which tool to use (determined by caller)
#   - SQL / Python / HTTP / Retrieval internals
#   - Retry / Timeout / Scheduler
#   - Provider / Runtime / Workflow
#
# It ONLY orchestrates:
#   Context → Factory → Registry → Tool.supports() → Tool.execute() → Result
#
# Mirrors:
#   agent.memory.MemoryEngine      → ToolEngine
#   agent.workflow.WorkflowEngine  → ToolEngine
#   agent.execution.ExecutionEngine → ToolEngine
# ============================================================

import logging
from typing import Union

from .base_tool import BaseTool
from .tool_authorization import ToolAuthorizationHook, evaluate_authorization
from .tool_context import ToolContext
from .tool_enums import ToolStatus, ToolType
from .tool_exceptions import ToolNotSupported
from .tool_factory import ToolFactory
from .tool_result import ToolResult

logger = logging.getLogger(__name__)


class ToolEngine:
    def __init__(self, authorization_hook: ToolAuthorizationHook | None = None) -> None:
        # ``None`` preserves the original engine behavior for all existing
        # callers.  Governance-aware entry points can opt in explicitly.
        from agent.tools.implementations import register_builtin_tools

        register_builtin_tools()
        self._authorization_hook = authorization_hook

    # ============================================================
    # Execute
    # ============================================================

    def execute(
        self,
        context: ToolContext,
        tool: Union[str, ToolType],
    ) -> ToolResult:
        tool_name = tool.value if isinstance(tool, ToolType) else tool

        denied_result = self._authorization_denied_result(tool_name, context)
        if denied_result is not None:
            return denied_result

        tool_instance = self._create_tool(tool)

        if not tool_instance.supports(context):
            raise ToolNotSupported(f"Tool '{tool}' does not support the given context.")

        self.before_execute(context)
        result = tool_instance.execute(context)
        self.after_execute(result)

        logger.info(
            "ToolEngine: %s → status=%s, latency=%.2fms",
            tool,
            result.status.value,
            result.latency_ms,
        )
        return result

    # ============================================================
    # Hooks — reserved for future extension
    # ============================================================

    def before_execute(self, context: ToolContext) -> None:
        pass

    def after_execute(self, result: ToolResult) -> None:
        pass

    # ============================================================
    # Optional authorization extension
    # ============================================================

    def _authorization_denied_result(
        self,
        tool_name: str,
        context: ToolContext,
    ) -> ToolResult | None:
        if self._authorization_hook is None:
            return None

        decision = evaluate_authorization(self._authorization_hook, tool_name, context)
        if decision.allowed:
            return None
        return ToolResult(
            status=ToolStatus.SKIPPED,
            error=decision.reason or f"Tool '{tool_name}' was not authorized",
            metadata={
                "tool": tool_name,
                "governance": {
                    "decision": "deny",
                    "reason": decision.reason,
                    **dict(decision.metadata),
                },
            },
        )

    # ============================================================
    # Internal helpers
    # ============================================================

    def _create_tool(self, tool: Union[str, ToolType]) -> BaseTool:
        if isinstance(tool, ToolType):
            tool = tool.value
        return ToolFactory.create(tool)
