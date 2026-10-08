# ============================================================
# ToolBridge — WorkflowStep metadata → ToolContext
# ============================================================
# The ToolBridge is the connector between the Workflow Layer
# and the Tool Layer. It converts declarative tool metadata
# from a WorkflowStep into a concrete ToolContext that the
# ToolEngine can execute.
#
# The Bridge does NOT make business decisions.
# It does NOT know about:
#   - Which tool to use (determined by WorkflowStep metadata)
#   - Tool implementations (ToolEngine handles that)
#   - Execution strategy (ExecutionEngine handles that)
#
# It ONLY converts:
#   WorkflowStep.metadata["tool"] → ToolContext
#
# Tool metadata format:
#   metadata = {
#       "tool": {
#           "name": "retrieval",
#           "parameters": {
#               "top_k": 5
#           }
#       }
#   }
# ============================================================

from typing import Any, Dict, Optional

from agent.tools.tool_context import ToolContext
from agent.workflow.workflow_models import WorkflowStep


class ToolBridge:
    # ============================================================
    # Detection
    # ============================================================

    @staticmethod
    def has_tool(step: WorkflowStep) -> bool:
        return "tool" in step.metadata

    # ============================================================
    # Extraction
    # ============================================================

    @staticmethod
    def get_tool_name(step: WorkflowStep) -> Optional[str]:
        tool_cfg = step.metadata.get("tool")
        if isinstance(tool_cfg, dict):
            return tool_cfg.get("name")
        return tool_cfg

    @staticmethod
    def get_tool_parameters(step: WorkflowStep) -> Dict[str, Any]:
        tool_cfg = step.metadata.get("tool")
        if isinstance(tool_cfg, dict):
            return tool_cfg.get("parameters", {})
        return {}

    # ============================================================
    # Context construction
    # ============================================================

    @staticmethod
    def to_tool_context(
        step: WorkflowStep,
        runtime_state=None,
        workflow=None,
        execution=None,
        memory=None,
    ) -> ToolContext:
        return ToolContext(
            runtime_state=runtime_state,
            workflow=workflow,
            execution=execution,
            memory=memory,
            parameters={
                **ToolBridge.get_tool_parameters(step),
                "step_id": step.step_id,
                "step_name": step.name,
            },
        )
