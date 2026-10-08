# ============================================================
# Execution Result
# ============================================================
# Unified output of the Execution Strategy Layer.
# Describes HOW a task should be executed — strategy type,
# estimated steps, parallelism, retrieval/tool flags, and
# confidence. All fields are consumed by the Runtime.
# ============================================================

from dataclasses import dataclass, field
from typing import Any, List

from .strategy_enums import ExecutionStrategyType


@dataclass(slots=True)
class ExecutionResult:
    """
    Strategy Execution Result

    Result of execution strategy planning.
    Describes HOW a task should be executed — strategy type,
    estimated steps, parallelism, retrieval/tool flags, and
    confidence. All fields are consumed by the Runtime.

    Different from:
    agent.execution_result.ExecutionResult (Step Execution Result)
    which is the result of executing one individual workflow step.
    """

    strategy: ExecutionStrategyType

    reason: str

    estimated_steps: int = 1

    parallelism: int = 1

    use_retrieval: bool = False

    use_tools: bool = False

    confidence: float = 1.0

    tool_results: List[Any] = field(default_factory=list)
