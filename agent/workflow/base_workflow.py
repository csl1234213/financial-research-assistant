# ============================================================
# BaseWorkflow — Abstract interface for all workflows
# ============================================================
# 每一个具体 Workflow（DirectChat、RAG、RetrieveThenReason、
# MultiStep、Parallel 等）都必须实现这个接口。
#
# Mirrors:
#   BaseExecutionStrategy ↔ BaseWorkflow
#   BaseProvider          ↔ BaseWorkflow
# ============================================================

from abc import ABC, abstractmethod

from .workflow_context import WorkflowContext
from .workflow_result import WorkflowResult


class BaseWorkflow(ABC):
    @property
    @abstractmethod
    def workflow_name(self) -> str: ...

    @abstractmethod
    def supports(
        self,
        context: WorkflowContext,
    ) -> bool: ...

    @abstractmethod
    def build(
        self,
        context: WorkflowContext,
    ) -> WorkflowResult: ...
