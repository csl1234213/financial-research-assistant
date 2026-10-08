# ============================================================
# Workflow Registry — Central registration for all workflows
# ============================================================
# Why registry instead of hardcoding in Factory?
#
# 1. Open/Closed Principle: Add new workflows without modifying Factory
# 2. Plugin architecture: Workflows can be registered dynamically
# 3. Separation of concerns: Registry knows who, Factory knows how to create
#
# Mirrors:
#   WorkflowRegistry ↔ StrategyRegistry
#   WorkflowRegistry ↔ ProviderRegistry
# ============================================================

from typing import Dict, List, Type

from .base_workflow import BaseWorkflow
from .workflow_exceptions import WorkflowNotFound, WorkflowRegistrationError


class WorkflowRegistry:
    _registry: Dict[str, Type[BaseWorkflow]] = {}

    @classmethod
    def register(cls, name: str, workflow_class: Type[BaseWorkflow]) -> None:
        if not issubclass(workflow_class, BaseWorkflow):
            raise WorkflowRegistrationError(f"'{workflow_class.__name__}' must be a subclass of BaseWorkflow")
        cls._registry[name] = workflow_class

    @classmethod
    def get(cls, name: str) -> Type[BaseWorkflow]:
        if not cls.has_workflow(name):
            raise WorkflowNotFound(f"Workflow '{name}' not registered. Available: {cls.list_workflows()}")
        return cls._registry[name]

    @classmethod
    def list_workflows(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def has_workflow(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()
