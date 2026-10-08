from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ExecutionResult:
    """
    Step Execution Result

    Result of executing one workflow step.
    Produced by the Step Execution Engine (agent/execution_engine.py).

    Different from:
    agent.execution.execution_result.ExecutionResult (Strategy Execution Result)
    which describes the overall execution strategy.
    """

    step_id: int

    success: bool

    output: Any = None

    error: Optional[str] = None

    routing: Optional[Dict[str, Any]] = None
