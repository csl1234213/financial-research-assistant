# ============================================================
# Workflow Factory — Creates workflow instances by name
# ============================================================
# The Factory only knows how to create, not which workflows exist.
# That knowledge lives in the Registry.
#
# Usage:
#   workflow = WorkflowFactory.create("rag")
#   workflow = WorkflowFactory.create(WorkflowType.RAG)
#   result = workflow.build(context)
#
# Mirrors agent.execution.strategy_factory.StrategyFactory:
#   WorkflowFactory ↔ StrategyFactory
# ============================================================

from typing import Optional, Union

from .base_workflow import BaseWorkflow
from .workflow_enums import WorkflowType
from .workflow_registry import WorkflowRegistry


class WorkflowFactory:
    _default_workflow: Optional[str] = None

    # ============================================================
    # Create
    # ============================================================

    @classmethod
    def create(cls, name: Union[str, WorkflowType]) -> BaseWorkflow:
        if isinstance(name, WorkflowType):
            name = name.value
        workflow_class = WorkflowRegistry.get(name)
        return workflow_class()

    # ============================================================
    # Default workflow
    # ============================================================

    @classmethod
    def set_default(cls, name: Union[str, WorkflowType]) -> None:
        if isinstance(name, WorkflowType):
            name = name.value
        if not WorkflowRegistry.has_workflow(name):
            raise KeyError(f"Cannot set default. Workflow '{name}' not registered.")
        cls._default_workflow = name

    @classmethod
    def get_default(cls) -> Optional[str]:
        return cls._default_workflow

    @classmethod
    def create_default(cls) -> BaseWorkflow:
        if cls._default_workflow is None:
            raise KeyError("No default workflow set. Call WorkflowFactory.set_default(name) first.")
        return cls.create(cls._default_workflow)

    # ============================================================
    # Discovery
    # ============================================================

    @classmethod
    def list_workflows(cls) -> list[str]:
        return WorkflowRegistry.list_workflows()
