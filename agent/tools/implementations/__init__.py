# ============================================================
# Implementations — Auto-registration
# ============================================================
# Importing this package automatically registers all built-in
# tool classes into the ToolRegistry.
#
# Mirrors:
#   agent.tools.implementations.__init__  ↔ agent.memory.memories.__init__
#   agent.tools.implementations.__init__  ↔ agent.workflow.workflows.__init__
# ============================================================

from agent.tools.tool_registry import ToolRegistry

from .financial_metrics_tool import FinancialMetricsTool
from .http_tool import HttpTool
from .python_tool import PythonTool
from .retrieval_tool import RetrievalTool
from .sql_tool import SQLTool

_BUILTIN_TOOLS = {
    "retrieval": RetrievalTool,
    "financial_metrics": FinancialMetricsTool,
    "python": PythonTool,
    "sql": SQLTool,
    "http": HttpTool,
}


def register_builtin_tools() -> None:
    """Idempotently register the tools shipped with the application.

    The explicit bootstrap avoids relying solely on import side effects.  This
    keeps tests, plugin reloads, and long-running registry rebuilds isolated.
    """

    for name, tool_class in _BUILTIN_TOOLS.items():
        if not ToolRegistry.has_tool(name):
            ToolRegistry.register(
                name,
                tool_class,
                metadata=tool_class().metadata,
            )


# Preserve the original import-time bootstrap for existing callers.
register_builtin_tools()

__all__ = [
    "FinancialMetricsTool",
    "HttpTool",
    "PythonTool",
    "RetrievalTool",
    "SQLTool",
    "register_builtin_tools",
]
