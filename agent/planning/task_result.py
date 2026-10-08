# ============================================================
# Task Result
# ============================================================
# Output of TaskAnalyzer — one classified task with reasoning
# and extracted entities. UI can display the reason for
# explainable task classification.
# ============================================================

from dataclasses import dataclass, field

from .task_models import TaskModel


@dataclass(slots=True)
class TaskResult:
    task: TaskModel

    reason: str

    extracted_entities: list[str] = field(default_factory=list)

    estimated_tokens: int = 0
