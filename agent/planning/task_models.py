# ============================================================
# Task Model
# ============================================================
# Core data model for one classified task.
# TaskAnalyzer produces this; Planner consumes it.
# ============================================================

from dataclasses import dataclass

from .task_enums import (
    ComplexityLevel,
    TaskType,
)


@dataclass(slots=True)
class TaskModel:
    task_type: TaskType

    confidence: float = 1.0

    complexity: ComplexityLevel = ComplexityLevel.LOW
