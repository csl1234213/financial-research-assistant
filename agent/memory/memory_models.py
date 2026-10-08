# ============================================================
# Memory Models
# ============================================================
# Core data models for the Memory Layer.
# MemoryRecord 是 Memory 的最小单位。
#
# 设计原则：
#   - 不引用 TaskResult / ExecutionResult 等复杂对象
#   - content + metadata 保持轻量，方便序列化
#   - 不包含 Runtime / Provider / Vector DB 依赖
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from .memory_enums import MemoryImportance, MemoryType


@dataclass(slots=True)
class MemoryRecord:
    id: str

    memory_type: MemoryType

    content: str

    importance: MemoryImportance

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    metadata: Dict[str, Any] = field(default_factory=dict)
