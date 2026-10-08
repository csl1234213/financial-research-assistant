# ============================================================
# Workflow Module — Workflow Layer
# ============================================================
# Unified data models for workflow composition.
# Workflow 不替代 Execution。
# Workflow 负责：多个 Execution 如何组成一个完整任务。
#
# Architecture mirrors:
#   agent.execution  → agent.workflow
#   agent.planning   → agent.workflow
# ============================================================

from .base_workflow import BaseWorkflow
from .workflow_bridge import WorkflowBridge
from .workflow_context import WorkflowContext
from .workflow_engine import WorkflowEngine
from .workflow_enums import WorkflowStatus, WorkflowType
from .workflow_exceptions import (
    WorkflowError,
    WorkflowNotFound,
    WorkflowRegistrationError,
)
from .workflow_executor import ExecutionRunner, WorkflowExecutor
from .workflow_factory import WorkflowFactory
from .workflow_models import WorkflowStep
from .workflow_registry import WorkflowRegistry
from .workflow_result import WorkflowResult

# Auto-register all workflow implementations
from .workflows import (  # noqa: F401 — auto-registration
    ComparisonWorkflow,
    DirectChatWorkflow,
    RAGWorkflow,
    ResearchWorkflow,
    ToolPipelineWorkflow,
)

__all__ = [
    "WorkflowStatus",
    "WorkflowType",
    "WorkflowContext",
    "WorkflowStep",
    "WorkflowResult",
    "BaseWorkflow",
    "WorkflowError",
    "WorkflowNotFound",
    "WorkflowRegistrationError",
    "WorkflowRegistry",
    "WorkflowFactory",
    "WorkflowEngine",
    "WorkflowBridge",
    "ExecutionRunner",
    "WorkflowExecutor",
]
