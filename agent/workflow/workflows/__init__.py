# ============================================================
# Workflows — Auto-registration
# ============================================================
# Importing this package automatically registers all built-in
# workflow classes into the WorkflowRegistry.
#
# Mirrors:
#   agent.execution.strategies.__init__  (auto-registration via import)
#   agent.execution.handlers.__init__    (auto-registration via import)
# ============================================================

from agent.workflow.workflow_registry import WorkflowRegistry

from .comparison_workflow import ComparisonWorkflow
from .direct_chat_workflow import DirectChatWorkflow
from .rag_workflow import RAGWorkflow
from .research_workflow import ResearchWorkflow
from .tool_pipeline_workflow import ToolPipelineWorkflow

WorkflowRegistry.register("direct_chat", DirectChatWorkflow)
WorkflowRegistry.register("rag", RAGWorkflow)
WorkflowRegistry.register("multi_step", ResearchWorkflow)
WorkflowRegistry.register("parallel", ComparisonWorkflow)
WorkflowRegistry.register("tool_pipeline", ToolPipelineWorkflow)

__all__ = [
    "DirectChatWorkflow",
    "RAGWorkflow",
    "ResearchWorkflow",
    "ToolPipelineWorkflow",
    "ComparisonWorkflow",
]
