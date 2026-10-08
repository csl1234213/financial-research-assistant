from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TaskType(str, Enum):
    PROCESS_DOCUMENT = "process_document"
    FORMAL_READY_DOCUMENT = "formal_ready_document"
    REFRESH_KNOWLEDGE = "refresh_knowledge"
    AGENT_TASK = "agent_task"


@dataclass
class Task:
    id: str
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    tenant_id: Optional[int] = None
    user_id: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    progress: int = 0
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
