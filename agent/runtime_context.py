from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.execution_result import ExecutionResult
from agent.reasoning_models import Evidence


@dataclass
class RuntimeContext:
    """
    Unified runtime state for one Agent execution.

    Replaces ad-hoc shared_context dict.
    Future: Memory, Conversation, Tool Cache all live here.
    """

    question: str

    company: Optional[str] = None

    tenant_id: int = 0

    thread_id: Optional[str] = None

    evidences: List[Evidence] = field(default_factory=list)

    execution_results: List[ExecutionResult] = field(default_factory=list)

    variables: Dict[str, Any] = field(default_factory=dict)
